import argparse
import asyncio
import json
import struct
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    from .sam2_bowling_bridge import JpegShotRecorder, Sam2BowlingBridge, Sam2BridgeConfig
except ImportError:
    from sam2_bowling_bridge import JpegShotRecorder, Sam2BowlingBridge, Sam2BridgeConfig


MAGIC = 0x424F574C
VERSION = 1
CONTROL_HEADER_STRUCT = struct.Struct("<IHHI")
UDP_FRAME_HEADER_STRUCT = struct.Struct("<IHHQHHHI")


class BowlingPacketType:
    HELLO = 1
    SESSION_CONFIG = 2
    LANE_CALIBRATION = 3
    FRAME_PACKET = 4
    SHOT_MARKER = 5
    TRACKER_STATUS = 6
    SHOT_RESULT = 7
    PING = 8
    PONG = 9
    ERROR = 10


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
    head_position: tuple[float, float, float]
    head_rotation: tuple[float, float, float, float]
    encoded_bytes: bytes


@dataclass
class PendingFrame:
    total_payload_length: int
    chunk_count: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


SHOT_MARKER_NAMES = {
    0: "session_started",
    1: "armed",
    2: "shot_started",
    3: "shot_ended",
    4: "tracker_reset",
}


def decode_jpeg(encoded_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(encoded_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("JPEG decode failed")
    return image


async def read_control_packet(reader: asyncio.StreamReader) -> Optional[tuple[int, bytes]]:
    try:
        header = await reader.readexactly(CONTROL_HEADER_STRUCT.size)
    except asyncio.IncompleteReadError:
        return None

    magic, version, packet_type, payload_length = CONTROL_HEADER_STRUCT.unpack(header)
    if magic != MAGIC:
        raise ValueError(f"invalid control packet magic 0x{magic:08X}")
    if version != VERSION:
        raise ValueError(f"unsupported control packet version {version}")

    payload = await reader.readexactly(payload_length) if payload_length > 0 else b""
    return packet_type, payload


async def write_control_packet(writer: asyncio.StreamWriter, packet_type: int, payload: bytes) -> None:
    payload = payload or b""
    writer.write(CONTROL_HEADER_STRUCT.pack(MAGIC, VERSION, packet_type, len(payload)))
    if payload:
        writer.write(payload)
    await writer.drain()


class DotNetBinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read_bytes(self, count: int) -> bytes:
        end = self.offset + count
        if end > len(self.data):
            raise ValueError("frame payload truncated")
        result = self.data[self.offset:end]
        self.offset = end
        return result

    def read_bool(self) -> bool:
        return struct.unpack("<?", self.read_bytes(1))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]

    def peek_int32(self) -> int:
        end = self.offset + 4
        if end > len(self.data):
            raise ValueError("frame payload truncated")
        return struct.unpack("<i", self.data[self.offset:end])[0]

    def read_int64(self) -> int:
        return struct.unpack("<q", self.read_bytes(8))[0]

    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint64(self) -> int:
        return struct.unpack("<Q", self.read_bytes(8))[0]

    def read_single(self) -> float:
        return struct.unpack("<f", self.read_bytes(4))[0]

    def read_7bit_encoded_int(self) -> int:
        value = 0
        shift = 0
        while True:
            byte = self.read_bytes(1)[0]
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return value
            shift += 7
            if shift >= 35:
                raise ValueError("invalid 7-bit encoded integer")

    def read_string(self) -> str:
        length = self.read_7bit_encoded_int()
        if length == 0:
            return ""
        return self.read_bytes(length).decode("utf-8")

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset


def decode_frame_packet(payload: bytes) -> FramePacket:
    reader = DotNetBinaryReader(payload)
    session_id = reader.read_string()
    shot_id = reader.read_string()
    frame_id = reader.read_uint64()
    timestamp_us = reader.read_int64()
    camera_position = (reader.read_single(), reader.read_single(), reader.read_single())
    camera_rotation = (reader.read_single(), reader.read_single(), reader.read_single(), reader.read_single())
    head_position = (0.0, 0.0, 0.0)
    head_rotation = (0.0, 0.0, 0.0, 1.0)

    encoded_length = reader.peek_int32()
    if encoded_length < 0 or encoded_length != reader.remaining - 4:
        head_position = (reader.read_single(), reader.read_single(), reader.read_single())
        head_rotation = (reader.read_single(), reader.read_single(), reader.read_single(), reader.read_single())
        encoded_length = reader.read_int32()

    encoded_bytes = reader.read_bytes(encoded_length)
    return FramePacket(
        session_id=session_id,
        shot_id=shot_id,
        frame_id=frame_id,
        timestamp_us=timestamp_us,
        camera_position=camera_position,
        camera_rotation=camera_rotation,
        head_position=head_position,
        head_rotation=head_rotation,
        encoded_bytes=encoded_bytes,
    )


class QuestUdpSession:
    def __init__(
        self,
        server: "QuestUdpServer",
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        self.server = server
        self.reader = reader
        self.writer = writer
        self.writer_lock = asyncio.Lock()
        self.analysis_mode = server.analysis_mode
        self.bridge = None if self.analysis_mode in {"diagnostic", "smoke"} else Sam2BowlingBridge(config=server.bridge_config)
        self.session_config: Optional[SessionConfig] = None
        self.lane_calibration: Optional[LaneCalibration] = None
        self.session_id = "pending-session"
        self.current_shot_id = "default-shot"
        self.received_frame_count = 0
        self.last_frame_size = (1280, 960)
        self.bridge_lock = asyncio.Lock()
        self.closed = False
        self.diagnostic_recorder: Optional[JpegShotRecorder] = None
        self.diagnostic_shot_dir: Optional[Path] = None
        self.smoke_recorder: Optional[JpegShotRecorder] = None
        self.smoke_shot_dir: Optional[Path] = None
        self.smoke_result_sent = False
        self.smoke_timeout_task: Optional[asyncio.Task] = None
        self.first_udp_frame_reported = False

    async def run(self) -> None:
        await self.send_tracker_status("control_connected", message="tcp control ready")
        try:
            while True:
                packet = await read_control_packet(self.reader)
                if packet is None:
                    break
                packet_type, payload = packet
                await self.handle_control_packet(packet_type, payload)
        finally:
            await self.close()

    async def handle_control_packet(self, packet_type: int, payload: bytes) -> None:
        if packet_type == BowlingPacketType.PING:
            await self.send_json(BowlingPacketType.PONG, {"kind": "pong", "timestamp_ms": int(time.time() * 1000)})
            return

        payload_text = payload.decode("utf-8") if payload else ""
        data = json.loads(payload_text) if payload_text else {}

        if packet_type == BowlingPacketType.HELLO:
            new_session_id = data.get("session_id", self.session_id)
            self.server.register_session_id(self, new_session_id)
            self.session_id = new_session_id
            print(f"[udp] hello session={self.session_id} device={data.get('device_name', 'unknown')}")
            await self.send_tracker_status("transport_ready", message="tcp+udp")
            return

        if packet_type == BowlingPacketType.SESSION_CONFIG:
            self.session_config = SessionConfig(
                session_id=data.get("session_id", self.session_id),
                camera_eye=int(data.get("camera_eye", 0)),
                width=int(data.get("width", self.last_frame_size[0])),
                height=int(data.get("height", self.last_frame_size[1])),
                fx=float(data.get("fx", 0.0)),
                fy=float(data.get("fy", 0.0)),
                cx=float(data.get("cx", 0.0)),
                cy=float(data.get("cy", 0.0)),
                sensor_width=int(data.get("sensor_width", 0)),
                sensor_height=int(data.get("sensor_height", 0)),
                lens_position=(
                    float(data.get("lens_position_x", 0.0)),
                    float(data.get("lens_position_y", 0.0)),
                    float(data.get("lens_position_z", 0.0)),
                ),
                lens_rotation=(
                    float(data.get("lens_rotation_x", 0.0)),
                    float(data.get("lens_rotation_y", 0.0)),
                    float(data.get("lens_rotation_z", 0.0)),
                    float(data.get("lens_rotation_w", 1.0)),
                ),
                target_send_fps=int(data.get("target_send_fps", 15)),
                transport=data.get("transport", "udp"),
                video_codec=data.get("video_codec", "jpeg"),
                target_bitrate_kbps=int(data.get("target_bitrate_kbps", 0)),
            )
            self.server.register_session_id(self, self.session_config.session_id)
            self.session_id = self.session_config.session_id
            self.last_frame_size = (self.session_config.width, self.session_config.height)
            print(
                f"[udp] session_config session={self.session_id} "
                f"size={self.session_config.width}x{self.session_config.height} "
                f"fps={self.session_config.target_send_fps}"
            )
            self.persist_active_shot_metadata()
            await self.send_tracker_status(
                "session_ready",
                width=self.session_config.width,
                height=self.session_config.height,
                target_send_fps=self.session_config.target_send_fps,
                transport=self.session_config.transport,
                video_codec=self.session_config.video_codec,
            )
            if self.analysis_mode == "smoke" and self.smoke_timeout_task is None:
                self.smoke_timeout_task = asyncio.create_task(self.run_smoke_timeout())
            return

        if packet_type == BowlingPacketType.LANE_CALIBRATION:
            self.lane_calibration = LaneCalibration(
                session_id=data.get("session_id", self.session_id),
                timestamp_ms=int(data.get("timestamp_ms", 0)),
                is_valid=bool(data.get("is_valid", False)),
                origin=(
                    float(data.get("origin_x", 0.0)),
                    float(data.get("origin_y", 0.0)),
                    float(data.get("origin_z", 0.0)),
                ),
                rotation=(
                    float(data.get("rotation_x", 0.0)),
                    float(data.get("rotation_y", 0.0)),
                    float(data.get("rotation_z", 0.0)),
                    float(data.get("rotation_w", 1.0)),
                ),
                lane_width_m=float(data.get("lane_width_m", 0.0)),
                lane_length_m=float(data.get("lane_length_m", 0.0)),
            )
            print(f"[udp] lane_calibration valid={self.lane_calibration.is_valid} session={self.session_id}")
            self.persist_active_shot_metadata()
            return

        if packet_type == BowlingPacketType.TRACKER_STATUS:
            self.persist_quest_tracker_status(data)
            stage = data.get("stage", "tracker_status")
            message = data.get("message", "")
            if stage in {"capture_perf", "capture_slow_frame", "frame_send_blocked", "frame_send_resumed"}:
                print(f"[quest-status] session={self.session_id} stage={stage} message={message}")
            return

        if packet_type == BowlingPacketType.SHOT_MARKER:
            await self.handle_shot_marker(data)
            return

        print(f"[udp] unhandled control packet type={packet_type}")

    async def handle_shot_marker(self, payload: dict) -> None:
        marker_type = int(payload.get("marker_type", -1))
        shot_id = payload.get("shot_id") or "default-shot"
        timestamp_ms = int(payload.get("timestamp_ms", 0))
        self.current_shot_id = shot_id

        print(f"[udp] shot marker type={marker_type} shot={shot_id} session={self.session_id}")

        if self.analysis_mode == "diagnostic":
            await self.handle_diagnostic_shot_marker(marker_type, shot_id, timestamp_ms)
            return

        if self.analysis_mode == "smoke":
            return

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
                shot_dir = self.bridge.active_shot_dir
                events = self.bridge.drain_status_events()
            self.persist_shot_metadata(shot_dir)
            self.append_shot_event(shot_dir, shot_id, marker_type, timestamp_ms)
            await self.send_events(events)
            return

        if marker_type == 3:
            async with self.bridge_lock:
                shot_dir = self.bridge.active_shot_dir
                task = await self.bridge.end_shot_and_launch()
                events = self.bridge.drain_status_events()
            self.append_shot_event(shot_dir, shot_id, marker_type, timestamp_ms)
            await self.send_events(events)
            if task is not None:
                result = await task
                result.setdefault("kind", "shot_result")
                result.setdefault("timestamp_ms", timestamp_ms)
                await self.send_json(BowlingPacketType.SHOT_RESULT, result)
            return

        if marker_type == 4:
            async with self.bridge_lock:
                shot_dir = self.bridge.active_shot_dir
                self.bridge.finish_active_recorder()
            self.append_shot_event(shot_dir, shot_id, marker_type, timestamp_ms)
            await self.send_tracker_status("tracker_reset", shot_id=shot_id)

    async def handle_frame(
        self,
        frame_packet: FramePacket,
        addr: tuple[str, int],
        chunk_count: int,
        total_payload_length: int,
    ) -> None:
        self.current_shot_id = frame_packet.shot_id or self.current_shot_id
        self.received_frame_count += 1

        if not self.first_udp_frame_reported:
            self.first_udp_frame_reported = True
            await self.send_tracker_status(
                "udp_frame_received",
                shot_id=self.current_shot_id,
                message=(
                    f"frame {frame_packet.frame_id} | jpg {len(frame_packet.encoded_bytes)} | "
                    f"{chunk_count} chunks | payload {total_payload_length} | {addr[0]}:{addr[1]}"
                ),
            )
        elif self.received_frame_count % 30 == 0:
            await self.send_tracker_status(
                "remote_frames",
                shot_id=self.current_shot_id,
                message=f"{self.received_frame_count} | frame {frame_packet.frame_id} | jpg {len(frame_packet.encoded_bytes)}",
            )

        if self.analysis_mode == "diagnostic":
            if self.diagnostic_recorder is not None:
                local_frame_idx = self.diagnostic_recorder.write_frame(frame_packet)
                if local_frame_idx == 0 or (local_frame_idx + 1) % 15 == 0:
                    await self.send_tracker_status(
                        "diagnostic_frames_recorded",
                        shot_id=self.current_shot_id,
                        message=str(local_frame_idx + 1),
                    )
            return

        if self.analysis_mode == "smoke":
            await self.handle_smoke_frame(frame_packet)
            return

        async with self.bridge_lock:
            self.bridge.buffer_frame(frame_packet)
            if self.bridge.active_recorder is not None:
                self.bridge.add_frame(frame_packet, decode_frame=lambda fp: decode_jpeg(fp.encoded_bytes))
                events = self.bridge.drain_status_events()
            else:
                events = []

        if events:
            await self.send_events(events)

    async def handle_diagnostic_shot_marker(self, marker_type: int, shot_id: str, timestamp_ms: int) -> None:
        if marker_type == 2:
            self.start_diagnostic_shot(shot_id)
            await self.send_tracker_status("diagnostic_recording", shot_id=shot_id, message="recording raw UDP JPEG frames")
            return

        if marker_type == 3:
            result = self.finish_diagnostic_shot(shot_id)
            result.setdefault("timestamp_ms", timestamp_ms)
            await self.send_json(BowlingPacketType.SHOT_RESULT, result)
            return

        if marker_type == 4:
            self.finish_diagnostic_shot(shot_id)
            await self.send_tracker_status("tracker_reset", shot_id=shot_id)

    def start_diagnostic_shot(self, shot_id: str) -> None:
        self.finish_diagnostic_shot(shot_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_dir = self.server.bridge_config.runs_root / f"{self.session_id}_{shot_id}_{timestamp}"
        raw_dir = shot_dir / "raw"
        fps = float(max(self.session_config.target_send_fps if self.session_config else 15, 1))
        self.diagnostic_recorder = JpegShotRecorder(raw_dir, fps=fps, frame_size=self.last_frame_size)
        self.diagnostic_shot_dir = shot_dir
        self.persist_shot_metadata(shot_dir)

    def finish_diagnostic_shot(self, shot_id: str) -> dict:
        recorder = self.diagnostic_recorder
        shot_dir = self.diagnostic_shot_dir
        self.diagnostic_recorder = None
        self.diagnostic_shot_dir = None

        if recorder is None or shot_dir is None:
            return {
                "kind": "shot_result",
                "success": False,
                "session_id": self.session_id,
                "shot_id": shot_id,
                "failure_reason": "diagnostic_not_recording",
                "tracked_frames": 0,
                "first_frame": -1,
                "last_frame": -1,
                "path_samples": [],
            }

        recorder.close()
        analysis_dir = shot_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "kind": "shot_result",
            "success": recorder.frame_count > 0,
            "session_id": self.session_id,
            "shot_id": shot_id,
            "failure_reason": "" if recorder.frame_count > 0 else "no_udp_frames_received",
            "raw_frames_dir": str(recorder.frames_dir),
            "analysis_dir": str(analysis_dir),
            "tracked_frames": recorder.frame_count,
            "first_frame": 0 if recorder.frame_count > 0 else -1,
            "last_frame": recorder.frame_count - 1 if recorder.frame_count > 0 else -1,
            "path_samples": [],
        }
        (shot_dir / "diagnostic_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (shot_dir / "shot_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    async def handle_smoke_frame(self, frame_packet: FramePacket) -> None:
        if self.smoke_result_sent:
            return

        if self.smoke_timeout_task is None:
            self.smoke_timeout_task = asyncio.create_task(self.run_smoke_timeout())

        if self.smoke_recorder is None:
            self.start_smoke_capture()
            await self.send_tracker_status(
                "smoke_recording",
                shot_id=self.current_shot_id,
                message=f"recording first {self.server.smoke_target_frames} UDP frames",
            )

        local_frame_idx = self.smoke_recorder.write_frame(frame_packet)
        if local_frame_idx == 0 or (local_frame_idx + 1) % 15 == 0:
            await self.send_tracker_status("smoke_frames_recorded", shot_id=self.current_shot_id, message=str(local_frame_idx + 1))

        if self.smoke_recorder.frame_count >= self.server.smoke_target_frames and not self.smoke_result_sent:
            self.smoke_result_sent = True
            result = self.finish_smoke_capture()
            await self.send_tracker_status("smoke_complete", shot_id=self.current_shot_id, message=str(result.get("tracked_frames", 0)))
            await self.send_json(BowlingPacketType.SHOT_RESULT, result)

    def start_smoke_capture(self) -> None:
        if self.smoke_recorder is not None:
            return

        self.current_shot_id = "smoke-test"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_dir = self.server.bridge_config.runs_root / f"{self.session_id}_smoke_{timestamp}"
        raw_dir = shot_dir / "raw"
        fps = float(max(self.session_config.target_send_fps if self.session_config else 15, 1))
        self.smoke_recorder = JpegShotRecorder(raw_dir, fps=fps, frame_size=self.last_frame_size)
        self.smoke_shot_dir = shot_dir
        self.persist_shot_metadata(shot_dir)

    def finish_smoke_capture(self) -> dict:
        recorder = self.smoke_recorder
        shot_dir = self.smoke_shot_dir
        self.smoke_recorder = None
        self.smoke_shot_dir = None

        if recorder is None or shot_dir is None:
            return {
                "kind": "shot_result",
                "success": False,
                "session_id": self.session_id,
                "shot_id": "smoke-test",
                "failure_reason": "smoke_not_recording",
                "tracked_frames": 0,
                "first_frame": -1,
                "last_frame": -1,
                "path_samples": [],
            }

        recorder.close()
        analysis_dir = shot_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "kind": "shot_result",
            "success": recorder.frame_count > 0,
            "session_id": self.session_id,
            "shot_id": "smoke-test",
            "failure_reason": "" if recorder.frame_count > 0 else "no_udp_frames_received",
            "raw_frames_dir": str(recorder.frames_dir),
            "analysis_dir": str(analysis_dir),
            "tracked_frames": recorder.frame_count,
            "first_frame": 0 if recorder.frame_count > 0 else -1,
            "last_frame": recorder.frame_count - 1 if recorder.frame_count > 0 else -1,
            "path_samples": [],
        }
        (shot_dir / "smoke_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (shot_dir / "shot_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    async def run_smoke_timeout(self) -> None:
        try:
            await asyncio.sleep(self.server.smoke_timeout_seconds)
            if self.closed or self.analysis_mode != "smoke" or self.smoke_result_sent:
                return

            if self.smoke_recorder is None:
                self.start_smoke_capture()

            self.smoke_result_sent = True
            await self.send_tracker_status(
                "smoke_timeout",
                shot_id=self.current_shot_id,
                message=f"{self.server.smoke_timeout_seconds:0.0f}s | frames {self.received_frame_count}",
            )
            await self.send_json(BowlingPacketType.SHOT_RESULT, self.finish_smoke_capture())
        except asyncio.CancelledError:
            raise

    async def send_events(self, events: list[dict]) -> None:
        for event in events:
            await self.send_json(BowlingPacketType.TRACKER_STATUS, event)

    async def send_tracker_status(self, stage: str, shot_id: Optional[str] = None, message: Optional[str] = None, **extra) -> None:
        payload = {"kind": "tracker_status", "stage": stage, "session_id": self.session_id, "shot_id": shot_id or self.current_shot_id}
        if message is not None:
            payload["message"] = message
        payload.update(extra)
        await self.send_json(BowlingPacketType.TRACKER_STATUS, payload)

    async def send_json(self, packet_type: int, payload: dict) -> None:
        if self.writer.is_closing():
            return
        async with self.writer_lock:
            await write_control_packet(writer=self.writer, packet_type=packet_type, payload=json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def get_active_shot_dir(self) -> Optional[Path]:
        if self.bridge is not None and self.bridge.active_shot_dir is not None:
            return self.bridge.active_shot_dir
        if self.diagnostic_shot_dir is not None:
            return self.diagnostic_shot_dir
        if self.smoke_shot_dir is not None:
            return self.smoke_shot_dir
        return None

    def persist_active_shot_metadata(self) -> None:
        self.persist_shot_metadata(self.get_active_shot_dir())

    def persist_shot_metadata(self, shot_dir: Optional[Path]) -> None:
        if shot_dir is None:
            return

        shot_dir.mkdir(parents=True, exist_ok=True)
        peername = self.writer.get_extra_info("peername")
        capture_context = {
            "session_id": self.session_id,
            "shot_id": self.current_shot_id,
            "analysis_mode": self.analysis_mode,
            "control_peer": list(peername) if isinstance(peername, tuple) else peername,
            "last_frame_width": self.last_frame_size[0],
            "last_frame_height": self.last_frame_size[1],
            "received_frame_count": self.received_frame_count,
            "saved_at_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        }
        (shot_dir / "capture_context.json").write_text(json.dumps(capture_context, indent=2), encoding="utf-8")

        if self.session_config is not None:
            (shot_dir / "session_config.json").write_text(json.dumps(asdict(self.session_config), indent=2), encoding="utf-8")

        if self.lane_calibration is not None:
            (shot_dir / "lane_calibration.json").write_text(json.dumps(asdict(self.lane_calibration), indent=2), encoding="utf-8")

    def append_shot_event(self, shot_dir: Optional[Path], shot_id: str, marker_type: int, timestamp_ms: int) -> None:
        if shot_dir is None:
            return

        self.persist_shot_metadata(shot_dir)
        event = {
            "shot_id": shot_id,
            "marker_type": marker_type,
            "marker_name": SHOT_MARKER_NAMES.get(marker_type, f"unknown_{marker_type}"),
            "quest_timestamp_ms": timestamp_ms,
            "server_received_utc": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        }
        with (shot_dir / "shot_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def persist_quest_tracker_status(self, payload: dict) -> None:
        shot_dir = self.get_active_shot_dir()
        if shot_dir is None:
            return

        self.persist_shot_metadata(shot_dir)
        record = dict(payload)
        record["server_received_utc"] = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        with (shot_dir / "quest_tracker_status.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    async def close(self) -> None:
        if self.closed:
            return

        self.closed = True
        self.server.unregister_session(self)

        if self.bridge is not None:
            async with self.bridge_lock:
                self.bridge.finish_active_recorder()
        elif self.diagnostic_recorder is not None:
            self.diagnostic_recorder.close()
            self.diagnostic_recorder = None
            self.diagnostic_shot_dir = None
        elif self.smoke_recorder is not None:
            self.smoke_recorder.close()
            self.smoke_recorder = None
            self.smoke_shot_dir = None

        if self.smoke_timeout_task is not None:
            self.smoke_timeout_task.cancel()
            try:
                await self.smoke_timeout_task
            except asyncio.CancelledError:
                pass
            self.smoke_timeout_task = None

        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass


class QuestUdpServer:
    def __init__(self, analysis_mode: str, smoke_target_frames: int, smoke_timeout_seconds: float):
        bridge_analysis_mode = "diagnostic" if analysis_mode == "smoke" else analysis_mode
        self.analysis_mode = analysis_mode
        self.bridge_config = Sam2BridgeConfig(analysis_mode=bridge_analysis_mode)
        self.smoke_target_frames = int(max(1, smoke_target_frames))
        self.smoke_timeout_seconds = float(max(1.0, smoke_timeout_seconds))
        self.sessions: set[QuestUdpSession] = set()
        self.sessions_by_id: dict[str, QuestUdpSession] = {}
        self.pending_frames: dict[tuple[tuple[str, int], int], PendingFrame] = {}
        self.first_udp_datagram_seen = False

    async def broadcast_tracker_status(self, stage: str, message: str) -> None:
        if not self.sessions:
            return

        await asyncio.gather(
            *(session.send_tracker_status(stage, message=message) for session in list(self.sessions)),
            return_exceptions=True,
        )

    async def handle_control_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = QuestUdpSession(server=self, reader=reader, writer=writer)
        self.sessions.add(session)
        await session.run()

    def register_session_id(self, session: QuestUdpSession, session_id: str) -> None:
        for existing_id, existing_session in list(self.sessions_by_id.items()):
            if existing_session is session and existing_id != session_id:
                del self.sessions_by_id[existing_id]
        self.sessions_by_id[session_id] = session

    def unregister_session(self, session: QuestUdpSession) -> None:
        self.sessions.discard(session)
        for existing_id, existing_session in list(self.sessions_by_id.items()):
            if existing_session is session:
                del self.sessions_by_id[existing_id]

    async def handle_udp_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        now = time.monotonic()
        for key, pending in list(self.pending_frames.items()):
            if now - pending.created_at > 5.0:
                del self.pending_frames[key]

        if len(data) < UDP_FRAME_HEADER_STRUCT.size:
            return

        magic, version, packet_type, frame_id, chunk_index, chunk_count, payload_length, total_payload_length = UDP_FRAME_HEADER_STRUCT.unpack(
            data[: UDP_FRAME_HEADER_STRUCT.size]
        )
        if magic != MAGIC or version != VERSION or packet_type != BowlingPacketType.FRAME_PACKET:
            return

        if not self.first_udp_datagram_seen:
            self.first_udp_datagram_seen = True
            message = f"{addr[0]}:{addr[1]} | frame {frame_id} | chunks {chunk_count} | total {total_payload_length}"
            print(f"[udp] first datagram {message}")
            await self.broadcast_tracker_status("udp_datagram_seen", message)

        chunk = data[UDP_FRAME_HEADER_STRUCT.size : UDP_FRAME_HEADER_STRUCT.size + payload_length]
        if len(chunk) != payload_length or chunk_index >= chunk_count:
            print(
                f"[udp] invalid datagram addr={addr[0]}:{addr[1]} frame={frame_id} "
                f"chunk={chunk_index}/{chunk_count} payload_length={payload_length} actual={len(chunk)}"
            )
            await self.broadcast_tracker_status(
                "udp_datagram_invalid",
                f"{addr[0]}:{addr[1]} | frame {frame_id} | chunk {chunk_index}/{chunk_count}",
            )
            return

        key = (addr, frame_id)
        pending = self.pending_frames.get(key)
        if pending is None:
            pending = PendingFrame(total_payload_length=total_payload_length, chunk_count=chunk_count, created_at=now)
            self.pending_frames[key] = pending

        pending.chunks[chunk_index] = chunk
        if len(pending.chunks) != pending.chunk_count:
            return

        payload = b"".join(pending.chunks[index] for index in range(pending.chunk_count))
        del self.pending_frames[key]
        if len(payload) != pending.total_payload_length:
            print(
                f"[udp] payload length mismatch addr={addr[0]}:{addr[1]} frame={frame_id} "
                f"expected={pending.total_payload_length} actual={len(payload)}"
            )
            await self.broadcast_tracker_status(
                "udp_payload_mismatch",
                f"{addr[0]}:{addr[1]} | frame {frame_id} | expected {pending.total_payload_length} got {len(payload)}",
            )
            return

        try:
            frame_packet = decode_frame_packet(payload)
        except Exception as exc:
            print(f"[udp] decode failed addr={addr[0]}:{addr[1]} frame={frame_id}: {exc}")
            await self.broadcast_tracker_status(
                "udp_frame_decode_failed",
                f"{addr[0]}:{addr[1]} | frame {frame_id} | {type(exc).__name__}: {exc}",
            )
            return

        session = self.sessions_by_id.get(frame_packet.session_id)
        if session is None:
            print(f"[udp] dropping frame for unknown session={frame_packet.session_id}")
            await self.broadcast_tracker_status(
                "udp_unknown_session_frame",
                f"{frame_packet.session_id} | frame {frame_packet.frame_id} | from {addr[0]}:{addr[1]}",
            )
            return

        await session.handle_frame(
            frame_packet,
            addr=addr,
            chunk_count=chunk_count,
            total_payload_length=total_payload_length,
        )

    async def close(self) -> None:
        sessions = list(self.sessions)
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)


class QuestUdpDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: QuestUdpServer):
        self.server = server

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self.server.handle_udp_datagram(data, addr))


async def run_server(args) -> None:
    server = QuestUdpServer(
        analysis_mode=args.analysis_mode,
        smoke_target_frames=args.smoke_target_frames,
        smoke_timeout_seconds=args.smoke_timeout_seconds,
    )
    loop = asyncio.get_running_loop()
    udp_transport, _ = await loop.create_datagram_endpoint(
        lambda: QuestUdpDatagramProtocol(server),
        local_addr=(args.host, args.port),
    )
    tcp_server = await asyncio.start_server(server.handle_control_connection, host=args.host, port=args.port)

    print(f"[udp] listening on tcp+udp {args.host}:{args.port} analysis_mode={args.analysis_mode}")
    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        udp_transport.close()
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Quest bowling UDP receiver")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5799)
    parser.add_argument("--analysis-mode", choices=("live", "synthetic", "diagnostic", "smoke"), default="live")
    parser.add_argument("--persist-jpeg-quality", type=int, default=90)
    parser.add_argument("--smoke-target-frames", type=int, default=90)
    parser.add_argument("--smoke-timeout-seconds", type=float, default=8.0)
    args = parser.parse_args()

    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
