from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import cv2

from laptop_receiver.local_clip_artifact import load_local_clip_artifact
from laptop_receiver.standalone_warm_sam2_tracker import StandaloneWarmSam2Config, StandaloneWarmSam2Tracker


@dataclass(frozen=True)
class StandaloneSam2TrackResult:
    kind: str
    success: bool
    artifact_dir: str
    analysis_dir: str
    seed_path: str
    sam2_dir: str
    preview_path: str
    failure_reason: str
    seed: dict[str, Any] | None
    summary: dict[str, str]
    track_csv_path: str
    tracked_frames: int
    first_frame: int | None
    last_frame: int | None
    timing: dict[str, float | int | None]


def parse_summary(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def _default_seed_path(artifact_dir: Path) -> Path:
    return artifact_dir / "analysis_yolo_seed" / "yolo_seed.json"


def _materialize_artifact_frames(artifact_video_path: Path, output_frames_dir: Path) -> Path:
    output_frames_dir.mkdir(parents=True, exist_ok=True)
    existing_frames = sorted(output_frames_dir.glob("*.jpg"), key=lambda path: int(path.stem))
    if existing_frames:
        return output_frames_dir

    capture = cv2.VideoCapture(str(artifact_video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open artifact video for frame extraction: {artifact_video_path}")

    frame_index = 0
    try:
        while True:
            ok, frame_bgr = capture.read()
            if not ok:
                break
            frame_path = output_frames_dir / f"{frame_index:06d}.jpg"
            if not cv2.imwrite(str(frame_path), frame_bgr):
                raise RuntimeError(f"Could not write extracted frame: {frame_path}")
            frame_index += 1
    finally:
        capture.release()

    if frame_index == 0:
        raise RuntimeError(f"No frames were extracted from artifact video: {artifact_video_path}")
    return output_frames_dir


def run_sam2_on_artifact(
    artifact_dir: Path | str,
    seed_path: Path | None = None,
    output_dir: Path | None = None,
    preview: bool = True,
    frame_limit: int = 0,
    config: StandaloneWarmSam2Config | None = None,
) -> StandaloneSam2TrackResult:
    artifact = load_local_clip_artifact(artifact_dir)
    resolved_seed_path = (seed_path or _default_seed_path(artifact.root_dir)).expanduser().resolve()
    if not resolved_seed_path.exists():
        raise RuntimeError(f"Standalone YOLO seed does not exist: {resolved_seed_path}")

    seed = json.loads(resolved_seed_path.read_text(encoding="utf-8"))
    analysis_dir = (output_dir.expanduser().resolve() if output_dir is not None else artifact.root_dir / "analysis_yolo_seed")
    analysis_dir.mkdir(parents=True, exist_ok=True)
    sam2_dir = analysis_dir / "sam2"
    sam2_dir.mkdir(parents=True, exist_ok=True)
    sam2_source_frames_dir = analysis_dir / "sam2_source_frames"
    source_path = _materialize_artifact_frames(artifact.video_path, sam2_source_frames_dir)

    tracker = StandaloneWarmSam2Tracker(config=config)
    warm_summary = tracker.track_from_seed(
        str(source_path),
        seed,
        sam2_dir,
        no_preview=not preview,
        frame_limit=int(frame_limit),
        preview_fps=float(artifact.video_info.fps or 30.0),
    )

    summary_path = Path(str(warm_summary["summary_path"]))
    track_csv_path = Path(str(warm_summary["track_csv"]))
    summary = parse_summary(summary_path) if summary_path.exists() else {}
    preview_path = sam2_dir / "preview.mp4"

    result = StandaloneSam2TrackResult(
        kind="standalone_sam2_track_result",
        success=bool(int(warm_summary.get("tracked_frames") or 0) > 0),
        artifact_dir=str(artifact.root_dir),
        analysis_dir=str(analysis_dir),
        seed_path=str(resolved_seed_path),
        sam2_dir=str(sam2_dir),
        preview_path=str(preview_path) if preview_path.exists() else "",
        failure_reason="" if int(warm_summary.get("tracked_frames") or 0) > 0 else "sam2_no_tracked_frames",
        seed=seed,
        summary=summary,
        track_csv_path=str(track_csv_path),
        tracked_frames=int(warm_summary.get("tracked_frames") or 0),
        first_frame=warm_summary.get("first_tracked_frame"),
        last_frame=warm_summary.get("last_tracked_frame"),
        timing={
            "build_seconds": float(warm_summary.get("build_seconds") or 0.0),
            "init_seconds": float(warm_summary.get("init_seconds") or 0.0),
            "propagate_seconds": float(warm_summary.get("propagate_seconds") or 0.0),
            "total_seconds": float(warm_summary.get("total_seconds") or 0.0),
        },
    )

    result_path = analysis_dir / "standalone_sam2_result.json"
    result_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return result
