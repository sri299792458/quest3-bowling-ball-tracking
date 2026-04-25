from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from laptop_receiver.live_shot_boundaries import CompletedShotWindow


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

    result_document = {
        "kind": "live_shot_tracking_stage_result",
        "sessionDir": str(artifact.root_dir),
        "videoPath": str(artifact.video_path),
        "window": window.to_dict(),
        "frameIdxStart": frame_idx_start,
        "frameIdxEnd": frame_idx_end,
        "yolo": asdict(yolo_result),
        "sam2": asdict(sam2_result) if sam2_result is not None else None,
        "success": bool(yolo_result.success and (sam2_result is None or sam2_result.success)),
    }
    result_path = resolved_output_dir / "shot_tracking_result.json"
    result_path.write_text(json.dumps(result_document, indent=2), encoding="utf-8")

    return LiveShotTrackingStageOutput(
        session_dir=artifact.root_dir,
        window_id=window.window_id,
        result_path=result_path,
        output_dir=resolved_output_dir,
        yolo_result=yolo_result,
        sam2_result=sam2_result,
        result_document=result_document,
    )
