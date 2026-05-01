from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from laptop_receiver.lane_lock_types import LaneLockResult, SourceFrameRange
from laptop_receiver.live_camera_sam2_tracker import LiveCameraSam2Config, LiveCameraSam2TrackResult
from laptop_receiver.live_lane_lock_results import load_lane_lock_result_for_request
from laptop_receiver.live_shot_boundaries import CompletedShotWindow
from laptop_receiver.shot_result_types import SHOT_RESULT_SCHEMA_VERSION, ShotResult, ShotTrackingSummary
from laptop_receiver.trajectory_reconstruction import trajectory_from_sam2_mask_track


@dataclass(frozen=True)
class LiveShotTrackingStageConfig:
    yolo_checkpoint_path: Path
    yolo_imgsz: int = 1280
    yolo_device: str = "0"
    yolo_det_conf: float = 0.05
    yolo_seed_conf: float = 0.8
    yolo_min_box_size: float = 10.0
    run_sam2: bool = True
    sam2_config: LiveCameraSam2Config | None = None


@dataclass(frozen=True)
class LiveShotSeedResult:
    success: bool
    failure_reason: str
    seed: dict[str, Any] | None


@dataclass(frozen=True)
class LiveShotTrackingStageOutput:
    session_dir: Path
    window_id: str
    result_path: Path
    output_dir: Path
    yolo_result: Any
    sam2_result: Any | None
    shot_result: ShotResult
    result_document: dict[str, Any]


def _frame_index_bounds_for_window(
    frame_metadata: list[dict[str, Any]],
    window: CompletedShotWindow,
) -> tuple[int, int]:
    start_index: int | None = None
    end_index: int | None = None
    for index, metadata in enumerate(frame_metadata):
        frame_seq = int(metadata.get("frameSeq", index))
        if start_index is None and frame_seq >= int(window.frame_seq_start):
            start_index = index
        if frame_seq <= int(window.frame_seq_end):
            end_index = index

    if start_index is None or end_index is None or end_index < start_index:
        raise RuntimeError(
            "Could not map completed shot window "
            f"{window.window_id} frameSeq {window.frame_seq_start}..{window.frame_seq_end} "
            "to decoded frame indices."
        )
    return start_index, end_index


def _trajectory_from_sam2_track(
    *,
    artifact: Any,
    window: CompletedShotWindow,
    lane_lock: LaneLockResult,
    sam2_result: Any,
) -> list[Any]:
    track_csv_path = Path(str(sam2_result.track_csv_path))
    return trajectory_from_sam2_mask_track(
        artifact=artifact,
        session_id=window.session_id,
        shot_id=window.shot_id,
        lane_lock=lane_lock,
        track_csv_path=track_csv_path,
        source_frame_idx_start=int(sam2_result.source_frame_idx_start),
        window_end_frame_seq=int(window.frame_seq_end),
    )


def _build_shot_result(
    *,
    artifact: Any,
    window: CompletedShotWindow,
    yolo_result: Any,
    sam2_result: Any | None,
) -> ShotResult:
    tracking_source = "camera_sam2"
    tracked_frames = int(sam2_result.tracked_frames) if sam2_result is not None else 0
    trajectory = []
    failure_reason = ""

    lane_lock = load_lane_lock_result_for_request(artifact.root_dir, window.lane_lock_request_id)
    if not yolo_result.success:
        failure_reason = str(yolo_result.failure_reason or "yolo_detection_failed")
    elif not window.lane_lock_request_id:
        failure_reason = "shot_boundary_lane_lock_request_missing"
    elif lane_lock is None:
        failure_reason = "shot_boundary_lane_lock_result_missing"
    elif sam2_result is None:
        failure_reason = "camera_sam2_track_missing"
    elif not sam2_result.success:
        failure_reason = str(sam2_result.failure_reason or "sam2_tracking_failed")
    else:
        try:
            trajectory = _trajectory_from_sam2_track(
                artifact=artifact,
                window=window,
                lane_lock=lane_lock,
                sam2_result=sam2_result,
            )
        except Exception as exc:
            failure_reason = f"lane_projection_failed:{exc}"

    if not failure_reason and not trajectory:
        failure_reason = "empty_lane_space_trajectory"

    average_projection_confidence = (
        sum(float(point.projection_confidence) for point in trajectory) / len(trajectory)
        if trajectory
        else 0.0
    )
    summary = ShotTrackingSummary(
        source=tracking_source,
        yolo_success=bool(yolo_result.success),
        sam2_success=bool(sam2_result.success) if sam2_result is not None else False,
        tracked_frames=tracked_frames,
        trajectory_points=len(trajectory),
        average_projection_confidence=average_projection_confidence,
    )

    return ShotResult(
        schema_version=SHOT_RESULT_SCHEMA_VERSION,
        session_id=window.session_id,
        shot_id=window.shot_id,
        window_id=window.window_id,
        success=not bool(failure_reason),
        failure_reason=failure_reason,
        lane_lock_request_id=lane_lock.request_id if lane_lock is not None else "",
        source_frame_range=SourceFrameRange(start=int(window.frame_seq_start), end=int(window.frame_seq_end)),
        tracking_summary=summary,
        trajectory=trajectory,
    )


def _camera_sam2_result_path_candidates(session_dir: Path, window: CompletedShotWindow) -> list[Path]:
    root = session_dir / "analysis_live_pipeline" / "camera_sam2"
    return [
        root / window.window_id / "camera_sam2_result.json",
        root / f"shot_{window.frame_seq_start}_{window.frame_seq_end}" / "camera_sam2_result.json",
        root / f"shot_{window.frame_seq_start}" / "camera_sam2_result.json",
    ]


def _load_camera_sam2_result_for_window(
    session_dir: Path,
    window: CompletedShotWindow,
) -> LiveCameraSam2TrackResult | None:
    for path in _camera_sam2_result_path_candidates(session_dir, window):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        return LiveCameraSam2TrackResult.from_dict(payload)
    return None


def _seed_result_from_camera_sam2(
    sam2_result: LiveCameraSam2TrackResult | None,
) -> LiveShotSeedResult:
    if sam2_result is None:
        return LiveShotSeedResult(success=False, failure_reason="camera_sam2_track_missing", seed=None)
    if not isinstance(sam2_result.seed, dict):
        return LiveShotSeedResult(success=False, failure_reason="camera_sam2_seed_missing", seed=None)
    return LiveShotSeedResult(success=True, failure_reason="", seed=dict(sam2_result.seed))


def run_live_shot_tracking_stage(
    session_dir: Path | str,
    window: CompletedShotWindow,
    config: LiveShotTrackingStageConfig,
    output_dir: Path | None = None,
) -> LiveShotTrackingStageOutput:
    from laptop_receiver.local_clip_artifact import load_local_clip_artifact

    artifact = load_local_clip_artifact(session_dir)
    frame_idx_start, frame_idx_end = _frame_index_bounds_for_window(artifact.frame_metadata, window)

    resolved_output_dir = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else artifact.root_dir / "analysis_shot_tracking" / window.window_id
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    (resolved_output_dir / "shot_window.json").write_text(
        json.dumps(window.to_dict(), indent=2),
        encoding="utf-8",
    )

    if not bool(config.run_sam2):
        raise RuntimeError("Live shot tracking requires camera SAM2; YOLO-only shot results are disabled.")

    sam2_result = _load_camera_sam2_result_for_window(artifact.root_dir, window)
    yolo_result = _seed_result_from_camera_sam2(sam2_result)

    shot_result = _build_shot_result(
        artifact=artifact,
        window=window,
        yolo_result=yolo_result,
        sam2_result=sam2_result,
    )

    result_document = {
        "kind": "live_shot_tracking_stage_result",
        "sessionDir": str(artifact.root_dir),
        "videoPath": str(artifact.video_path),
        "window": window.to_dict(),
        "frameIdxStart": frame_idx_start,
        "frameIdxEnd": frame_idx_end,
        "yolo": asdict(yolo_result),
        "sam2": asdict(sam2_result) if sam2_result is not None else None,
        "shotResult": shot_result.to_dict(),
        "trackingSuccess": bool(yolo_result.success and sam2_result is not None and sam2_result.success),
        "success": bool(shot_result.success),
    }
    result_path = resolved_output_dir / "shot_result.json"
    result_path.write_text(json.dumps(shot_result.to_dict(), indent=2), encoding="utf-8")

    return LiveShotTrackingStageOutput(
        session_dir=artifact.root_dir,
        window_id=window.window_id,
        result_path=result_path,
        output_dir=resolved_output_dir,
        yolo_result=yolo_result,
        sam2_result=sam2_result,
        shot_result=shot_result,
        result_document=result_document,
    )
