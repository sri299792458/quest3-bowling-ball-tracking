from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from laptop_receiver.lane_geometry import bottom_center_from_box, project_ball_image_point_to_lane_space
from laptop_receiver.lane_lock_types import CameraIntrinsics, FrameCameraState, LaneLockResult, SourceFrameRange
from laptop_receiver.live_lane_lock_results import load_lane_lock_result_for_request
from laptop_receiver.live_shot_boundaries import CompletedShotWindow
from laptop_receiver.shot_result_types import SHOT_RESULT_SCHEMA_VERSION, ShotResult, ShotTrackingSummary


@dataclass(frozen=True)
class LiveShotTrackingStageConfig:
    yolo_checkpoint_path: Path
    yolo_imgsz: int = 1280
    yolo_device: str = "0"
    yolo_det_conf: float = 0.05
    yolo_seed_conf: float = 0.8
    yolo_min_box_size: float = 10.0
    run_sam2: bool = False
    sam2_config: Any = None
    sam2_preview: bool = True
    sam2_frame_limit: int = 0


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


def _frame_state_for_index(frame_metadata: list[dict[str, Any]], frame_index: int) -> FrameCameraState:
    if frame_index < 0 or frame_index >= len(frame_metadata):
        raise RuntimeError(f"Frame index {frame_index} is outside metadata range 0..{len(frame_metadata) - 1}.")
    return FrameCameraState.from_frame_metadata(frame_metadata[frame_index])


def _trajectory_from_yolo_seed(
    *,
    artifact: Any,
    window: CompletedShotWindow,
    lane_lock: LaneLockResult,
    seed: dict[str, Any],
) -> list[Any]:
    frame_index = int(seed["frame_idx"])
    image_point_px = bottom_center_from_box(seed["box"])
    frame_state = _frame_state_for_index(artifact.frame_metadata, frame_index)
    return [
        project_ball_image_point_to_lane_space(
            session_id=window.session_id,
            shot_id=window.shot_id,
            image_point_px=image_point_px,
            frame_camera_state=frame_state,
            intrinsics=CameraIntrinsics.from_session_metadata(artifact.session_metadata),
            lane_lock=lane_lock,
            point_definition="yolo_bbox_bottom_contact_proxy",
        )
    ]


def _trajectory_from_sam2_track(
    *,
    artifact: Any,
    window: CompletedShotWindow,
    lane_lock: LaneLockResult,
    sam2_result: Any,
) -> list[Any]:
    track_csv_path = Path(str(sam2_result.track_csv_path))
    if not track_csv_path.exists():
        raise RuntimeError(f"SAM2 track CSV does not exist: {track_csv_path}")

    intrinsics = CameraIntrinsics.from_session_metadata(artifact.session_metadata)
    trajectory: list[Any] = []
    with track_csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row.get("present") or 0) != 1:
                continue

            local_frame_idx = int(row["frame_idx"])
            source_frame_idx = local_frame_idx + int(sam2_result.source_frame_idx_start)
            frame_state = _frame_state_for_index(artifact.frame_metadata, source_frame_idx)
            image_point_px = bottom_center_from_box(
                [
                    float(row["bbox_x1"]),
                    float(row["bbox_y1"]),
                    float(row["bbox_x2"]),
                    float(row["bbox_y2"]),
                ]
            )
            trajectory.append(
                project_ball_image_point_to_lane_space(
                    session_id=window.session_id,
                    shot_id=window.shot_id,
                    image_point_px=image_point_px,
                    frame_camera_state=frame_state,
                    intrinsics=intrinsics,
                    lane_lock=lane_lock,
                    point_definition="sam2_bbox_bottom_contact_proxy",
                )
            )
    return trajectory


def _build_shot_result(
    *,
    artifact: Any,
    window: CompletedShotWindow,
    yolo_result: Any,
    sam2_result: Any | None,
) -> ShotResult:
    tracking_source = "sam2" if sam2_result is not None else "yolo_seed"
    tracked_frames = int(sam2_result.tracked_frames) if sam2_result is not None else (1 if yolo_result.success else 0)
    trajectory = []
    failure_reason = ""

    lane_lock = load_lane_lock_result_for_request(artifact.root_dir, window.lane_lock_request_id)
    if not yolo_result.success:
        failure_reason = str(yolo_result.failure_reason or "yolo_detection_failed")
    elif not window.lane_lock_request_id:
        failure_reason = "shot_boundary_lane_lock_request_missing"
    elif lane_lock is None:
        failure_reason = "shot_boundary_lane_lock_result_missing"
    elif sam2_result is not None and not sam2_result.success:
        failure_reason = str(sam2_result.failure_reason or "sam2_tracking_failed")
    else:
        try:
            if sam2_result is not None:
                trajectory = _trajectory_from_sam2_track(
                    artifact=artifact,
                    window=window,
                    lane_lock=lane_lock,
                    sam2_result=sam2_result,
                )
            else:
                trajectory = _trajectory_from_yolo_seed(
                    artifact=artifact,
                    window=window,
                    lane_lock=lane_lock,
                    seed=yolo_result.seed,
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


def run_live_shot_tracking_stage(
    session_dir: Path | str,
    window: CompletedShotWindow,
    config: LiveShotTrackingStageConfig,
    output_dir: Path | None = None,
) -> LiveShotTrackingStageOutput:
    from laptop_receiver.local_clip_artifact import load_local_clip_artifact
    from laptop_receiver.standalone_sam2_tracking import run_sam2_on_artifact
    from laptop_receiver.standalone_yolo_seed import analyze_artifact_with_yolo_seed

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

    yolo_dir = resolved_output_dir / "yolo_seed"
    yolo_result = analyze_artifact_with_yolo_seed(
        artifact.root_dir,
        checkpoint_path=config.yolo_checkpoint_path,
        output_root=yolo_dir,
        imgsz=int(config.yolo_imgsz),
        device=str(config.yolo_device),
        det_conf=float(config.yolo_det_conf),
        seed_conf=float(config.yolo_seed_conf),
        min_box_size=float(config.yolo_min_box_size),
        frame_seq_start=int(window.frame_seq_start),
        frame_seq_end=int(window.frame_seq_end),
    )

    sam2_result = None
    if bool(config.run_sam2) and bool(yolo_result.success):
        sam2_result = run_sam2_on_artifact(
            artifact.root_dir,
            seed_path=yolo_dir / "yolo_seed.json",
            output_dir=resolved_output_dir / "sam2_track",
            preview=bool(config.sam2_preview),
            frame_limit=int(config.sam2_frame_limit),
            config=config.sam2_config,
            source_frame_idx_start=frame_idx_start,
            source_frame_idx_end=frame_idx_end,
        )

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
        "trackingSuccess": bool(yolo_result.success and (sam2_result is None or sam2_result.success)),
        "success": bool(shot_result.success),
    }
    result_path = resolved_output_dir / "shot_tracking_result.json"
    result_path.write_text(json.dumps(result_document, indent=2), encoding="utf-8")
    (resolved_output_dir / "shot_result.json").write_text(json.dumps(shot_result.to_dict(), indent=2), encoding="utf-8")

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
