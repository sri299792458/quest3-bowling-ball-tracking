from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import cv2

try:
    from .batch_track_recorded_runs import load_run_metadata
    from .oracle_seed_utils import (
        DEFAULT_INPUT_ROOT,
        DEFAULT_MANUAL_SEEDS_PATH,
        get_seed_for_run,
        list_run_dirs,
        load_manual_seeds,
    )
    from .sam2_bowling_bridge import parse_summary, parse_track_csv
    from .warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames
except ImportError:
    from batch_track_recorded_runs import load_run_metadata
    from oracle_seed_utils import (
        DEFAULT_INPUT_ROOT,
        DEFAULT_MANUAL_SEEDS_PATH,
        get_seed_for_run,
        list_run_dirs,
        load_manual_seeds,
    )
    from sam2_bowling_bridge import parse_summary, parse_track_csv
    from warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames


def reset_oracle_outputs(run_dir: Path) -> None:
    analysis_dir = run_dir / "analysis_oracle"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
    for path in (
        run_dir / "oracle_tracking_result.json",
        run_dir / "oracle_warm_sam2_summary.json",
    ):
        if path.exists():
            path.unlink()


def build_oracle_result(run_dir: Path, seed: dict[str, Any] | None, failure_reason: str) -> dict[str, Any]:
    analysis_dir = run_dir / "analysis_oracle"
    sam2_dir = analysis_dir / "sam2"
    track_path = sam2_dir / "track.csv"
    summary_path = sam2_dir / "summary.txt"
    preview_path = sam2_dir / "preview.mp4"
    path_samples = parse_track_csv(track_path) if track_path.exists() else []
    summary = parse_summary(summary_path) if summary_path.exists() else {}
    return {
        "kind": "oracle_shot_result",
        "success": len(path_samples) > 0,
        "shot_id": run_dir.name,
        "raw_frames_dir": str(run_dir / "raw" / "frames"),
        "analysis_dir": str(analysis_dir),
        "preview_path": str(preview_path) if preview_path.exists() else "",
        "failure_reason": failure_reason,
        "seed": seed,
        "summary": summary,
        "path_samples": path_samples,
        "tracked_frames": len(path_samples),
        "first_frame": path_samples[0]["frame_idx"] if path_samples else None,
        "last_frame": path_samples[-1]["frame_idx"] if path_samples else None,
        "review_status": "unreviewed",
    }


def write_seed_preview(frames_dir: Path, seed: dict[str, Any], output_path: Path) -> None:
    frame_path = frames_dir / f"{int(seed['frame_idx']):06d}.jpg"
    image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read seed frame: {frame_path}")
    x1, y1, x2, y2 = (int(round(value)) for value in seed["box"])
    cv2.rectangle(image, (x1, y1), (x2, y2), (255, 255, 0), 2)
    cv2.putText(image, "manual oracle seed", (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 0), 2, cv2.LINE_AA)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image)


def write_raw_preview(frames_dir: Path, preview_path: Path, preview_fps: float, label: str) -> None:
    writer = None
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        for _, frame_rgb in iter_source_frames(str(frames_dir)):
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
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


def analyze_run_with_manual_seed(
    run_dir: Path,
    manual_seed_document: dict[str, Any],
    warm_tracker: WarmSam2Tracker,
    overwrite: bool,
) -> dict[str, Any]:
    metadata = load_run_metadata(run_dir)
    frames_dir = metadata["frames_dir"]
    analysis_dir = run_dir / "analysis_oracle"
    sam2_dir = analysis_dir / "sam2"
    preview_path = sam2_dir / "preview.mp4"
    result_path = run_dir / "oracle_tracking_result.json"

    if not frames_dir.exists():
        result = {
            "kind": "oracle_shot_result",
            "success": False,
            "shot_id": run_dir.name,
            "failure_reason": "frames_dir_missing",
            "analysis_dir": str(analysis_dir),
            "raw_frames_dir": str(frames_dir),
            "preview_path": "",
        }
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    seed = get_seed_for_run(manual_seed_document, run_dir.name)
    if seed is None:
        result = build_oracle_result(run_dir, None, "manual_seed_missing")
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    if not overwrite and preview_path.exists() and (sam2_dir / "track.csv").exists():
        return json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else build_oracle_result(run_dir, seed, "")

    reset_oracle_outputs(run_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "manual_seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")
    write_seed_preview(frames_dir, seed, analysis_dir / "manual_seed_preview.jpg")

    try:
        warm_summary = warm_tracker.track_from_seed(
            str(frames_dir.resolve()),
            seed,
            sam2_dir,
            no_preview=False,
            frame_limit=0,
            preview_fps=float(metadata["preview_fps"]),
        )
    except Exception as exc:
        write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "ORACLE TRACK ERROR")
        result = build_oracle_result(run_dir, seed, "sam2_exception")
        result["error_message"] = f"{type(exc).__name__}: {exc}"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    (run_dir / "oracle_warm_sam2_summary.json").write_text(json.dumps(warm_summary, indent=2), encoding="utf-8")
    result = build_oracle_result(run_dir, seed, "")
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="Run warm SAM2 over recorded bowling runs using manual oracle seeds.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--seeds-path", type=Path, default=DEFAULT_MANUAL_SEEDS_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run-name", default="", help="Optional single run directory name to process.")
    parser.add_argument(
        "--no-vos-optimized",
        action="store_false",
        dest="vos_optimized",
        help="Disable the VOS-optimized SAM2 build path.",
    )
    parser.set_defaults(vos_optimized=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    seeds_path = args.seeds_path.resolve()
    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")

    manual_seed_document = load_manual_seeds(seeds_path)
    run_dirs = list_run_dirs(input_root)
    if args.run_name:
        run_dirs = [run_dir for run_dir in run_dirs if run_dir.name == args.run_name]
    if args.limit > 0:
        run_dirs = run_dirs[: args.limit]
    if not run_dirs:
        raise SystemExit("No matching runs found.")

    warm_tracker = WarmSam2Tracker(WarmSam2Config(vos_optimized=bool(args.vos_optimized)))
    batch_started = time.perf_counter()
    results: list[dict[str, Any]] = []

    for index, run_dir in enumerate(run_dirs, start=1):
        print(f"[oracle-batch] {index}/{len(run_dirs)} {run_dir.name}")
        started = time.perf_counter()
        try:
            result = analyze_run_with_manual_seed(run_dir, manual_seed_document, warm_tracker, overwrite=args.overwrite)
        except Exception as exc:
            result = {
                "kind": "oracle_shot_result",
                "success": False,
                "shot_id": run_dir.name,
                "failure_reason": "oracle_analysis_exception",
                "error_message": f"{type(exc).__name__}: {exc}",
                "analysis_dir": str(run_dir / "analysis_oracle"),
                "raw_frames_dir": str(run_dir / "raw" / "frames"),
                "preview_path": "",
            }
        elapsed = time.perf_counter() - started
        result["batch_elapsed_seconds"] = round(elapsed, 3)
        results.append(result)
        status = "success" if result.get("success") else "failure"
        failure = result.get("failure_reason") or "-"
        print(f"[oracle-batch] done {status=} tracked_frames={result.get('tracked_frames', 0)} failure={failure}")

    success_count = sum(1 for result in results if result.get("success"))
    summary = {
        "input_root": str(input_root),
        "seeds_path": str(seeds_path),
        "vos_optimized": bool(args.vos_optimized),
        "run_count": len(results),
        "success_count": success_count,
        "failure_count": len(results) - success_count,
        "elapsed_seconds": round(time.perf_counter() - batch_started, 3),
        "results": results,
    }
    summary_path = input_root / "oracle_batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[oracle-batch] summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
