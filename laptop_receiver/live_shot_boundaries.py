from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SHOT_BOUNDARY_START = "shot_start"
SHOT_BOUNDARY_END = "shot_end"
SUPPORTED_SHOT_BOUNDARY_TYPES = {SHOT_BOUNDARY_START, SHOT_BOUNDARY_END}


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"shot_boundary requires integer {field_name}.") from exc


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON in shot_boundaries.jsonl") from exc
    return rows


@dataclass(frozen=True)
class ShotBoundaryEvent:
    envelope_index: int
    session_id: str
    shot_id: str
    lane_lock_request_id: str
    boundary_type: str
    frame_seq: int
    camera_timestamp_us: int
    pts_us: int
    reason: str

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any], envelope_index: int) -> "ShotBoundaryEvent":
        kind = _str(envelope.get("kind"))
        if kind != "shot_boundary":
            raise ValueError(f"Unsupported shot boundary kind {kind!r}.")

        boundary_type = _str(envelope.get("boundary_type")).strip()
        if boundary_type not in SUPPORTED_SHOT_BOUNDARY_TYPES:
            raise ValueError(
                "shot_boundary boundary_type must be "
                f"{SHOT_BOUNDARY_START!r} or {SHOT_BOUNDARY_END!r}; got {boundary_type!r}."
            )

        session_id = _str(envelope.get("session_id")).strip()
        shot_id = _str(envelope.get("shot_id")).strip()
        if not session_id:
            raise ValueError("shot_boundary requires session_id.")
        if not shot_id:
            raise ValueError("shot_boundary requires shot_id.")

        frame_seq = _int(envelope.get("frame_seq"), "frame_seq")
        camera_timestamp_us = _int(envelope.get("camera_timestamp_us"), "camera_timestamp_us")
        pts_us = _int(envelope.get("pts_us"), "pts_us")
        if frame_seq < 0:
            raise ValueError("shot_boundary frame_seq must be non-negative.")

        return cls(
            envelope_index=int(envelope_index),
            session_id=session_id,
            shot_id=shot_id,
            lane_lock_request_id=_str(envelope.get("laneLockRequestId") or envelope.get("lane_lock_request_id")).strip(),
            boundary_type=boundary_type,
            frame_seq=frame_seq,
            camera_timestamp_us=camera_timestamp_us,
            pts_us=pts_us,
            reason=_str(envelope.get("reason")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelopeIndex": self.envelope_index,
            "sessionId": self.session_id,
            "shotId": self.shot_id,
            "laneLockRequestId": self.lane_lock_request_id,
            "boundaryType": self.boundary_type,
            "frameSeq": self.frame_seq,
            "cameraTimestampUs": self.camera_timestamp_us,
            "ptsUs": self.pts_us,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CompletedShotWindow:
    window_id: str
    session_id: str
    shot_id: str
    lane_lock_request_id: str
    start: ShotBoundaryEvent
    end: ShotBoundaryEvent

    @property
    def frame_seq_start(self) -> int:
        return self.start.frame_seq

    @property
    def frame_seq_end(self) -> int:
        return self.end.frame_seq

    def to_dict(self) -> dict[str, Any]:
        return {
            "windowId": self.window_id,
            "sessionId": self.session_id,
            "shotId": self.shot_id,
            "laneLockRequestId": self.lane_lock_request_id,
            "frameSeqStart": self.frame_seq_start,
            "frameSeqEnd": self.frame_seq_end,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }


@dataclass(frozen=True)
class ShotBoundaryLoadResult:
    events: list[ShotBoundaryEvent]
    completed_windows: list[CompletedShotWindow]
    open_start: ShotBoundaryEvent | None
    errors: list[str]


def build_completed_shot_windows(events: list[ShotBoundaryEvent]) -> ShotBoundaryLoadResult:
    completed_windows: list[CompletedShotWindow] = []
    errors: list[str] = []
    open_start: ShotBoundaryEvent | None = None

    for event in events:
        if event.boundary_type == SHOT_BOUNDARY_START:
            if open_start is not None:
                errors.append(
                    "Nested shot_start at frame "
                    f"{event.frame_seq}; open shot started at frame {open_start.frame_seq}."
                )
                continue
            open_start = event
            continue

        if open_start is None:
            errors.append(f"shot_end at frame {event.frame_seq} has no preceding shot_start.")
            continue

        if event.session_id != open_start.session_id or event.shot_id != open_start.shot_id:
            errors.append(
                "shot_end session/shot id does not match open shot_start "
                f"at frame {open_start.frame_seq}."
            )
            open_start = None
            continue

        if event.lane_lock_request_id != open_start.lane_lock_request_id:
            errors.append(
                "shot_end laneLockRequestId does not match open shot_start "
                f"at frame {open_start.frame_seq}."
            )
            open_start = None
            continue

        if event.frame_seq < open_start.frame_seq:
            errors.append(
                f"shot_end frame {event.frame_seq} is before shot_start frame {open_start.frame_seq}."
            )
            open_start = None
            continue

        window_id = f"shot_{open_start.frame_seq}_{event.frame_seq}"
        completed_windows.append(
            CompletedShotWindow(
                window_id=window_id,
                session_id=open_start.session_id,
                shot_id=open_start.shot_id,
                lane_lock_request_id=open_start.lane_lock_request_id,
                start=open_start,
                end=event,
            )
        )
        open_start = None

    return ShotBoundaryLoadResult(
        events=events,
        completed_windows=completed_windows,
        open_start=open_start,
        errors=errors,
    )


def load_shot_boundaries(session_dir: Path | str) -> ShotBoundaryLoadResult:
    root = Path(session_dir).expanduser().resolve()
    envelopes = _load_jsonl(root / "shot_boundaries.jsonl")
    events: list[ShotBoundaryEvent] = []
    errors: list[str] = []
    for index, envelope in enumerate(envelopes):
        try:
            events.append(ShotBoundaryEvent.from_envelope(envelope, envelope_index=index))
        except Exception as exc:
            errors.append(f"shot_boundaries.jsonl[{index}]: {exc}")

    result = build_completed_shot_windows(events)
    return ShotBoundaryLoadResult(
        events=result.events,
        completed_windows=result.completed_windows,
        open_start=result.open_start,
        errors=[*errors, *result.errors],
    )
