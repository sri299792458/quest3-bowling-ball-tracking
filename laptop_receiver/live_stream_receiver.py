from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import socket
import struct
import time
from typing import Any

from laptop_receiver.laptop_result_types import validate_laptop_result_envelope
from laptop_receiver.session_state import (
    LANE_CANDIDATE_RECEIVED,
    LANE_CONFIRMED,
    LANE_FAILED,
    LANE_REJECTED,
    LANE_REQUEST_QUEUED,
    SHOT_ARMED,
    SHOT_DISABLED_UNTIL_LANE_CONFIRMED,
    SHOT_OPEN,
    SHOT_RESULT_FAILED,
    SHOT_RESULT_READY,
    SHOT_WINDOW_COMPLETE,
    TRANSPORT_CONNECTING,
    TRANSPORT_ENDED,
    TRANSPORT_STREAMING,
    mark_lane,
    mark_shot,
    mark_transport,
    increment_replay_successful_shot_count,
)


DISCOVERY_SCHEMA_VERSION = "quest_bowling_laptop_discovery_v1"
DISCOVERY_REQUEST_KIND = "quest_bowling_laptop_discovery_request"
DISCOVERY_RESPONSE_KIND = "quest_bowling_laptop_discovery_response"
DEFAULT_DISCOVERY_HOST = "0.0.0.0"
DEFAULT_DISCOVERY_PORT = 8765
DEFAULT_MEDIA_HOST = "0.0.0.0"
DEFAULT_MEDIA_PORT = 8766
DEFAULT_METADATA_HOST = "0.0.0.0"
DEFAULT_METADATA_PORT = 8767
DEFAULT_HEALTH_HOST = "0.0.0.0"
DEFAULT_HEALTH_PORT = 8768
DEFAULT_RESULT_HOST = "0.0.0.0"
DEFAULT_RESULT_PORT = 8769
DEFAULT_RESULT_PUBLISH_HOST = "127.0.0.1"
DEFAULT_RESULT_PUBLISH_PORT = 8770
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


def _resolve_advertise_host(advertise_host: str, peer: tuple[Any, ...] | None) -> str:
    configured = (advertise_host or "").strip()
    if configured:
        return configured

    peer_host = str(peer[0]) if peer else ""
    peer_port = int(peer[1]) if peer and len(peer) > 1 else DEFAULT_DISCOVERY_PORT
    if peer_host:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
                route_socket.connect((peer_host, max(1, peer_port)))
                route_host = str(route_socket.getsockname()[0])
                if route_host:
                    return route_host
        except OSError:
            pass

    try:
        host = socket.gethostbyname(socket.gethostname())
        if host:
            return str(host)
    except OSError:
        pass

    return "127.0.0.1"


class LaptopDiscoveryResponder(asyncio.DatagramProtocol):
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[Any, ...]) -> None:
        if self._transport is None:
            return

        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return

        if payload.get("schemaVersion") != DISCOVERY_SCHEMA_VERSION:
            return
        if payload.get("kind") != DISCOVERY_REQUEST_KIND:
            return

        response = {
            "schemaVersion": DISCOVERY_SCHEMA_VERSION,
            "kind": DISCOVERY_RESPONSE_KIND,
            "host": _resolve_advertise_host(str(self._args.advertise_host), addr),
            "mediaPort": int(self._args.media_port),
            "metadataPort": int(self._args.metadata_port),
            "resultPort": int(self._args.result_port),
            "healthPort": int(self._args.health_port),
            "resultPublishPort": int(self._args.result_publish_port),
        }
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        self._transport.sendto(encoded, addr)


@dataclass
class LiveStreamSession:
    session_id: str
    shot_id: str
    root_dir: Path
    media_stream_path: Path
    media_samples_path: Path
    metadata_stream_path: Path
    lane_lock_requests_path: Path
    lane_lock_confirms_path: Path
    shot_boundaries_path: Path
    outbound_results_path: Path
    codec_config_path: Path
    session_start_path: Path
    session_end_path: Path
    stream_receipt_path: Path
    media_file: Any = None
    media_samples_file: Any = None
    metadata_stream_file: Any = None
    lane_lock_requests_file: Any = None
    lane_lock_confirms_file: Any = None
    shot_boundaries_file: Any = None
    outbound_results_file: Any = None
    session_started_payload: dict[str, Any] | None = None
    session_ended_payload: dict[str, Any] | None = None
    sample_count: int = 0
    keyframe_count: int = 0
    metadata_message_count: int = 0
    outbound_result_count: int = 0
    first_pts_us: int | None = None
    last_pts_us: int | None = None
    codec_config_seen: bool = False
    codec_config_bytes: int = 0

    def open(self, *, append_existing: bool = False) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.media_file = self.media_stream_path.open("ab" if append_existing else "wb")
        self.media_samples_file = self.media_samples_path.open(
            "a" if append_existing else "w",
            encoding="utf-8",
            newline="\n",
        )
        self.metadata_stream_file = self.metadata_stream_path.open("a", encoding="utf-8", newline="\n")
        self.lane_lock_requests_file = self.lane_lock_requests_path.open("a", encoding="utf-8", newline="\n")
        self.lane_lock_confirms_file = self.lane_lock_confirms_path.open("a", encoding="utf-8", newline="\n")
        self.shot_boundaries_file = self.shot_boundaries_path.open("a", encoding="utf-8", newline="\n")
        self.outbound_results_file = self.outbound_results_path.open("a", encoding="utf-8", newline="\n")

    def close(self) -> None:
        for handle_name in (
            "media_file",
            "media_samples_file",
            "metadata_stream_file",
            "lane_lock_requests_file",
            "lane_lock_confirms_file",
            "shot_boundaries_file",
            "outbound_results_file",
        ):
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
            "outbound_result_count": self.outbound_result_count,
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
        self._mark_transport(
            TRANSPORT_CONNECTING,
            mediaSessionStartSeen=True,
        )
        self.persist_receipt()

    def write_session_end(self, payload: dict[str, Any]) -> None:
        self.session_ended_payload = payload
        self.session_end_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._mark_transport(TRANSPORT_ENDED, sessionEndSeen=True)
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
        if self.sample_count == 1 or is_keyframe or self.sample_count % 30 == 0:
            self._mark_transport(TRANSPORT_STREAMING)
        self.persist_receipt()

    def write_codec_config(self, codec_config_bytes: bytes) -> None:
        if self.media_file is None:
            raise RuntimeError("Live stream session files are not open.")

        self.media_file.write(codec_config_bytes)
        self.media_file.flush()
        self.codec_config_path.write_bytes(codec_config_bytes)
        self.codec_config_seen = True
        self.codec_config_bytes = int(len(codec_config_bytes))
        self._mark_transport(
            TRANSPORT_CONNECTING,
            codecConfigSeen=True,
        )
        self.persist_receipt()

    def append_metadata_message(self, payload: dict[str, Any]) -> None:
        if self.metadata_stream_file is None:
            raise RuntimeError("Metadata stream file is not open.")

        self.metadata_stream_file.write(json.dumps(payload) + "\n")
        self.metadata_stream_file.flush()
        self.metadata_message_count += 1
        kind = str(payload.get("kind") or "")
        if kind == "session_start":
            self._mark_transport(TRANSPORT_CONNECTING, metadataSessionStartSeen=True)
        elif kind == "frame_metadata":
            frame_metadata = payload.get("frame_metadata")
            if isinstance(frame_metadata, dict):
                frame_seq = frame_metadata.get("frameSeq")
                pts_us = frame_metadata.get("ptsUs")
                if self.metadata_message_count == 1 or self.metadata_message_count % 30 == 0:
                    self._mark_transport(
                        TRANSPORT_STREAMING,
                        lastFrameSeq=frame_seq,
                        lastFramePtsUs=pts_us,
                    )
        self.persist_receipt()

    def append_lane_lock_request(self, payload: dict[str, Any]) -> None:
        if self.lane_lock_requests_file is None:
            raise RuntimeError("Lane-lock request file is not open.")

        self.lane_lock_requests_file.write(json.dumps(payload) + "\n")
        self.lane_lock_requests_file.flush()
        request = payload.get("lane_lock_request")
        request_id = str(request.get("requestId") or "") if isinstance(request, dict) else ""
        mark_lane(
            self.root_dir,
            LANE_REQUEST_QUEUED,
            activeRequestId=request_id,
            lastFailureReason="",
        )

    def append_lane_lock_confirm(self, payload: dict[str, Any]) -> None:
        if self.lane_lock_confirms_file is None:
            raise RuntimeError("Lane-lock confirm file is not open.")

        self.lane_lock_confirms_file.write(json.dumps(payload) + "\n")
        self.lane_lock_confirms_file.flush()
        request_id = str(payload.get("requestId") or payload.get("request_id") or "")
        accepted = bool(payload.get("accepted"))
        reason = str(payload.get("reason") or "")
        if accepted:
            mark_lane(
                self.root_dir,
                LANE_CONFIRMED,
                confirmedRequestId=request_id,
                activeRequestId="",
                lastFailureReason="",
            )
            mark_shot(
                self.root_dir,
                SHOT_ARMED,
                activeLaneLockRequestId=request_id,
                candidateStartFrameSeq=None,
                openWindowId="",
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason="",
                lastReason="lane_confirmed",
            )
        else:
            mark_lane(
                self.root_dir,
                LANE_REJECTED,
                activeRequestId="",
                candidateRequestId="",
                confirmedRequestId="",
                candidateResultPath="",
                confirmedResultPath="",
                lastFailureReason=reason,
            )
            mark_shot(
                self.root_dir,
                SHOT_DISABLED_UNTIL_LANE_CONFIRMED,
                activeLaneLockRequestId="",
                candidateStartFrameSeq=None,
                openWindowId="",
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason=reason,
                lastReason=reason,
            )

    def append_shot_boundary(self, payload: dict[str, Any]) -> None:
        if self.shot_boundaries_file is None:
            raise RuntimeError("Shot-boundary file is not open.")

        self.shot_boundaries_file.write(json.dumps(payload) + "\n")
        self.shot_boundaries_file.flush()
        boundary_type = str(payload.get("boundary_type") or "")
        frame_seq = payload.get("frame_seq")
        lane_lock_request_id = str(payload.get("laneLockRequestId") or payload.get("lane_lock_request_id") or "")
        reason = str(payload.get("reason") or "")
        if boundary_type == "shot_start":
            mark_shot(
                self.root_dir,
                SHOT_OPEN,
                activeLaneLockRequestId=lane_lock_request_id,
                openWindowId=f"shot_{frame_seq}",
                openFrameSeqStart=frame_seq,
                openFrameSeqEnd=None,
                lastReason=reason,
            )
        elif boundary_type == "shot_end":
            mark_shot(
                self.root_dir,
                SHOT_WINDOW_COMPLETE,
                activeLaneLockRequestId=lane_lock_request_id,
                openWindowId="",
                openFrameSeqEnd=frame_seq,
                lastReason=reason,
            )

    def append_outbound_result(self, payload: dict[str, Any]) -> None:
        if self.outbound_results_file is None:
            raise RuntimeError("Outbound result file is not open.")

        self.outbound_results_file.write(json.dumps(payload) + "\n")
        self.outbound_results_file.flush()
        self.outbound_result_count += 1
        self._mark_result_state(payload)
        self.persist_receipt()

    def _mark_transport(self, state: str, **fields: Any) -> None:
        mark_transport(
            self.root_dir,
            state,
            session_id=self.session_id,
            stream_id=self.shot_id,
            **fields,
        )

    def _mark_result_state(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind") or "")
        if kind == "lane_lock_result":
            result = payload.get("lane_lock_result")
            if not isinstance(result, dict):
                return
            request_id = str(result.get("requestId") or "")
            success = bool(result.get("success"))
            if success:
                mark_lane(
                    self.root_dir,
                    LANE_CANDIDATE_RECEIVED,
                    candidateRequestId=request_id,
                    activeRequestId="",
                    lastFailureReason="",
                )
            else:
                mark_lane(
                    self.root_dir,
                    LANE_FAILED,
                    activeRequestId="",
                    candidateRequestId=request_id,
                    lastFailureReason=str(result.get("failureReason") or ""),
                )
            return

        if kind == "shot_result":
            result = payload.get("shot_result")
            if not isinstance(result, dict):
                return
            window_id = str(result.get("windowId") or "")
            lane_lock_request_id = str(result.get("laneLockRequestId") or "")
            success = bool(result.get("success"))
            if success:
                mark_shot(
                    self.root_dir,
                    SHOT_RESULT_READY,
                    latestWindowId=window_id,
                    activeLaneLockRequestId=lane_lock_request_id,
                    openWindowId="",
                    lastFailureReason="",
                    lastReason="shot_result_ready",
                )
                increment_replay_successful_shot_count(self.root_dir, latest_window_id=window_id)
            else:
                mark_shot(
                    self.root_dir,
                    SHOT_RESULT_FAILED,
                    latestWindowId=window_id,
                    activeLaneLockRequestId=lane_lock_request_id,
                    openWindowId="",
                    lastFailureReason=str(result.get("failureReason") or ""),
                    lastReason="shot_result_failed",
                )


@dataclass
class LiveStreamRegistry:
    incoming_root: Path
    sessions: dict[tuple[str, str], LiveStreamSession] = field(default_factory=dict)

    def recover_existing_sessions(self) -> None:
        if not self.incoming_root.exists():
            return

        candidates = sorted(
            [path for path in self.incoming_root.iterdir() if path.is_dir() and path.name.startswith("live_")],
            key=lambda path: path.stat().st_mtime,
        )
        for root_dir in candidates:
            recovered = self._recover_session(root_dir)
            if recovered is None:
                continue
            key = (recovered.session_id, recovered.shot_id)
            existing = self.sessions.get(key)
            if existing is not None:
                existing.close()
            self.sessions[key] = recovered

    def get_or_create(self, session_id: str, shot_id: str) -> LiveStreamSession:
        key = (session_id, shot_id)
        existing = self.sessions.get(key)
        if existing is not None:
            return existing

        return self._create_session(session_id, shot_id)

    def start_metadata_session(self, session_id: str, shot_id: str) -> LiveStreamSession:
        key = (session_id, shot_id)
        existing = self.sessions.get(key)
        if existing is None:
            return self._create_session(session_id, shot_id)
        if existing.session_ended_payload is not None:
            existing.close()
            return self._create_session(session_id, shot_id)
        return existing

    def start_media_session(self, session_id: str, shot_id: str) -> LiveStreamSession:
        key = (session_id, shot_id)
        existing = self.sessions.get(key)
        if existing is None:
            return self._create_session(session_id, shot_id)
        if existing.sample_count > 0 or existing.session_ended_payload is not None:
            existing.close()
            return self._create_session(session_id, shot_id)
        return existing

    def _create_session(self, session_id: str, shot_id: str) -> LiveStreamSession:
        key = (session_id, shot_id)
        root_dir = self._next_root_dir(session_id, shot_id)
        session = LiveStreamSession(
            session_id=session_id,
            shot_id=shot_id,
            root_dir=root_dir,
            media_stream_path=root_dir / "stream.h264",
            media_samples_path=root_dir / "media_samples.jsonl",
            metadata_stream_path=root_dir / "metadata_stream.jsonl",
            lane_lock_requests_path=root_dir / "lane_lock_requests.jsonl",
            lane_lock_confirms_path=root_dir / "lane_lock_confirms.jsonl",
            shot_boundaries_path=root_dir / "shot_boundaries.jsonl",
            outbound_results_path=root_dir / "outbound_results.jsonl",
            codec_config_path=root_dir / "codec_config.h264",
            session_start_path=root_dir / "session_start.json",
            session_end_path=root_dir / "session_end.json",
            stream_receipt_path=root_dir / "stream_receipt.json",
        )
        session.open()
        mark_transport(
            root_dir,
            TRANSPORT_CONNECTING,
            session_id=session_id,
            stream_id=shot_id,
        )
        session.persist_receipt()
        self.sessions[key] = session
        return session

    def _recover_session(self, root_dir: Path) -> LiveStreamSession | None:
        identity = self._recover_session_identity(root_dir)
        if identity is None:
            return None
        session_id, shot_id = identity
        receipt = self._load_json(root_dir / "stream_receipt.json")
        session_end_payload = self._load_json(root_dir / "session_end.json")
        session_start_payload = self._load_json(root_dir / "session_start.json")
        session = LiveStreamSession(
            session_id=session_id,
            shot_id=shot_id,
            root_dir=root_dir,
            media_stream_path=root_dir / "stream.h264",
            media_samples_path=root_dir / "media_samples.jsonl",
            metadata_stream_path=root_dir / "metadata_stream.jsonl",
            lane_lock_requests_path=root_dir / "lane_lock_requests.jsonl",
            lane_lock_confirms_path=root_dir / "lane_lock_confirms.jsonl",
            shot_boundaries_path=root_dir / "shot_boundaries.jsonl",
            outbound_results_path=root_dir / "outbound_results.jsonl",
            codec_config_path=root_dir / "codec_config.h264",
            session_start_path=root_dir / "session_start.json",
            session_end_path=root_dir / "session_end.json",
            stream_receipt_path=root_dir / "stream_receipt.json",
            session_started_payload=session_start_payload or None,
            session_ended_payload=session_end_payload or None,
            sample_count=int(receipt.get("sample_count") or self._count_lines(root_dir / "media_samples.jsonl")),
            keyframe_count=int(receipt.get("keyframe_count") or 0),
            metadata_message_count=int(
                receipt.get("metadata_message_count") or self._count_lines(root_dir / "metadata_stream.jsonl")
            ),
            outbound_result_count=int(
                receipt.get("outbound_result_count") or self._count_lines(root_dir / "outbound_results.jsonl")
            ),
            first_pts_us=receipt.get("first_pts_us"),
            last_pts_us=receipt.get("last_pts_us"),
            codec_config_seen=bool(receipt.get("codec_config_seen") or (root_dir / "codec_config.h264").exists()),
            codec_config_bytes=int(receipt.get("codec_config_bytes") or 0),
        )
        session.open(append_existing=True)
        session.persist_receipt()
        return session

    def _recover_session_identity(self, root_dir: Path) -> tuple[str, str] | None:
        for path in (root_dir / "stream_receipt.json", root_dir / "session_start.json"):
            payload = self._load_json(path)
            session_id = str(payload.get("session_id") or "").strip()
            shot_id = str(payload.get("shot_id") or "").strip()
            if session_id and shot_id:
                return session_id, shot_id
        return None

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _count_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def _next_root_dir(self, session_id: str, shot_id: str) -> Path:
        base = self.incoming_root / f"live_{_sanitize_file_part(session_id)}_{_sanitize_file_part(shot_id)}"
        if not base.exists():
            return base

        for attempt in range(1000):
            suffix = int(time.time() * 1000) + attempt
            candidate = self.incoming_root / (
                f"live_{_sanitize_file_part(session_id)}_{_sanitize_file_part(shot_id)}_{suffix}"
            )
            if not candidate.exists():
                return candidate

        raise RuntimeError("Could not allocate a unique live stream directory.")

    def get_existing(self, session_id: str, shot_id: str) -> LiveStreamSession | None:
        return self.sessions.get((session_id, shot_id))

    def close_all(self) -> None:
        for session in self.sessions.values():
            session.persist_receipt()
            session.close()


@dataclass
class LiveResultHub:
    registry: LiveStreamRegistry
    clients: dict[asyncio.StreamWriter, asyncio.Lock] = field(default_factory=dict)

    async def handle_result_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.clients[writer] = asyncio.Lock()
        try:
            await self.replay_outbound_results(writer)
            await reader.read()
        finally:
            self.clients.pop(writer, None)
            writer.close()
            await writer.wait_closed()

    async def handle_result_publish(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                stripped = line.decode("utf-8").strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                    envelope = validate_laptop_result_envelope(payload)
                    session = self.registry.get_existing(envelope.session_id, envelope.shot_id)
                    if session is None:
                        response = {
                            "ok": False,
                            "errorCode": "unknown_active_stream",
                            "error": (
                                f"Unknown active stream session_id={envelope.session_id!r} "
                                f"shot_id={envelope.shot_id!r}."
                            ),
                        }
                        writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
                        await writer.drain()
                        continue
                    session.append_outbound_result(dict(payload))
                    await self.broadcast(dict(payload))
                    response = {"ok": True, "kind": envelope.kind, "message_id": envelope.message_id}
                except Exception as exc:
                    response = {
                        "ok": False,
                        "errorCode": "result_publish_failed",
                        "error": exc.__class__.__name__ + ": " + str(exc),
                    }
                writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return

        dead_clients: list[asyncio.StreamWriter] = []
        line = json.dumps(payload, separators=(",", ":"))
        for client in list(self.clients):
            try:
                await self._send_line(client, line)
            except Exception:
                dead_clients.append(client)

        for client in dead_clients:
            self.clients.pop(client, None)
            try:
                client.close()
                await client.wait_closed()
            except Exception:
                pass

    async def replay_outbound_results(self, writer: asyncio.StreamWriter) -> None:
        sessions = sorted(
            list(self.registry.sessions.values()),
            key=lambda session: session.root_dir.stat().st_mtime if session.root_dir.exists() else 0.0,
        )
        for session in sessions:
            path = session.outbound_results_path
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped:
                    await self._send_line(writer, stripped)

    async def _send_line(self, writer: asyncio.StreamWriter, line: str) -> None:
        lock = self.clients.get(writer)
        encoded = (line + "\n").encode("utf-8")
        if lock is None:
            writer.write(encoded)
            await writer.drain()
            return
        async with lock:
            writer.write(encoded)
            await writer.drain()


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
                active_session = registry.start_media_session(session_id, shot_id)
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
            kind = str(payload.get("kind") or "")
            if kind == "session_start":
                session = registry.start_metadata_session(session_id, shot_id)
            else:
                session = registry.get_or_create(session_id, shot_id)
            session.append_metadata_message(payload)
            if kind == "lane_lock_request":
                session.append_lane_lock_request(payload)
            elif kind == "lane_lock_confirm":
                session.append_lane_lock_confirm(payload)
            elif kind == "shot_boundary":
                session.append_shot_boundary(payload)
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
    parser.add_argument("--discovery-host", default=DEFAULT_DISCOVERY_HOST)
    parser.add_argument("--discovery-port", type=int, default=DEFAULT_DISCOVERY_PORT)
    parser.add_argument("--advertise-host", default="")
    parser.add_argument("--media-host", default=DEFAULT_MEDIA_HOST)
    parser.add_argument("--media-port", type=int, default=DEFAULT_MEDIA_PORT)
    parser.add_argument("--metadata-host", default=DEFAULT_METADATA_HOST)
    parser.add_argument("--metadata-port", type=int, default=DEFAULT_METADATA_PORT)
    parser.add_argument("--health-host", default=DEFAULT_HEALTH_HOST)
    parser.add_argument("--health-port", type=int, default=DEFAULT_HEALTH_PORT)
    parser.add_argument("--result-host", default=DEFAULT_RESULT_HOST)
    parser.add_argument("--result-port", type=int, default=DEFAULT_RESULT_PORT)
    parser.add_argument("--result-publish-host", default=DEFAULT_RESULT_PUBLISH_HOST)
    parser.add_argument("--result-publish-port", type=int, default=DEFAULT_RESULT_PUBLISH_PORT)
    return parser


async def _run_servers(args: argparse.Namespace) -> None:
    incoming_root = args.incoming_root.expanduser().resolve()
    incoming_root.mkdir(parents=True, exist_ok=True)
    registry = LiveStreamRegistry(incoming_root=incoming_root)
    registry.recover_existing_sessions()
    result_hub = LiveResultHub(registry=registry)
    loop = asyncio.get_running_loop()
    discovery_transport, _ = await loop.create_datagram_endpoint(
        lambda: LaptopDiscoveryResponder(args),
        local_addr=(str(args.discovery_host), int(args.discovery_port)),
        allow_broadcast=True,
    )

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
    result_server = await asyncio.start_server(
        result_hub.handle_result_client,
        host=str(args.result_host),
        port=int(args.result_port),
    )
    result_publish_server = await asyncio.start_server(
        result_hub.handle_result_publish,
        host=str(args.result_publish_host),
        port=int(args.result_publish_port),
    )

    print(f"live media receiver listening on tcp://{args.media_host}:{args.media_port}")
    print(f"live metadata receiver listening on tcp://{args.metadata_host}:{args.metadata_port}")
    print(f"Quest laptop discovery listening on udp://{args.discovery_host}:{args.discovery_port}")
    print(f"live health endpoint listening on http://{args.health_host}:{args.health_port}/health")
    print(f"Quest result channel listening on tcp://{args.result_host}:{args.result_port}")
    print(f"local result publish endpoint listening on tcp://{args.result_publish_host}:{args.result_publish_port}")
    print(f"incoming_root={incoming_root}")

    try:
        async with media_server, metadata_server, health_server, result_server, result_publish_server:
            await asyncio.gather(
                media_server.serve_forever(),
                metadata_server.serve_forever(),
                health_server.serve_forever(),
                result_server.serve_forever(),
                result_publish_server.serve_forever(),
            )
    finally:
        discovery_transport.close()
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
