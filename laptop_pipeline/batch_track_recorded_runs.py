from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import cv2

try:
    from .online_classical_seed import OnlineClassicalSeedConfig, OnlineClassicalSeedDetector
    from .path_config import LAPTOP_PIPELINE_ROOT
    from .sam2_bowling_bridge import parse_summary, parse_track_csv
    from .warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames
except ImportError:
    from online_classical_seed import OnlineClassicalSeedConfig, OnlineClassicalSeedDetector
    from path_config import LAPTOP_PIPELINE_ROOT
    from sam2_bowling_bridge import parse_summary, parse_track_csv
    from warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames


DEFAULT_INPUT_ROOT = LAPTOP_PIPELINE_ROOT / "runs" / "bowling_tests"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_metadata(run_dir: Path) -> dict[str, Any]:
    manifest = _load_json(run_dir / "raw" / "manifest.json")
    session_config = _load_json(run_dir / "session_config.json")

    capture_summary_path = run_dir / "raw" / "capture_summary.json"
    capture_summary = _load_json(capture_summary_path) if capture_summary_path.exists() else {}

    effective_fps = float(capture_summary.get("effective_fps") or 0.0)
    preview_fps = effective_fps if effective_fps > 0.0 else float(manifest.get("fps") or session_config.get("target_send_fps") or 30.0)

    return {
        "frames_dir": run_dir / "raw" / "frames",
        "frame_width": int(manifest.get("frame_width") or session_config.get("width") or 0),
        "frame_height": int(manifest.get("frame_height") or session_config.get("height") or 0),
        "preview_fps": preview_fps,
        "session_config": session_config,
        "manifest": manifest,
        "capture_summary": capture_summary,
    }


def build_seed_config(profile: str) -> OnlineClassicalSeedConfig:
    normalized = profile.strip().lower()
    if normalized == "default":
        return OnlineClassicalSeedConfig()
    if normalized == "recorded_alley":
        return OnlineClassicalSeedConfig(
            min_start_center_y_ratio=0.25,
            min_track_travel=30.0,
            min_mean_score=0.45,
            max_track_gap=10,
        )
    raise ValueError(f"Unknown seed profile: {profile}")


def reset_analysis_outputs(run_dir: Path) -> None:
    analysis_dir = run_dir / "analysis"
    sam2_dir = analysis_dir / "sam2"
    if sam2_dir.exists():
        shutil.rmtree(sam2_dir)

    for path in (
        analysis_dir / "seed.json",
        analysis_dir / "track.json",
        analysis_dir / "detections.csv",
        analysis_dir / "pipeline_summary.txt",
        analysis_dir / "best_detection.jpg",
        analysis_dir / "lane_hypotheses.json",
        analysis_dir / "lane_overlay.jpg",
        run_dir / "warm_sam2_summary.json",
        run_dir / "offline_tracking_result.json",
    ):
        if path.exists():
            path.unlink()


def write_raw_preview(frames_dir: Path, preview_path: Path, preview_fps: float, label: str) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    try:
        for frame_idx, frame_rgb in iter_source_frames(str(frames_dir)):
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            if label:
                cv2.putText(frame_bgr, label, (24, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
            if writer is None:
                height, width = frame_bgr.shape[:2]
                writer = cv2.VideoWriter(str(preview_path), cv2.VideoWriter_fourcc(*"mp4v"), max(preview_fps, 1.0), (width, height))
                if not writer.isOpened():
                    raise RuntimeError(f"Could not open preview writer for {preview_path}")
            writer.write(frame_bgr)
    finally:
        if writer is not None:
            writer.release()


def write_exception_artifacts(run_dir: Path, frames_dir: Path, preview_path: Path, preview_fps: float, label: str, error_message: str) -> None:
    write_raw_preview(frames_dir, preview_path, preview_fps, label)
    error_path = run_dir / "analysis" / "sam2_error.txt"
    error_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.write_text(error_message + "\n", encoding="utf-8")


def build_offline_result(run_dir: Path, seed: dict[str, Any] | None, failure_reason: str) -> dict[str, Any]:
    analysis_dir = run_dir / "analysis"
    sam2_dir = analysis_dir / "sam2"
    track_path = sam2_dir / "track.csv"
    summary_path = sam2_dir / "summary.txt"
    preview_path = sam2_dir / "preview.mp4"
    path_samples = parse_track_csv(track_path) if track_path.exists() else []
    summary = parse_summary(summary_path) if summary_path.exists() else {}

    return {
        "kind": "shot_result",
        "success": len(path_samples) > 0,
        "shot_id": run_dir.name,
        "raw_frames_dir": str(run_dir / "raw" / "frames"),
        "analysis_dir": str(analysis_dir),
        "warm_sam2_summary": str(run_dir / "warm_sam2_summary.json") if (run_dir / "warm_sam2_summary.json").exists() else "",
        "preview_path": str(preview_path) if preview_path.exists() else "",
        "failure_reason": failure_reason,
        "seed": seed,
        "summary": summary,
        "path_samples": path_samples,
        "tracked_frames": len(path_samples),
        "first_frame": path_samples[0]["frame_idx"] if path_samples else None,
        "last_frame": path_samples[-1]["frame_idx"] if path_samples else None,
    }


def analyze_run(run_dir: Path, warm_tracker: WarmSam2Tracker, seed_config: OnlineClassicalSeedConfig, overwrite: bool) -> dict[str, Any]:
    metadata = load_run_metadata(run_dir)
    frames_dir = metadata["frames_dir"]
    analysis_dir = run_dir / "analysis"
    sam2_dir = analysis_dir / "sam2"
    preview_path = sam2_dir / "preview.mp4"
    result_path = run_dir / "offline_tracking_result.json"

    if not frames_dir.exists():
        result = {
            "kind": "shot_result",
            "success": False,
            "shot_id": run_dir.name,
            "failure_reason": "frames_dir_missing",
            "analysis_dir": str(analysis_dir),
            "raw_frames_dir": str(frames_dir),
            "preview_path": "",
        }
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    if not overwrite and preview_path.exists() and (sam2_dir / "track.csv").exists():
        return _load_json(result_path) if result_path.exists() else build_offline_result(run_dir, None, "")

    reset_analysis_outputs(run_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    detector = OnlineClassicalSeedDetector(
        frame_width=int(metadata["frame_width"]),
        frame_height=int(metadata["frame_height"]),
        config=seed_config,
    )

    for frame_idx, frame_rgb in iter_source_frames(str(frames_dir)):
        detector.process_frame(frame_idx, frame_rgb)

    seed = detector.write_outputs(analysis_dir)
    if seed is None:
        write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "NO SEED")
        result = build_offline_result(run_dir, None, "no_seed_found")
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    try:
        warm_summary = warm_tracker.track_from_seed(
            str(frames_dir),
            seed,
            sam2_dir,
            no_preview=False,
            frame_limit=0,
            preview_fps=float(metadata["preview_fps"]),
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        write_exception_artifacts(
            run_dir,
            frames_dir,
            preview_path,
            float(metadata["preview_fps"]),
            "TRACK ERROR",
            error_message,
        )
        result = build_offline_result(run_dir, seed, "sam2_exception")
        result["error_message"] = error_message
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    (run_dir / "warm_sam2_summary.json").write_text(json.dumps(warm_summary, indent=2), encoding="utf-8")

    result = build_offline_result(run_dir, seed, "")
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run classical seeding + warm SAM2 tracking over recorded bowling runs.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT, help="Folder containing recorded shot run directories.")
    parser.add_argument("--overwrite", action="store_true", help="Recompute tracking outputs even if preview.mp4 already exists.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for how many runs to process.")
    parser.add_argument(
        "--seed-profile",
        choices=("default", "recorded_alley"),
        default="recorded_alley",
        help="Classical seed profile to use before warm SAM2.",
    )
    parser.add_argument(
        "--no-vos-optimized",
        action="store_false",
        dest="vos_optimized",
        help="Disable the VOS-optimized SAM2 build path.",
    )
    parser.set_defaults(vos_optimized=True)
    args = parser.parse_args()

    input_root = args.input_root.resolve()
    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")

    run_dirs = sorted([path for path in input_root.iterdir() if path.is_dir()])
    if args.limit > 0:
        run_dirs = run_dirs[: args.limit]

    seed_config = build_seed_config(args.seed_profile)
    warm_tracker = WarmSam2Tracker(WarmSam2Config(vos_optimized=bool(args.vos_optimized)))
    batch_started = time.perf_counter()
    results: list[dict[str, Any]] = []

    for index, run_dir in enumerate(run_dirs, start=1):
        print(f"[batch] {index}/{len(run_dirs)} {run_dir.name}")
        started = time.perf_counter()
        try:
            result = analyze_run(run_dir, warm_tracker, seed_config, overwrite=args.overwrite)
        except Exception as exc:
            result = {
                "kind": "shot_result",
                "success": False,
                "shot_id": run_dir.name,
                "failure_reason": "analysis_exception",
                "error_message": f"{type(exc).__name__}: {exc}",
                "analysis_dir": str(run_dir / "analysis"),
                "raw_frames_dir": str(run_dir / "raw" / "frames"),
                "preview_path": "",
            }
            write_exception_artifacts(
                run_dir,
                run_dir / "raw" / "frames",
                run_dir / "analysis" / "sam2" / "preview.mp4",
                15.0,
                "TRACK ERROR",
                result["error_message"],
            )
            result["preview_path"] = str(run_dir / "analysis" / "sam2" / "preview.mp4")
            (run_dir / "offline_tracking_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["batch_elapsed_seconds"] = round(time.perf_counter() - started, 3)
        results.append(result)
        print(
            f"[batch] done success={result.get('success', False)} "
            f"tracked_frames={result.get('tracked_frames', 0)} "
            f"failure={result.get('failure_reason', '') or '-'}"
        )

    summary = {
        "input_root": str(input_root),
        "seed_profile": args.seed_profile,
        "vos_optimized": bool(args.vos_optimized),
        "run_count": len(run_dirs),
        "success_count": sum(1 for result in results if result.get("success")),
        "failure_count": sum(1 for result in results if not result.get("success")),
        "elapsed_seconds": round(time.perf_counter() - batch_started, 3),
        "results": results,
    }
    summary_path = input_root / "batch_tracking_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[batch] summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
