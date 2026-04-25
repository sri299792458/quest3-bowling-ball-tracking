from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from laptop_receiver.lane_lock_types import FrameCameraState, LaneLockRequest
from laptop_receiver.local_clip_artifact import LocalClipArtifact, load_local_clip_artifact


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


@dataclass(frozen=True)
class LiveSessionLaneLockRequest:
    artifact: LocalClipArtifact
    request_envelope: dict[str, Any]
    request: LaneLockRequest
    frame_states: list[FrameCameraState]

    @property
    def session_dir(self) -> Path:
        return self.artifact.root_dir


def load_lane_lock_request_envelopes(session_dir: Path | str) -> list[dict[str, Any]]:
    root = Path(session_dir).expanduser().resolve()
    lane_lock_requests_path = root / "lane_lock_requests.jsonl"
    return _load_jsonl(lane_lock_requests_path)


def load_live_session_lane_lock_request(
    session_dir: Path | str,
    request_id: str | None = None,
) -> LiveSessionLaneLockRequest:
    artifact = load_local_clip_artifact(session_dir)
    envelopes = load_lane_lock_request_envelopes(artifact.root_dir)
    if not envelopes:
        raise RuntimeError(f"No lane_lock_request messages found in {artifact.root_dir}")

    selected_envelope: dict[str, Any] | None = None
    if request_id:
        for envelope in envelopes:
            payload = envelope.get("lane_lock_request") or {}
            if str(payload.get("requestId") or "") == request_id:
                selected_envelope = envelope
                break
        if selected_envelope is None:
            raise RuntimeError(f"Could not find lane_lock_request requestId={request_id!r} in {artifact.root_dir}")
    else:
        selected_envelope = envelopes[-1]

    request_payload = selected_envelope.get("lane_lock_request")
    if not isinstance(request_payload, dict):
        raise RuntimeError("lane_lock_request envelope missing request payload.")

    request = LaneLockRequest.from_dict(request_payload)
    frame_states = [
        FrameCameraState.from_frame_metadata(frame_metadata)
        for frame_metadata in artifact.frame_metadata
        if int(frame_metadata.get("frameSeq", -1)) >= int(request.frame_seq_start)
        and int(frame_metadata.get("frameSeq", -1)) <= int(request.frame_seq_end)
    ]
    if not frame_states:
        raise RuntimeError(
            f"No frame metadata matched lane_lock_request frame range {request.frame_seq_start}..{request.frame_seq_end}"
        )

    return LiveSessionLaneLockRequest(
        artifact=artifact,
        request_envelope=selected_envelope,
        request=request,
        frame_states=frame_states,
    )
