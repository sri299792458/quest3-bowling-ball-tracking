import argparse
import asyncio
import json
import struct
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import cv2
import numpy as np

try:
    from .sam2_bowling_bridge import Sam2BowlingBridge, Sam2BridgeConfig
except ImportError:
    from sam2_bowling_bridge import Sam2BowlingBridge, Sam2BridgeConfig


MAGIC = 0x424F574C
VERSION = 1


class PacketType:
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
    codec: int
    quality: int


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


@dataclass
class SessionState:
    writer: asyncio.StreamWriter
    session_config: Optional[SessionConfig] = None
    lane_calibration: Optional[LaneCalibration] = None
    received_frame_count: int = 0


@dataclass
class ShotMarker:
    session_id: str
    shot_id: str
    marker_type: int
    timestamp_ms: int


class PayloadReader:
    def __init__(self, data: bytes):
        self._stream = BytesIO(data)

    def read_bool(self) -> bool:
        return struct.unpack("<?", self._stream.read(1))[0]

    def read_u16(self) -> int:
        return struct.unpack("<H", self._stream.read(2))[0]

    def read_i32(self) -> int:
        return struct.unpack("<i", self._stream.read(4))[0]

    def read_u64(self) -> int:
        return struct.unpack("<Q", self._stream.read(8))[0]

    def read_i64(self) -> int:
        return struct.unpack("<q", self._stream.read(8))[0]

    def read_f32(self) -> float:
        return struct.unpack("<f", self._stream.read(4))[0]

    def read_string(self) -> str:
        length = self._read_7bit_int()
        return self._stream.read(length).decode("utf-8")

    def read_bytes(self, count: int) -> bytes:
        return self._stream.read(count)

    def _read_7bit_int(self) -> int:
        result = 0
        shift = 0
        while True:
            raw = self._stream.read(1)
            if not raw:
                raise EOFError("Unexpected end of payload while reading 7-bit int")
            byte = raw[0]
            result |= (byte & 0x7F) << shift
            if byte & 0x80 == 0:
                return result
            shift += 7


async def write_text_packet(writer: asyncio.StreamWriter, packet_type: int, payload_obj: dict):
    payload = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    header = struct.pack("<IHHI", MAGIC, VERSION, packet_type, len(payload))
    writer.write(header)
    writer.write(payload)
    await writer.drain()


def parse_session_config(payload: bytes) -> SessionConfig:
    reader = PayloadReader(payload)
    return SessionConfig(
        session_id=reader.read_string(),
        camera_eye=reader.read_i32(),
        width=reader.read_i32(),
        height=reader.read_i32(),
        fx=reader.read_f32(),
        fy=reader.read_f32(),
        cx=reader.read_f32(),
        cy=reader.read_f32(),
        sensor_width=reader.read_i32(),
        sensor_height=reader.read_i32(),
        lens_position=(reader.read_f32(), reader.read_f32(), reader.read_f32()),
        lens_rotation=(reader.read_f32(), reader.read_f32(), reader.read_f32(), reader.read_f32()),
        target_send_fps=reader.read_i32(),
        codec=reader.read_u16(),
        quality=reader.read_i32(),
    )


def parse_lane_calibration(payload: bytes) -> LaneCalibration:
    reader = PayloadReader(payload)
    return LaneCalibration(
        session_id=reader.read_string(),
        timestamp_ms=reader.read_i64(),
        is_valid=reader.read_bool(),
        origin=(reader.read_f32(), reader.read_f32(), reader.read_f32()),
        rotation=(reader.read_f32(), reader.read_f32(), reader.read_f32(), reader.read_f32()),
        lane_width_m=reader.read_f32(),
        lane_length_m=reader.read_f32(),
    )


def parse_frame_packet(payload: bytes) -> FramePacket:
    reader = PayloadReader(payload)
    session_id = reader.read_string()
    shot_id = reader.read_string()
    frame_id = reader.read_u64()
    timestamp_us = reader.read_i64()
    camera_position = (reader.read_f32(), reader.read_f32(), reader.read_f32())
    camera_rotation = (reader.read_f32(), reader.read_f32(), reader.read_f32(), reader.read_f32())
    encoded_length = reader.read_i32()
    encoded_bytes = reader.read_bytes(encoded_length)
    return FramePacket(session_id, shot_id, frame_id, timestamp_us, camera_position, camera_rotation, encoded_bytes)


def parse_shot_marker(payload: bytes) -> ShotMarker:
    reader = PayloadReader(payload)
    return ShotMarker(
        session_id=reader.read_string(),
        shot_id=reader.read_string(),
        marker_type=reader.read_u16(),
        timestamp_ms=reader.read_i64(),
    )


def decode_jpeg(encoded_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(encoded_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("JPEG decode failed")
    return image


async def read_packet(reader: asyncio.StreamReader):
    header = await reader.readexactly(12)
    magic, version, packet_type, payload_length = struct.unpack("<IHHI", header)
    if magic != MAGIC:
        raise ValueError(f"Invalid packet magic: 0x{magic:08X}")
    if version != VERSION:
        raise ValueError(f"Unsupported version: {version}")
    payload = await reader.readexactly(payload_length) if payload_length else b""
    return packet_type, payload


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bridge_config: Sam2BridgeConfig):
    peer = writer.get_extra_info("peername")
    print(f"[server] connection from {peer}")
    session = SessionState(writer=writer)
    bridge = Sam2BowlingBridge(config=bridge_config)

    try:
        while True:
            packet_type, payload = await read_packet(reader)
            if packet_type == PacketType.HELLO:
                continue
            if packet_type == PacketType.SESSION_CONFIG:
                session.session_config = parse_session_config(payload)
                await write_text_packet(writer, PacketType.TRACKER_STATUS, {"kind": "tracker_status", "stage": "session_ready", "session_id": session.session_config.session_id, "width": session.session_config.width, "height": session.session_config.height, "target_send_fps": session.session_config.target_send_fps})
            elif packet_type == PacketType.LANE_CALIBRATION:
                session.lane_calibration = parse_lane_calibration(payload)
            elif packet_type == PacketType.FRAME_PACKET:
                frame = parse_frame_packet(payload)
                session.received_frame_count += 1
                bridge.buffer_frame(frame)
                if bridge.active_recorder is not None:
                    bridge.add_frame(frame, decode_frame=lambda fp: decode_jpeg(fp.encoded_bytes))
                    for event in bridge.drain_status_events():
                        await write_text_packet(writer, PacketType.TRACKER_STATUS, event)
            elif packet_type == PacketType.SHOT_MARKER:
                marker = parse_shot_marker(payload)
                if marker.marker_type == 2:
                    if not session.session_config:
                        await write_text_packet(writer, PacketType.ERROR, {"kind": "error", "message": "shot_started received before session config"})
                        continue
                    bridge.start_shot(marker.session_id, marker.shot_id, float(max(session.session_config.target_send_fps, 1)), (session.session_config.width, session.session_config.height), decode_frame=lambda fp: decode_jpeg(fp.encoded_bytes))
                    for event in bridge.drain_status_events():
                        await write_text_packet(writer, PacketType.TRACKER_STATUS, event)
                elif marker.marker_type == 3:
                    task = await bridge.end_shot_and_launch()
                    for event in bridge.drain_status_events():
                        await write_text_packet(writer, PacketType.TRACKER_STATUS, event)
                    if task is not None:
                        await write_text_packet(writer, PacketType.SHOT_RESULT, await task)
                elif marker.marker_type == 4:
                    bridge.finish_active_recorder()
                    await write_text_packet(writer, PacketType.TRACKER_STATUS, {"kind": "tracker_status", "stage": "tracker_reset", "shot_id": marker.shot_id})
            elif packet_type == PacketType.PING:
                await write_text_packet(writer, PacketType.PONG, {"kind": "pong"})
    except asyncio.IncompleteReadError:
        pass
    finally:
        bridge.finish_active_recorder()
        writer.close()
        await writer.wait_closed()


async def main():
    parser = argparse.ArgumentParser(description="Quest bowling TCP receiver")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5799)
    parser.add_argument("--analysis-mode", choices=("live", "synthetic"), default="live")
    args = parser.parse_args()

    bridge_config = Sam2BridgeConfig(analysis_mode=args.analysis_mode)
    server = await asyncio.start_server(lambda reader, writer: handle_client(reader, writer, bridge_config), args.host, args.port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
