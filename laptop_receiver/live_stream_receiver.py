from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import struct
from typing import Any


DEFAULT_MEDIA_HOST = "0.0.0.0"
DEFAULT_MEDIA_PORT = 8766
DEFAULT_METADATA_HOST = "0.0.0.0"
DEFAULT_METADATA_PORT = 8767
DEFAULT_HEALTH_HOST = "0.0.0.0"
DEFAULT_HEALTH_PORT = 8768
DEFAULT_INCOMING_ROOT = Path(r"C:\Users\student\QuestBowlingStandalone\data\incoming_live_streams")

PACKET_MAGIC = b"QBLS"
PACKET_VERSION = 1
PACKET_HEADER_STRUCT = struct.Struct("<4sBBI")
SAMPLE_HEADER_STRUCT = struct.Struct("<QII")

PACKET_TYPE_SESSION_START = 1
PACKET_TYPE_SAMPLE = 2
PACKET_TYPE_SESSION_END = 3
PACKET_TYPE_CODEC_CONFIG = 4

SAMPLE_FLAG_KEYFRAME = 1 << 0


def _json_dumps_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def _sanitize_file_part(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "unknown"
    invalid = set('<>:"/\\|?*')
    return "".join("_" if ch in invalid else ch for ch in text)


@dataclass
class LiveStreamSession:
    session_id: str
    shot_id: str
    root_dir: Path
    media_stream_path: Path
    media_samples_path: Path
    metadata_stream_path: Path
    codec_config_path: Path
    session_start_path: Path
    session_end_path: Path
    stream_receipt_path: Path
    media_file: Any = None
    media_samples_file: Any = None
    metadata_stream_file: Any = None
    session_started_payload: dict[str, Any] | None = None
    session_ended_payload: dict[str, Any] | None = None
    sample_count: int = 0
    keyframe_count: int = 0
    metadata_message_count: int = 0
    first_pts_us: int | None = None
    last_pts_us: int | None = None
    codec_config_seen: bool = False
    codec_config_bytes: int = 0

    def open(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.media_file = self.media_stream_path.open("wb")
        self.media_samples_file = self.media_samples_path.open("w", encoding="utf-8", newline="\n")
        self.metadata_stream_file = self.metadata_stream_path.open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        for handle_name in ("media_file", "media_samples_file", "metadata_stream_file"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)

    def persist_receipt(self) -> None:
        payload = {
            "kind": "live_stream_receipt",
            "session_id": self.session_id,
            "shot_id": self.shot_id,
            "root_dir": str(self.root_dir),
            "sample_count": self.sample_count,
            "keyframe_count": self.keyframe_count,
            "metadata_message_count": self.metadata_message_count,
            "first_pts_us": self.first_pts_us,
            "last_pts_us": self.last_pts_us,
            "session_start_seen": self.session_started_payload is not None,
            "session_end_seen": self.session_ended_payload is not None,
            "codec_config_seen": self.codec_config_seen,
            "codec_config_bytes": self.codec_config_bytes,
        }
        self.stream_receipt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_session_start(self, payload: dict[str, Any]) -> None:
        self.session_started_payload = payload
        self.session_start_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.persist_receipt()

    def write_session_end(self, payload: dict[str, Any]) -> None:
        self.session_ended_payload = payload
        self.session_end_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.persist_receipt()

    def append_sample(self, pts_us: int, flags: int, encoded_bytes: bytes) -> None:
        if self.media_file is None or self.media_samples_file is None:
            raise RuntimeError("Live stream session files are not open.")

        self.media_file.write(encoded_bytes)
        self.media_file.flush()

        is_keyframe = (flags & SAMPLE_FLAG_KEYFRAME) != 0
        self.media_samples_file.write(
            json.dumps(
                {
                    "pts_us": int(pts_us),
                    "flags": int(flags),
                    "is_keyframe": bool(is_keyframe),
                    "byte_count": int(len(encoded_bytes)),
                }
            )
            + "\n"
        )
        self.media_samples_file.flush()

        self.sample_count += 1
        if is_keyframe:
            self.keyframe_count += 1
        if self.first_pts_us is None:
            self.first_pts_us = int(pts_us)
        self.last_pts_us = int(pts_us)
        self.persist_receipt()

    def write_codec_config(self, codec_config_bytes: bytes) -> None:
        if self.media_file is None:
            raise RuntimeError("Live stream session files are not open.")

        self.media_file.write(codec_config_bytes)
        self.media_file.flush()
        self.codec_config_path.write_bytes(codec_config_bytes)
        self.codec_config_seen = True
        self.codec_config_bytes = int(len(codec_config_bytes))
        self.persist_receipt()

    def append_metadata_message(self, payload: dict[str, Any]) -> None:
        if self.metadata_stream_file is None:
            raise RuntimeError("Metadata stream file is not open.")

        self.metadata_stream_file.write(json.dumps(payload) + "\n")
        self.metadata_stream_file.flush()
        self.metadata_message_count += 1
        self.persist_receipt()


@dataclass
class LiveStreamRegistry:
    incoming_root: Path
    sessions: dict[tuple[str, str], LiveStreamSession] = field(default_factory=dict)

    def get_or_create(self, session_id: str, shot_id: str) -> LiveStreamSession:
        key = (session_id, shot_id)
        existing = self.sessions.get(key)
        if existing is not None:
            return existing

        root_dir = self.incoming_root / f"live_{_sanitize_file_part(session_id)}_{_sanitize_file_part(shot_id)}"
        session = LiveStreamSession(
            session_id=session_id,
            shot_id=shot_id,
            root_dir=root_dir,
            media_stream_path=root_dir / "stream.h264",
            media_samples_path=root_dir / "media_samples.jsonl",
            metadata_stream_path=root_dir / "metadata_stream.jsonl",
            codec_config_path=root_dir / "codec_config.h264",
            session_start_path=root_dir / "session_start.json",
            session_end_path=root_dir / "session_end.json",
            stream_receipt_path=root_dir / "stream_receipt.json",
        )
        session.open()
        session.persist_receipt()
        self.sessions[key] = session
        return session

    def close_all(self) -> None:
        for session in self.sessions.values():
            session.persist_receipt()
            session.close()


async def _read_exact(reader: asyncio.StreamReader, size: int) -> bytes:
    data = await reader.readexactly(size)
    if len(data) != size:
        raise asyncio.IncompleteReadError(data, size)
    return data


async def _handle_media_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    registry: LiveStreamRegistry,
) -> None:
    peer = writer.get_extra_info("peername")
    active_session: LiveStreamSession | None = None
    try:
        while True:
            header = await _read_exact(reader, PACKET_HEADER_STRUCT.size)
            magic, version, packet_type, payload_length = PACKET_HEADER_STRUCT.unpack(header)
            if magic != PACKET_MAGIC:
                raise RuntimeError(f"Invalid packet magic from {peer}: {magic!r}")
            if version != PACKET_VERSION:
                raise RuntimeError(f"Unsupported packet version from {peer}: {version}")
            payload = await _read_exact(reader, int(payload_length))

            if packet_type == PACKET_TYPE_SESSION_START:
                session_payload = json.loads(payload.decode("utf-8"))
                session_id = str(session_payload["session_id"])
                shot_id = str(session_payload["shot_id"])
                active_session = registry.get_or_create(session_id, shot_id)
                active_session.write_session_start(session_payload)
                continue

            if packet_type == PACKET_TYPE_SAMPLE:
                if active_session is None:
                    raise RuntimeError("Received media sample before session_start packet.")
                if len(payload) < SAMPLE_HEADER_STRUCT.size:
                    raise RuntimeError("Sample packet too short.")
                pts_us, flags, sample_size = SAMPLE_HEADER_STRUCT.unpack(payload[: SAMPLE_HEADER_STRUCT.size])
                encoded_bytes = payload[SAMPLE_HEADER_STRUCT.size :]
                if len(encoded_bytes) != sample_size:
                    raise RuntimeError(
                        f"Sample length mismatch. Declared {sample_size}, got {len(encoded_bytes)}."
                    )
                active_session.append_sample(int(pts_us), int(flags), encoded_bytes)
                continue

            if packet_type == PACKET_TYPE_CODEC_CONFIG:
                if active_session is None:
                    raise RuntimeError("Received codec_config before session_start.")
                active_session.write_codec_config(payload)
                continue

            if packet_type == PACKET_TYPE_SESSION_END:
                if active_session is None:
                    raise RuntimeError("Received session_end before session_start.")
                session_end_payload = json.loads(payload.decode("utf-8"))
                active_session.write_session_end(session_end_payload)
                continue

            raise RuntimeError(f"Unknown media packet type: {packet_type}")
    except asyncio.IncompleteReadError:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def _handle_metadata_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    registry: LiveStreamRegistry,
) -> None:
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            stripped = line.decode("utf-8").strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            session_id = str(payload["session_id"])
            shot_id = str(payload["shot_id"])
            session = registry.get_or_create(session_id, shot_id)
            session.append_metadata_message(payload)
    finally:
        writer.close()
        await writer.wait_closed()


async def _handle_health_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        await reader.read(1024)
        body = _json_dumps_bytes({"ok": True, "status": "healthy"})
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("utf-8")
            + b"Connection: close\r\n\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone live H.264 Quest-to-laptop receiver.")
    parser.add_argument("--incoming-root", type=Path, default=DEFAULT_INCOMING_ROOT)
    parser.add_argument("--media-host", default=DEFAULT_MEDIA_HOST)
    parser.add_argument("--media-port", type=int, default=DEFAULT_MEDIA_PORT)
    parser.add_argument("--metadata-host", default=DEFAULT_METADATA_HOST)
    parser.add_argument("--metadata-port", type=int, default=DEFAULT_METADATA_PORT)
    parser.add_argument("--health-host", default=DEFAULT_HEALTH_HOST)
    parser.add_argument("--health-port", type=int, default=DEFAULT_HEALTH_PORT)
    return parser


async def _run_servers(args: argparse.Namespace) -> None:
    incoming_root = args.incoming_root.expanduser().resolve()
    incoming_root.mkdir(parents=True, exist_ok=True)
    registry = LiveStreamRegistry(incoming_root=incoming_root)

    media_server = await asyncio.start_server(
        lambda r, w: _handle_media_connection(r, w, registry),
        host=str(args.media_host),
        port=int(args.media_port),
    )
    metadata_server = await asyncio.start_server(
        lambda r, w: _handle_metadata_connection(r, w, registry),
        host=str(args.metadata_host),
        port=int(args.metadata_port),
    )
    health_server = await asyncio.start_server(
        _handle_health_connection,
        host=str(args.health_host),
        port=int(args.health_port),
    )

    print(f"live media receiver listening on tcp://{args.media_host}:{args.media_port}")
    print(f"live metadata receiver listening on tcp://{args.metadata_host}:{args.metadata_port}")
    print(f"live health endpoint listening on http://{args.health_host}:{args.health_port}/health")
    print(f"incoming_root={incoming_root}")

    try:
        async with media_server, metadata_server, health_server:
            await asyncio.gather(
                media_server.serve_forever(),
                metadata_server.serve_forever(),
                health_server.serve_forever(),
            )
    finally:
        registry.close_all()


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()
    try:
        asyncio.run(_run_servers(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
