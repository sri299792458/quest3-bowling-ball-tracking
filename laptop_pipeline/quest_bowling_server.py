import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription

try:
    from .sam2_bowling_bridge import Sam2BowlingBridge, Sam2BridgeConfig
except ImportError:
    from sam2_bowling_bridge import Sam2BowlingBridge, Sam2BridgeConfig


@dataclass
class SessionConfig:
    session_id: str
    camera_eye: int
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    sensor_width: int
    sensor_height: int
    lens_position: tuple[float, float, float]
    lens_rotation: tuple[float, float, float, float]
    target_send_fps: int
    transport: str
    video_codec: str
    target_bitrate_kbps: int


@dataclass
class LaneCalibration:
    session_id: str
    timestamp_ms: int
    is_valid: bool
    origin: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    lane_width_m: float
    lane_length_m: float


@dataclass
class FramePacket:
    session_id: str
    shot_id: str
    frame_id: int
    timestamp_us: int
    camera_position: tuple[float, float, float]
    camera_rotation: tuple[float, float, float, float]
    encoded_bytes: bytes


def decode_jpeg(encoded_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(encoded_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("JPEG decode failed")
    return image


class QuestWebRtcSession:
    def __init__(self, bridge_config: Sam2BridgeConfig, persist_jpeg_quality: int):
        self.bridge = Sam2BowlingBridge(config=bridge_config)
        self.bridge_config = bridge_config
        self.persist_jpeg_quality = int(max(40, min(95, persist_jpeg_quality)))
        self.pc = RTCPeerConnection()
        self.control_channel = None
        self.session_config: Optional[SessionConfig] = None
        self.lane_calibration: Optional[LaneCalibration] = None
        self.session_id = "pending-session"
        self.current_shot_id = "default-shot"
        self.frame_counter = 0
        self.last_frame_size = (1280, 960)
        self.bridge_lock = asyncio.Lock()
        self.video_task: Optional[asyncio.Task] = None
        self.closed = False

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"[webrtc] peer state={self.pc.connectionState} session={self.session_id}")
            if self.pc.connectionState in {"failed", "closed"}:
                await self.close()

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.attach_data_channel(channel)

        @self.pc.on("track")
        def on_track(track):
            print(f"[webrtc] track kind={track.kind} session={self.session_id}")
            if track.kind == "video":
                if self.video_task is not None:
                    self.video_task.cancel()
                self.video_task = asyncio.create_task(self.consume_video(track))

            @track.on("ended")
            async def on_ended():
                print(f"[webrtc] track ended kind={track.kind} session={self.session_id}")

    async def handle_offer(self, payload: dict) -> dict:
        session_id = payload.get("session_id")
        if session_id:
            self.session_id = session_id

        offer = RTCSessionDescription(sdp=payload["sdp"], type=payload["type"])
        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return {
            "type": self.pc.localDescription.type,
            "sdp": self.pc.localDescription.sdp,
        }

    def attach_data_channel(self, channel) -> None:
        self.control_channel = channel

        @channel.on("open")
        def on_open():
            print(f"[webrtc] data channel open session={self.session_id}")
            asyncio.create_task(
                self.send_json(
                    {
                        "kind": "tracker_status",
                        "stage": "webrtc_ready",
                        "session_id": self.session_id,
                    }
                )
            )

        @channel.on("close")
        def on_close():
            print(f"[webrtc] data channel closed session={self.session_id}")

        @channel.on("message")
        def on_message(message):
            asyncio.create_task(self.handle_control_message(message))

    async def handle_control_message(self, message) -> None:
        if isinstance(message, bytes):
            message = message.decode("utf-8")

        payload = json.loads(message)
        kind = payload.get("kind", "")

        if kind == "hello":
            self.session_id = payload.get("session_id", self.session_id)
            print(f"[webrtc] hello session={self.session_id} device={payload.get('device_name')}")
            return

        if kind == "session_config":
            self.session_config = SessionConfig(
                session_id=payload.get("session_id", self.session_id),
                camera_eye=int(payload.get("camera_eye", 0)),
                width=int(payload.get("width", self.last_frame_size[0])),
                height=int(payload.get("height", self.last_frame_size[1])),
                fx=float(payload.get("fx", 0.0)),
                fy=float(payload.get("fy", 0.0)),
                cx=float(payload.get("cx", 0.0)),
                cy=float(payload.get("cy", 0.0)),
                sensor_width=int(payload.get("sensor_width", 0)),
                sensor_height=int(payload.get("sensor_height", 0)),
                lens_position=(
                    float(payload.get("lens_position_x", 0.0)),
                    float(payload.get("lens_position_y", 0.0)),
                    float(payload.get("lens_position_z", 0.0)),
                ),
                lens_rotation=(
                    float(payload.get("lens_rotation_x", 0.0)),
                    float(payload.get("lens_rotation_y", 0.0)),
                    float(payload.get("lens_rotation_z", 0.0)),
                    float(payload.get("lens_rotation_w", 1.0)),
                ),
                target_send_fps=int(payload.get("target_send_fps", 15)),
                transport=payload.get("transport", "webrtc"),
                video_codec=payload.get("video_codec", "vp8"),
                target_bitrate_kbps=int(payload.get("target_bitrate_kbps", 0)),
            )
            self.session_id = self.session_config.session_id
            self.last_frame_size = (self.session_config.width, self.session_config.height)
            print(
                f"[webrtc] session_config session={self.session_id} "
                f"size={self.session_config.width}x{self.session_config.height} "
                f"fps={self.session_config.target_send_fps}"
            )
            await self.send_json(
                {
                    "kind": "tracker_status",
                    "stage": "session_ready",
                    "session_id": self.session_id,
                    "width": self.session_config.width,
                    "height": self.session_config.height,
                    "target_send_fps": self.session_config.target_send_fps,
                    "transport": self.session_config.transport,
                }
            )
            return

        if kind == "lane_calibration":
            self.lane_calibration = LaneCalibration(
                session_id=payload.get("session_id", self.session_id),
                timestamp_ms=int(payload.get("timestamp_ms", 0)),
                is_valid=bool(payload.get("is_valid", False)),
                origin=(
                    float(payload.get("origin_x", 0.0)),
                    float(payload.get("origin_y", 0.0)),
                    float(payload.get("origin_z", 0.0)),
                ),
                rotation=(
                    float(payload.get("rotation_x", 0.0)),
                    float(payload.get("rotation_y", 0.0)),
                    float(payload.get("rotation_z", 0.0)),
                    float(payload.get("rotation_w", 1.0)),
                ),
                lane_width_m=float(payload.get("lane_width_m", 0.0)),
                lane_length_m=float(payload.get("lane_length_m", 0.0)),
            )
            print(f"[webrtc] lane_calibration valid={self.lane_calibration.is_valid} session={self.session_id}")
            return

        if kind == "shot_marker":
            await self.handle_shot_marker(payload)
            return

        if kind == "ping":
            await self.send_json({"kind": "pong", "timestamp_ms": int(time.time() * 1000)})
            return

        print(f"[webrtc] unhandled control message kind={kind!r}")

    async def handle_shot_marker(self, payload: dict) -> None:
        marker_type = int(payload.get("marker_type", -1))
        shot_id = payload.get("shot_id") or "default-shot"
        timestamp_ms = int(payload.get("timestamp_ms", 0))
        self.current_shot_id = shot_id

        print(f"[webrtc] shot marker type={marker_type} shot={shot_id} session={self.session_id}")

        if marker_type == 2:
            fps = float(max(self.session_config.target_send_fps if self.session_config else 15, 1))
            frame_size = self.last_frame_size
            async with self.bridge_lock:
                self.bridge.start_shot(
                    session_id=self.session_id,
                    shot_id=shot_id,
                    fps=fps,
                    frame_size=frame_size,
                    decode_frame=lambda fp: decode_jpeg(fp.encoded_bytes),
                )
                events = self.bridge.drain_status_events()
            await self.send_events(events)
            return

        if marker_type == 3:
            async with self.bridge_lock:
                task = await self.bridge.end_shot_and_launch()
                events = self.bridge.drain_status_events()
            await self.send_events(events)
            if task is not None:
                result = await task
                result.setdefault("kind", "shot_result")
                result.setdefault("timestamp_ms", timestamp_ms)
                await self.send_json(result)
            return

        if marker_type == 4:
            async with self.bridge_lock:
                self.bridge.finish_active_recorder()
            await self.send_json(
                {
                    "kind": "tracker_status",
                    "stage": "tracker_reset",
                    "session_id": self.session_id,
                    "shot_id": shot_id,
                }
            )

    async def consume_video(self, track) -> None:
        try:
            while True:
                frame = await track.recv()
                image_bgr = frame.to_ndarray(format="bgr24")
                height, width = image_bgr.shape[:2]
                self.last_frame_size = (width, height)
                packet = self.build_frame_packet(image_bgr)

                async with self.bridge_lock:
                    self.bridge.buffer_frame(packet)
                    if self.bridge.active_recorder is not None:
                        self.bridge.add_frame(packet, decode_frame=lambda fp: decode_jpeg(fp.encoded_bytes))
                        events = self.bridge.drain_status_events()
                    else:
                        events = []

                if events:
                    await self.send_events(events)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[webrtc] video consume failed session={self.session_id}: {exc}")
            await self.send_json(
                {
                    "kind": "tracker_status",
                    "stage": "video_receive_failed",
                    "session_id": self.session_id,
                    "shot_id": self.current_shot_id,
                    "message": str(exc),
                }
            )

    def build_frame_packet(self, image_bgr: np.ndarray) -> FramePacket:
        ok, encoded = cv2.imencode(
            ".jpg",
            image_bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.persist_jpeg_quality],
        )
        if not ok:
            raise RuntimeError("OpenCV JPEG encode failed for WebRTC frame")

        timestamp_us = int(time.time() * 1_000_000)
        packet = FramePacket(
            session_id=self.session_id,
            shot_id=self.current_shot_id,
            frame_id=self.frame_counter,
            timestamp_us=timestamp_us,
            camera_position=(0.0, 0.0, 0.0),
            camera_rotation=(0.0, 0.0, 0.0, 1.0),
            encoded_bytes=encoded.tobytes(),
        )
        self.frame_counter += 1
        return packet

    async def send_events(self, events: list[dict]) -> None:
        for event in events:
            await self.send_json(event)

    async def send_json(self, payload: dict) -> None:
        if self.control_channel is None or self.control_channel.readyState != "open":
            return
        self.control_channel.send(json.dumps(payload, separators=(",", ":")))

    async def close(self) -> None:
        if self.closed:
            return

        self.closed = True
        async with self.bridge_lock:
            self.bridge.finish_active_recorder()

        if self.video_task is not None:
            self.video_task.cancel()
            try:
                await self.video_task
            except asyncio.CancelledError:
                pass

        await self.pc.close()


async def handle_offer(request: web.Request) -> web.Response:
    payload = await request.json()
    session = QuestWebRtcSession(
        bridge_config=request.app["bridge_config"],
        persist_jpeg_quality=request.app["persist_jpeg_quality"],
    )
    request.app["sessions"].add(session)
    answer = await session.handle_offer(payload)
    return web.json_response(answer)


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "transport": "webrtc"})


async def on_shutdown(app: web.Application) -> None:
    sessions = list(app["sessions"])
    await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)


def build_app(args) -> web.Application:
    app = web.Application()
    app["bridge_config"] = Sam2BridgeConfig(analysis_mode=args.analysis_mode)
    app["persist_jpeg_quality"] = args.persist_jpeg_quality
    app["sessions"] = set()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/api/webrtc/session", handle_offer)
    app.on_shutdown.append(on_shutdown)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Quest bowling WebRTC receiver")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5799)
    parser.add_argument("--analysis-mode", choices=("live", "synthetic"), default="live")
    parser.add_argument("--persist-jpeg-quality", type=int, default=90)
    args = parser.parse_args()

    app = build_app(args)
    print(f"[webrtc] listening on http://{args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
