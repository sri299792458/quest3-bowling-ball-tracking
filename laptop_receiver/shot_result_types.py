from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from laptop_receiver.lane_lock_types import LaneSpaceBallPoint, SourceFrameRange
from laptop_receiver.shot_stats import ShotStats


SHOT_RESULT_SCHEMA_VERSION = "shot_result"


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


@dataclass(frozen=True)
class ShotTrackingSummary:
    source: str
    yolo_success: bool
    sam2_success: bool
    tracked_frames: int
    trajectory_points: int
    average_projection_confidence: float

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ShotTrackingSummary":
        source = payload or {}
        return cls(
            source=_str(source.get("source")),
            yolo_success=bool(source.get("yoloSuccess")),
            sam2_success=bool(source.get("sam2Success")),
            tracked_frames=_int(source.get("trackedFrames")),
            trajectory_points=_int(source.get("trajectoryPoints")),
            average_projection_confidence=_float(source.get("averageProjectionConfidence")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "yoloSuccess": self.yolo_success,
            "sam2Success": self.sam2_success,
            "trackedFrames": self.tracked_frames,
            "trajectoryPoints": self.trajectory_points,
            "averageProjectionConfidence": self.average_projection_confidence,
        }


@dataclass(frozen=True)
class ShotResult:
    schema_version: str
    session_id: str
    shot_id: str
    window_id: str
    success: bool
    failure_reason: str
    lane_lock_request_id: str
    source_frame_range: SourceFrameRange
    tracking_summary: ShotTrackingSummary
    shot_stats: ShotStats | None
    trajectory: list[LaneSpaceBallPoint]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShotResult":
        schema_version = _str(payload.get("schemaVersion"))
        if schema_version != SHOT_RESULT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported shot_result schemaVersion {schema_version!r}.")

        session_id = _str(payload.get("sessionId"))
        shot_id = _str(payload.get("shotId"))
        if not session_id:
            raise ValueError("shot_result requires sessionId.")
        if not shot_id:
            raise ValueError("shot_result requires shotId.")

        trajectory_payload = payload.get("trajectory")
        if not isinstance(trajectory_payload, list):
            raise ValueError("shot_result requires trajectory list.")
        trajectory: list[LaneSpaceBallPoint] = []
        for index, point in enumerate(trajectory_payload):
            if not isinstance(point, Mapping):
                raise ValueError(f"shot_result trajectory[{index}] must be an object.")
            lane_point = LaneSpaceBallPoint.from_dict(point)
            if lane_point.session_id != session_id:
                raise ValueError(f"shot_result trajectory[{index}] sessionId mismatch.")
            if lane_point.shot_id != shot_id:
                raise ValueError(f"shot_result trajectory[{index}] shotId mismatch.")
            trajectory.append(lane_point)

        result = cls(
            schema_version=schema_version,
            session_id=session_id,
            shot_id=shot_id,
            window_id=_str(payload.get("windowId")),
            success=bool(payload.get("success")),
            failure_reason=_str(payload.get("failureReason")),
            lane_lock_request_id=_str(payload.get("laneLockRequestId")),
            source_frame_range=SourceFrameRange.from_dict(payload.get("sourceFrameRange")),
            tracking_summary=ShotTrackingSummary.from_dict(payload.get("trackingSummary")),
            shot_stats=(
                ShotStats.from_dict(payload.get("shotStats"))
                if payload.get("shotStats") is not None
                else None
            ),
            trajectory=trajectory,
        )
        if result.success and result.shot_stats is None:
            raise ValueError("successful shot_result requires shotStats.")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "shotId": self.shot_id,
            "windowId": self.window_id,
            "success": self.success,
            "failureReason": self.failure_reason,
            "laneLockRequestId": self.lane_lock_request_id,
            "sourceFrameRange": self.source_frame_range.to_dict(),
            "trackingSummary": self.tracking_summary.to_dict(),
            "shotStats": self.shot_stats.to_dict() if self.shot_stats is not None else None,
            "trajectory": [point.to_dict() for point in self.trajectory],
        }
