from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

try:
    from .oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from .oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
    from .sam2_bowling_bridge import parse_track_csv
except ImportError:
    from oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
    from sam2_bowling_bridge import parse_track_csv


DEFAULT_CHECKPOINT = (
    DEFAULT_INPUT_ROOT.parent
    / "yolo_hillclimb"
    / "20260329_165618"
    / "training_runs"
    / "e02_yolo11s_img1280_lightaug"
    / "weights"
    / "best.pt"
)
DEFAULT_OUTPUT_ROOT = DEFAULT_INPUT_ROOT.parent / "yolo_eval"


def _timestamp_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0.0 else 0.0


def _draw_box(image, box, color, label):
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(image, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def _run_dirs(input_root: Path, review_doc: dict[str, Any]) -> list[Path]:
    return [
        run_dir
        for run_dir in list_run_dirs(input_root)
        if (get_review_for_run(review_doc, run_dir.name) or {}).get("status") == "accepted"
        and (run_dir / "analysis_oracle" / "sam2" / "track.csv").exists()
    ]


def _load_run_name_filter(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {str(value) for value in payload}
    if isinstance(payload, dict):
        values = payload.get("runs")
        if isinstance(values, list):
            return {str(value) for value in values}
    raise ValueError(f"Unsupported run-names file format: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the YOLO seed detector against oracle bowling runs.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--reviews-path", type=Path, default=DEFAULT_ORACLE_REVIEW_PATH)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-tag", default=_timestamp_tag())
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--device", default="0")
    parser.add_argument("--run-names-file", type=Path, default=None, help="Optional JSON file containing a list of run names to evaluate.")
    parser.add_argument("--det-conf", type=float, default=0.05, help="Detector confidence floor for collecting candidates.")
    parser.add_argument("--success-conf", type=float, default=0.25, help="Confidence threshold for a successful seed.")
    parser.add_argument("--success-iou", type=float, default=0.25, help="IoU threshold versus the oracle box.")
    parser.add_argument("--max-frame-after-seed", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.checkpoint.exists():
        raise SystemExit(f"Checkpoint not found: {args.checkpoint}")

    review_doc = load_oracle_reviews(args.reviews_path.resolve())
    run_dirs = _run_dirs(args.input_root.resolve(), review_doc)
    if args.run_names_file is not None:
        allowed = _load_run_name_filter(args.run_names_file.resolve())
        run_dirs = [run_dir for run_dir in run_dirs if run_dir.name in allowed]
    if not run_dirs:
        raise SystemExit("No accepted oracle runs found for evaluation.")

    from ultralytics import YOLO

    model = YOLO(str(args.checkpoint.resolve()))
    run_output_root = args.output_root.resolve() / args.run_tag
    run_output_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "run_tag": args.run_tag,
        "checkpoint": str(args.checkpoint.resolve()),
        "run_count": len(run_dirs),
        "success_conf": float(args.success_conf),
        "success_iou": float(args.success_iou),
        "max_frame_after_seed": int(args.max_frame_after_seed),
        "runs": [],
    }

    success_count = 0
    for run_dir in run_dirs:
        manual_seed = _load_json(run_dir / "analysis_oracle" / "manual_seed.json")
        track_samples = parse_track_csv(run_dir / "analysis_oracle" / "sam2" / "track.csv")
        oracle_by_frame = {
            int(sample["frame_idx"]): [
                float(sample["bbox_x1"]),
                float(sample["bbox_y1"]),
                float(sample["bbox_x2"]),
                float(sample["bbox_y2"]),
            ]
            for sample in track_samples
        }
        seed_frame = int(manual_seed["frame_idx"])
        eval_end = min(max(oracle_by_frame.keys()), seed_frame + int(args.max_frame_after_seed))
        frame_paths = [
            run_dir / "raw" / "frames" / f"{frame_idx:06d}.jpg"
            for frame_idx in range(0, eval_end + 1)
            if (run_dir / "raw" / "frames" / f"{frame_idx:06d}.jpg").exists() and frame_idx in oracle_by_frame
        ]

        best_frame_idx = None
        best_iou = -1.0
        best_conf = 0.0
        best_pred_box: list[float] | None = None
        first_good_frame = None
        first_good_conf = None
        first_good_iou = None
        first_good_box: list[float] | None = None

        results = model.predict(
            source=[str(path) for path in frame_paths],
            imgsz=int(args.imgsz),
            conf=float(args.det_conf),
            device=args.device,
            verbose=False,
        )
        for frame_path, result in zip(frame_paths, results):
            frame_idx = int(frame_path.stem)
            oracle_box = oracle_by_frame.get(frame_idx)
            if oracle_box is None:
                continue
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            best_idx = int(confs.argmax())
            pred_box = [float(v) for v in xyxy[best_idx]]
            conf = float(confs[best_idx])
            iou = _iou(pred_box, oracle_box)

            if iou > best_iou:
                best_iou = iou
                best_conf = conf
                best_frame_idx = frame_idx
                best_pred_box = pred_box

            if first_good_frame is None and conf >= float(args.success_conf) and iou >= float(args.success_iou):
                first_good_frame = frame_idx
                first_good_conf = conf
                first_good_iou = iou
                first_good_box = pred_box

        chosen_frame = first_good_frame if first_good_frame is not None else best_frame_idx
        chosen_pred_box = first_good_box if first_good_frame is not None else best_pred_box

        preview_path = ""
        if chosen_frame is not None and chosen_pred_box is not None:
            image_path = run_dir / "raw" / "frames" / f"{int(chosen_frame):06d}.jpg"
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is not None:
                oracle_box = oracle_by_frame[int(chosen_frame)]
                _draw_box(image, oracle_box, (0, 255, 0), "oracle")
                _draw_box(image, chosen_pred_box, (255, 255, 0), "yolo")
                _draw_box(image, manual_seed["box"], (0, 140, 255), f"manual_seed f{seed_frame}")
                preview_dir = run_output_root / run_dir.name
                preview_dir.mkdir(parents=True, exist_ok=True)
                preview_path = str(preview_dir / "yolo_seed_eval.jpg")
                cv2.imwrite(preview_path, image)

        success = first_good_frame is not None
        if success:
            success_count += 1

        summary["runs"].append(
            {
                "run_name": run_dir.name,
                "seed_frame": seed_frame,
                "eval_end_frame": eval_end,
                "success": success,
                "first_good_frame": first_good_frame,
                "delay_from_seed": (first_good_frame - seed_frame) if first_good_frame is not None else None,
                "first_good_conf": first_good_conf,
                "first_good_iou": first_good_iou,
                "best_frame": best_frame_idx,
                "best_conf": best_conf if best_frame_idx is not None else None,
                "best_iou": best_iou if best_frame_idx is not None else None,
                "preview_path": preview_path,
            }
        )

    summary["success_count"] = success_count
    summary["failure_count"] = len(summary["runs"]) - success_count
    summary["success_rate"] = success_count / len(summary["runs"]) if summary["runs"] else 0.0

    summary_path = run_output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[yolo-eval] summary -> {summary_path}")
    print(f"[yolo-eval] success_rate={summary['success_rate']:.3f} ({success_count}/{len(summary['runs'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
