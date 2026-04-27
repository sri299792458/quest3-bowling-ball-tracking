from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import time
from typing import Any, Mapping
from uuid import uuid4

from laptop_receiver.lane_lock_types import LaneLockResult
from laptop_receiver.shot_result_types import ShotResult


RESULT_ENVELOPE_SCHEMA_VERSION = "laptop_result_envelope"

RESULT_KIND_LANE_LOCK_RESULT = "lane_lock_result"
RESULT_KIND_SHOT_RESULT = "shot_result"
RESULT_KIND_REPLAY_PATH = "replay_path"
RESULT_KIND_PIPELINE_ERROR = "pipeline_error"

SUPPORTED_RESULT_KINDS = {
    RESULT_KIND_LANE_LOCK_RESULT,
    RESULT_KIND_SHOT_RESULT,
    RESULT_KIND_REPLAY_PATH,
    RESULT_KIND_PIPELINE_ERROR,
}


class LaptopResultPublishError(RuntimeError):
    def __init__(self, message: str, error_code: str = "") -> None:
        super().__init__(message)
        self.error_code = error_code


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


@dataclass(frozen=True)
class LaptopResultEnvelope:
    schema_version: str
    kind: str
    session_id: str
    shot_id: str
    message_id: str
    created_unix_ms: int
    payload: Mapping[str, Any]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LaptopResultEnvelope":
        schema_version = _str(payload.get("schemaVersion"))
        if schema_version != RESULT_ENVELOPE_SCHEMA_VERSION:
            raise ValueError(f"Unsupported laptop result schemaVersion {schema_version!r}.")

        kind = _str(payload.get("kind"))
        if kind not in SUPPORTED_RESULT_KINDS:
            raise ValueError(f"Unsupported laptop result kind {kind!r}.")

        session_id = _str(payload.get("session_id"))
        shot_id = _str(payload.get("shot_id"))
        if not session_id:
            raise ValueError("laptop_result_envelope requires session_id.")
        if not shot_id:
            raise ValueError("laptop_result_envelope requires shot_id.")

        message_id = _str(payload.get("message_id"))
        if not message_id:
            raise ValueError("laptop_result_envelope requires message_id.")

        created_unix_ms = _int(payload.get("created_unix_ms"))
        if created_unix_ms <= 0:
            raise ValueError("laptop_result_envelope requires created_unix_ms.")

        if kind == RESULT_KIND_LANE_LOCK_RESULT:
            lane_lock_payload = payload.get("lane_lock_result")
            if not isinstance(lane_lock_payload, Mapping):
                raise ValueError("lane_lock_result envelope requires lane_lock_result payload.")
            lane_lock_result = LaneLockResult.from_dict(lane_lock_payload)
            if lane_lock_result.session_id != session_id:
                raise ValueError(
                    "lane_lock_result sessionId does not match envelope session_id."
                )
        elif kind == RESULT_KIND_SHOT_RESULT:
            shot_payload = payload.get("shot_result")
            if not isinstance(shot_payload, Mapping):
                raise ValueError("shot_result envelope requires shot_result payload.")
            shot_result = ShotResult.from_dict(shot_payload)
            if shot_result.session_id != session_id:
                raise ValueError("shot_result sessionId does not match envelope session_id.")
            if shot_result.shot_id != shot_id:
                raise ValueError("shot_result shotId does not match envelope shot_id.")

        return cls(
            schema_version=schema_version,
            kind=kind,
            session_id=session_id,
            shot_id=shot_id,
            message_id=message_id,
            created_unix_ms=created_unix_ms,
            payload=payload,
        )


def build_lane_lock_result_envelope(
    *,
    result: LaneLockResult,
    shot_id: str,
    message_id: str | None = None,
    created_unix_ms: int | None = None,
) -> dict[str, Any]:
    if not shot_id:
        raise ValueError("shot_id is required when building a lane-lock result envelope.")

    envelope = {
        "schemaVersion": RESULT_ENVELOPE_SCHEMA_VERSION,
        "kind": RESULT_KIND_LANE_LOCK_RESULT,
        "session_id": result.session_id,
        "shot_id": shot_id,
        "message_id": message_id or uuid4().hex,
        "created_unix_ms": int(created_unix_ms or time.time() * 1000),
        "lane_lock_result": result.to_dict(),
    }
    LaptopResultEnvelope.from_dict(envelope)
    return envelope


def build_shot_result_envelope(
    *,
    result: ShotResult,
    message_id: str | None = None,
    created_unix_ms: int | None = None,
) -> dict[str, Any]:
    envelope = {
        "schemaVersion": RESULT_ENVELOPE_SCHEMA_VERSION,
        "kind": RESULT_KIND_SHOT_RESULT,
        "session_id": result.session_id,
        "shot_id": result.shot_id,
        "message_id": message_id or uuid4().hex,
        "created_unix_ms": int(created_unix_ms or time.time() * 1000),
        "shot_result": result.to_dict(),
    }
    LaptopResultEnvelope.from_dict(envelope)
    return envelope


def validate_laptop_result_envelope(payload: Mapping[str, Any]) -> LaptopResultEnvelope:
    return LaptopResultEnvelope.from_dict(payload)


def publish_laptop_result(
    payload: Mapping[str, Any],
    *,
    host: str,
    port: int,
    timeout_seconds: float = 3.0,
) -> None:
    validate_laptop_result_envelope(payload)
    line = json.dumps(dict(payload), separators=(",", ":")) + "\n"
    with socket.create_connection((host, int(port)), timeout=float(timeout_seconds)) as sock:
        sock.settimeout(float(timeout_seconds))
        sock.sendall(line.encode("utf-8"))
        with sock.makefile("r", encoding="utf-8", newline="\n") as handle:
            response_line = handle.readline()
        if not response_line:
            raise RuntimeError("Result publish endpoint closed without an acknowledgement.")
        response = json.loads(response_line)
        if not bool(response.get("ok")):
            raise LaptopResultPublishError(
                str(response.get("error") or "result_publish_failed"),
                str(response.get("errorCode") or ""),
            )
