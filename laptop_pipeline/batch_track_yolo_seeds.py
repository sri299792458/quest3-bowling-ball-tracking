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
    from .evaluate_yolo_seed_detector import DEFAULT_CHECKPOINT
    from .oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from .path_config import LAPTOP_PIPELINE_ROOT
    from .sam2_bowling_bridge import parse_summary, parse_track_csv
    from .warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames
except ImportError:
    from batch_track_recorded_runs import load_run_metadata
    from evaluate_yolo_seed_detector import DEFAULT_CHECKPOINT
    from oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from path_config import LAPTOP_PIPELINE_ROOT
    from sam2_bowling_bridge import parse_summary, parse_track_csv
    from warm_sam2_tracker import WarmSam2Config, WarmSam2Tracker, iter_source_frames


DEFAULT_INPUT_ROOT = LAPTOP_PIPELINE_ROOT / "runs" / "bowling_tests"
DEFAULT_EVAL_SUMMARY = LAPTOP_PIPELINE_ROOT / "runs" / "yolo_eval" / "20260329_180853" / "summary.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _draw_box(image, box, color, label):
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(image, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def reset_yolo_outputs(run_dir: Path) -> None:
    analysis_dir = run_dir / "analysis_yolo_seed"
    if analysis_dir.exists():
        shutil.rmtree(analysis_dir)
    for path in (
        run_dir / "yolo_warm_sam2_summary.json",
        run_dir / "yolo_tracking_result.json",
    ):
        if path.exists():
            path.unlink()


def write_raw_preview(frames_dir: Path, preview_path: Path, preview_fps: float, label: str) -> None:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    try:
        for _, frame_rgb in iter_source_frames(str(frames_dir)):
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


def build_result(run_dir: Path, seed: dict[str, Any] | None, failure_reason: str) -> dict[str, Any]:
    analysis_dir = run_dir / "analysis_yolo_seed"
    sam2_dir = analysis_dir / "sam2"
    track_path = sam2_dir / "track.csv"
    summary_path = sam2_dir / "summary.txt"
    preview_path = sam2_dir / "preview.mp4"
    path_samples = parse_track_csv(track_path) if track_path.exists() else []
    summary = parse_summary(summary_path) if summary_path.exists() else {}
    return {
        "kind": "yolo_seed_shot_result",
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
    }


def _select_eval_runs(input_root: Path, review_doc: dict[str, Any], eval_summary: dict[str, Any], run_name: str) -> list[tuple[Path, dict[str, Any]]]:
    run_map = {run["run_name"]: run for run in eval_summary.get("runs", []) if run.get("success")}
    selected: list[tuple[Path, dict[str, Any]]] = []
    for run_dir in sorted(input_root.iterdir()):
        if not run_dir.is_dir() or not (run_dir / "raw" / "frames").exists():
            continue
        if run_name and run_dir.name != run_name:
            continue
        review = get_review_for_run(review_doc, run_dir.name) or {}
        if review.get("status") != "accepted":
            continue
        run_eval = run_map.get(run_dir.name)
        if run_eval is None:
            continue
        selected.append((run_dir, run_eval))
    return selected


def _select_reviewed_runs(input_root: Path, review_doc: dict[str, Any], run_name: str) -> list[Path]:
    selected: list[Path] = []
    for run_dir in sorted(input_root.iterdir()):
        if not run_dir.is_dir() or not (run_dir / "raw" / "frames").exists():
            continue
        if run_name and run_dir.name != run_name:
            continue
        review = get_review_for_run(review_doc, run_dir.name) or {}
        if review.get("status") != "accepted":
            continue
        selected.append(run_dir)
    return selected


def detect_seed_for_frame(model, image_path: Path, frame_idx: int, imgsz: int, device: str, det_conf: float) -> dict[str, Any] | None:
    results = model.predict(
        source=[str(image_path)],
        imgsz=int(imgsz),
        conf=float(det_conf),
        device=device,
        verbose=False,
    )
    if not results:
        return None
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None
    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    best_idx = int(confs.argmax())
    return {
        "frame_idx": int(frame_idx),
        "box": [float(v) for v in xyxy[best_idx]],
        "source": "yolo",
        "detector_confidence": float(confs[best_idx]),
    }


def detect_seed_causally(
    model,
    frames_dir: Path,
    imgsz: int,
    device: str,
    det_conf: float,
    seed_conf: float,
    min_box_size: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.perf_counter()
    searched_frames = 0
    best_candidate: dict[str, Any] | None = None
    for image_path in sorted(frames_dir.glob("*.jpg"), key=lambda path: int(path.stem)):
        frame_idx = int(image_path.stem)
        searched_frames += 1
        candidate = detect_seed_for_frame(model, image_path, frame_idx, imgsz=imgsz, device=device, det_conf=det_conf)
        if candidate is None:
            continue
        x1, y1, x2, y2 = candidate["box"]
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        candidate["box_width"] = width
        candidate["box_height"] = height
        if best_candidate is None or float(candidate["detector_confidence"]) > float(best_candidate["detector_confidence"]):
            best_candidate = dict(candidate)
        if width >= float(min_box_size) and height >= float(min_box_size) and float(candidate["detector_confidence"]) >= float(seed_conf):
            candidate["seed_mode"] = "causal_first_confident"
            return candidate, {
                "search_mode": "causal",
                "search_seconds": round(time.perf_counter() - started, 3),
                "searched_frames": searched_frames,
                "seed_conf_threshold": float(seed_conf),
                "det_conf_floor": float(det_conf),
                "min_box_size": float(min_box_size),
                "best_candidate_conf": float(best_candidate["detector_confidence"]) if best_candidate is not None else None,
                "best_candidate_frame": int(best_candidate["frame_idx"]) if best_candidate is not None else None,
            }
    return None, {
        "search_mode": "causal",
        "search_seconds": round(time.perf_counter() - started, 3),
        "searched_frames": searched_frames,
        "seed_conf_threshold": float(seed_conf),
        "det_conf_floor": float(det_conf),
        "min_box_size": float(min_box_size),
        "best_candidate_conf": float(best_candidate["detector_confidence"]) if best_candidate is not None else None,
        "best_candidate_frame": int(best_candidate["frame_idx"]) if best_candidate is not None else None,
    }


def analyze_run_with_yolo_seed(
    run_dir: Path,
    run_eval: dict[str, Any] | None,
    model,
    warm_tracker: WarmSam2Tracker,
    overwrite: bool,
    imgsz: int,
    device: str,
    det_conf: float,
    seed_mode: str,
    seed_conf: float,
    min_box_size: float,
    checkpoint_path: Path,
    eval_summary_path: Path | None,
) -> dict[str, Any]:
    metadata = load_run_metadata(run_dir)
    frames_dir = metadata["frames_dir"]
    analysis_dir = run_dir / "analysis_yolo_seed"
    sam2_dir = analysis_dir / "sam2"
    preview_path = sam2_dir / "preview.mp4"
    result_path = run_dir / "yolo_tracking_result.json"

    if not frames_dir.exists():
        result = {
            "kind": "yolo_seed_shot_result",
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
        return _load_json(result_path) if result_path.exists() else build_result(run_dir, None, "")

    search_info: dict[str, Any] = {}
    if seed_mode == "eval_summary":
        chosen_frame = run_eval.get("first_good_frame") if run_eval is not None else None
        if chosen_frame is None and run_eval is not None:
            chosen_frame = run_eval.get("best_frame")
        if chosen_frame is None:
            write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "NO YOLO SEED")
            result = build_result(run_dir, None, "yolo_seed_missing")
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result

        image_path = frames_dir / f"{int(chosen_frame):06d}.jpg"
        if not image_path.exists():
            write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "YOLO SEED FRAME MISSING")
            result = build_result(run_dir, None, "yolo_seed_frame_missing")
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result
        seed = detect_seed_for_frame(model, image_path, int(chosen_frame), imgsz=imgsz, device=device, det_conf=det_conf)
        search_info = {
            "search_mode": "eval_summary",
            "search_seconds": 0.0,
            "searched_frames": 1,
            "seed_conf_threshold": float(seed_conf),
            "det_conf_floor": float(det_conf),
            "min_box_size": float(min_box_size),
        }
    else:
        seed, search_info = detect_seed_causally(
            model,
            frames_dir,
            imgsz=imgsz,
            device=device,
            det_conf=det_conf,
            seed_conf=seed_conf,
            min_box_size=min_box_size,
        )

    if seed is None:
        write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "YOLO DETECT FAIL")
        result = build_result(run_dir, None, "yolo_detection_failed")
        result["seed_search"] = search_info
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    seed["checkpoint"] = str(checkpoint_path)
    seed["seed_mode"] = seed_mode
    seed["seed_search"] = search_info
    if eval_summary_path is not None:
        seed["eval_summary_path"] = str(eval_summary_path)
    if run_eval is not None:
        seed["eval_reference"] = {
            "first_good_frame": run_eval.get("first_good_frame"),
            "best_frame": run_eval.get("best_frame"),
            "best_iou": run_eval.get("best_iou"),
            "best_conf": run_eval.get("best_conf"),
        }

    reset_yolo_outputs(run_dir)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "yolo_seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    chosen_frame = int(seed["frame_idx"])
    image_path = frames_dir / f"{chosen_frame:06d}.jpg"
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is not None:
        _draw_box(image, seed["box"], (255, 255, 0), f"yolo seed f{chosen_frame}")
        seed_preview_path = analysis_dir / "yolo_seed_preview.jpg"
        seed_preview_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(seed_preview_path), image)

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
        write_raw_preview(frames_dir, preview_path, float(metadata["preview_fps"]), "YOLO TRACK ERROR")
        result = build_result(run_dir, seed, "sam2_exception")
        result["error_message"] = f"{type(exc).__name__}: {exc}"
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    (run_dir / "yolo_warm_sam2_summary.json").write_text(json.dumps(warm_summary, indent=2), encoding="utf-8")
    result = build_result(run_dir, seed, "")
    result["seed_search"] = search_info
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run warm SAM2 over bowling runs using YOLO-selected seed boxes.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--reviews-path", type=Path, default=DEFAULT_ORACLE_REVIEW_PATH)
    parser.add_argument("--eval-summary", type=Path, default=DEFAULT_EVAL_SUMMARY)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--device", default="0")
    parser.add_argument("--det-conf", type=float, default=0.05)
    parser.add_argument("--seed-conf", type=float, default=0.8, help="Confidence threshold for causal first-lock seeding.")
    parser.add_argument("--min-box-size", type=float, default=10.0, help="Minimum width/height in pixels for a causal seed candidate.")
    parser.add_argument("--seed-mode", choices=["causal", "eval_summary"], default="causal")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run-name", default="")
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
    reviews_path = args.reviews_path.resolve()
    checkpoint_path = args.checkpoint.resolve()
    if not input_root.exists():
        raise SystemExit(f"Input root does not exist: {input_root}")
    if not checkpoint_path.exists():
        raise SystemExit(f"YOLO checkpoint does not exist: {checkpoint_path}")

    review_doc = load_oracle_reviews(reviews_path)
    eval_summary_path: Path | None = None
    run_items: list[tuple[Path, dict[str, Any] | None]]
    if args.seed_mode == "eval_summary":
        eval_summary_path = args.eval_summary.resolve()
        if not eval_summary_path.exists():
            raise SystemExit(f"YOLO eval summary does not exist: {eval_summary_path}")
        eval_summary = _load_json(eval_summary_path)
        run_items = _select_eval_runs(input_root, review_doc, eval_summary, args.run_name)
        if not run_items:
            raise SystemExit("No matching accepted runs found in the YOLO eval summary.")
    else:
        run_items = [(run_dir, None) for run_dir in _select_reviewed_runs(input_root, review_doc, args.run_name)]
        if not run_items:
            raise SystemExit("No matching accepted runs found for causal YOLO seeding.")
    if args.limit > 0:
        run_items = run_items[: args.limit]

    from ultralytics import YOLO

    model = YOLO(str(checkpoint_path))
    warm_tracker = WarmSam2Tracker(WarmSam2Config(vos_optimized=bool(args.vos_optimized)))

    batch_started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for index, (run_dir, run_eval) in enumerate(run_items, start=1):
        print(f"[yolo-batch] {index}/{len(run_items)} {run_dir.name}")
        started = time.perf_counter()
        try:
            result = analyze_run_with_yolo_seed(
                run_dir,
                run_eval,
                model,
                warm_tracker,
                overwrite=bool(args.overwrite),
                imgsz=int(args.imgsz),
                device=str(args.device),
                det_conf=float(args.det_conf),
                seed_mode=str(args.seed_mode),
                seed_conf=float(args.seed_conf),
                min_box_size=float(args.min_box_size),
                checkpoint_path=checkpoint_path,
                eval_summary_path=eval_summary_path,
            )
        except Exception as exc:
            result = {
                "kind": "yolo_seed_shot_result",
                "success": False,
                "shot_id": run_dir.name,
                "failure_reason": "yolo_seed_batch_exception",
                "error_message": f"{type(exc).__name__}: {exc}",
                "analysis_dir": str(run_dir / "analysis_yolo_seed"),
                "raw_frames_dir": str(run_dir / "raw" / "frames"),
                "preview_path": "",
            }
        elapsed = time.perf_counter() - started
        result["batch_elapsed_seconds"] = round(elapsed, 3)
        results.append(result)
        status = "success" if result.get("success") else "failure"
        failure = result.get("failure_reason") or "-"
        print(f"[yolo-batch] done {status=} tracked_frames={result.get('tracked_frames', 0)} failure={failure}")

    success_count = sum(1 for result in results if result.get("success"))
    summary = {
        "input_root": str(input_root),
        "reviews_path": str(reviews_path),
        "seed_mode": str(args.seed_mode),
        "eval_summary": str(eval_summary_path) if eval_summary_path is not None else "",
        "checkpoint": str(checkpoint_path),
        "seed_conf": float(args.seed_conf),
        "det_conf": float(args.det_conf),
        "min_box_size": float(args.min_box_size),
        "vos_optimized": bool(args.vos_optimized),
        "run_count": len(results),
        "success_count": success_count,
        "failure_count": len(results) - success_count,
        "elapsed_seconds": round(time.perf_counter() - batch_started, 3),
        "results": results,
    }
    summary_path = input_root / "yolo_batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[yolo-batch] summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
