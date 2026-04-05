from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from pathlib import Path
from typing import Any

try:
    from .oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from .oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
    from .path_config import LAPTOP_PIPELINE_ROOT
except ImportError:
    from oracle_review_utils import DEFAULT_ORACLE_REVIEW_PATH, get_review_for_run, load_oracle_reviews
    from oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
    from path_config import LAPTOP_PIPELINE_ROOT


DEFAULT_OUTPUT_ROOT = LAPTOP_PIPELINE_ROOT / "datasets" / "bowling_ball_oracle_yolo"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_statuses(text: str) -> set[str]:
    values = {value.strip().lower() for value in text.split(",") if value.strip()}
    if not values:
        raise ValueError("At least one review status must be provided.")
    return values


def _load_track_samples(track_path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with track_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("present") != "1":
                continue
            x1 = float(row["bbox_x1"])
            y1 = float(row["bbox_y1"])
            x2 = float(row["bbox_x2"])
            y2 = float(row["bbox_y2"])
            samples.append(
                {
                    "frame_idx": int(row["frame_idx"]),
                    "bbox": [x1, y1, x2, y2],
                    "width": x2 - x1,
                    "height": y2 - y1,
                }
            )
    return samples


def _to_yolo_box(box: list[float], frame_width: int, frame_height: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    center_x = x1 + width * 0.5
    center_y = y1 + height * 0.5
    return (
        center_x / float(frame_width),
        center_y / float(frame_height),
        width / float(frame_width),
        height / float(frame_height),
    )


def _write_label(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _build_split_lookup(run_names: list[str], val_ratio: float, seed: int) -> dict[str, str]:
    shuffled = list(run_names)
    random.Random(seed).shuffle(shuffled)
    val_count = int(round(len(shuffled) * val_ratio))
    if 0 < len(shuffled) and val_ratio > 0.0 and val_count == 0:
        val_count = 1
    val_names = set(shuffled[:val_count])
    return {run_name: ("val" if run_name in val_names else "train") for run_name in run_names}


def _load_split_lookup(path: Path, known_run_names: set[str]) -> dict[str, str]:
    payload = _load_json(path)
    split_lookup: dict[str, str] = {}
    seen: set[str] = set()
    for split_name in ("train", "val", "test"):
        raw_names = payload.get(split_name, [])
        if not isinstance(raw_names, list):
            raise ValueError(f"Split '{split_name}' must be a list in {path}")
        for run_name in raw_names:
            run_name = str(run_name)
            if run_name not in known_run_names:
                raise ValueError(f"Run '{run_name}' from {path} was not found in the exportable run set.")
            if run_name in seen:
                raise ValueError(f"Run '{run_name}' appears more than once in {path}.")
            seen.add(run_name)
            split_lookup[run_name] = split_name
    missing = sorted(known_run_names - seen)
    if missing:
        raise ValueError(f"Split file {path} is missing runs: {missing}")
    return split_lookup


def _copy_frame(frame_path: Path, image_out: Path) -> None:
    image_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(frame_path, image_out)


def _dataset_file_stem(run_name: str, frame_idx: int) -> str:
    return f"{run_name}_f{frame_idx:06d}"


def parse_args():
    parser = argparse.ArgumentParser(description="Export reviewed oracle SAM2 tracks to a YOLO-style detector dataset.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--reviews-path", type=Path, default=DEFAULT_ORACLE_REVIEW_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--statuses", default="accepted", help="Comma-separated review statuses to include. Default: accepted")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--positive-frame-step", type=int, default=2)
    parser.add_argument("--max-positive-frames-per-run", type=int, default=24)
    parser.add_argument("--negative-pre-roll-count", type=int, default=4, help="How many empty pre-seed frames to export per run.")
    parser.add_argument("--negative-frame-step", type=int, default=2)
    parser.add_argument("--min-box-size", type=float, default=10.0, help="Skip very tiny boxes below this width or height in pixels.")
    parser.add_argument("--split-runs-file", type=Path, default=None, help="Optional JSON file with explicit train/val/test run lists.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    included_statuses = _parse_statuses(args.statuses)
    review_doc = load_oracle_reviews(args.reviews_path.resolve())

    run_dirs = []
    for run_dir in list_run_dirs(input_root):
        review = get_review_for_run(review_doc, run_dir.name) or {"status": "pending"}
        if review.get("status") not in included_statuses:
            continue
        if not (run_dir / "oracle_tracking_result.json").exists():
            continue
        run_dirs.append(run_dir)
    if not run_dirs:
        raise SystemExit(f"No runs matched statuses={sorted(included_statuses)} under {input_root}")

    if output_root.exists() and args.overwrite:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (output_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    run_names = [run_dir.name for run_dir in run_dirs]
    if args.split_runs_file is not None:
        split_lookup = _load_split_lookup(args.split_runs_file.resolve(), set(run_names))
    else:
        split_lookup = _build_split_lookup(run_names, float(args.val_ratio), int(args.seed))
    manifest_runs: list[dict[str, Any]] = []
    total_positive = 0
    total_negative = 0

    for run_dir in run_dirs:
        split_name = split_lookup[run_dir.name]
        oracle_result = _load_json(run_dir / "oracle_tracking_result.json")
        if not oracle_result.get("success"):
            continue

        seed = _load_json(run_dir / "analysis_oracle" / "manual_seed.json")
        session_config = _load_json(run_dir / "session_config.json")
        frame_width = int(session_config.get("width") or 0)
        frame_height = int(session_config.get("height") or 0)
        if frame_width <= 0 or frame_height <= 0:
            manifest = _load_json(run_dir / "raw" / "manifest.json")
            frame_width = int(manifest.get("frame_width") or 0)
            frame_height = int(manifest.get("frame_height") or 0)
        if frame_width <= 0 or frame_height <= 0:
            raise RuntimeError(f"Could not determine frame size for {run_dir.name}")

        frames_dir = run_dir / "raw" / "frames"
        track_path = run_dir / "analysis_oracle" / "sam2" / "track.csv"
        samples = _load_track_samples(track_path)
        usable_samples = [
            sample
            for sample in samples
            if sample["width"] >= float(args.min_box_size) and sample["height"] >= float(args.min_box_size)
        ]
        positive_samples = usable_samples[:: max(1, int(args.positive_frame_step))]
        if args.max_positive_frames_per_run > 0:
            positive_samples = positive_samples[: int(args.max_positive_frames_per_run)]

        positive_count = 0
        negative_count = 0
        exported_frames: list[int] = []

        for sample in positive_samples:
            frame_idx = int(sample["frame_idx"])
            frame_path = frames_dir / f"{frame_idx:06d}.jpg"
            if not frame_path.exists():
                continue
            stem = _dataset_file_stem(run_dir.name, frame_idx)
            image_out = output_root / "images" / split_name / f"{stem}.jpg"
            label_out = output_root / "labels" / split_name / f"{stem}.txt"
            yolo_x, yolo_y, yolo_w, yolo_h = _to_yolo_box(sample["bbox"], frame_width, frame_height)
            _copy_frame(frame_path, image_out)
            _write_label(label_out, [f"0 {yolo_x:.6f} {yolo_y:.6f} {yolo_w:.6f} {yolo_h:.6f}"])
            positive_count += 1
            exported_frames.append(frame_idx)

        seed_frame = int(seed["frame_idx"])
        for offset in range(int(args.negative_pre_roll_count), 0, -1):
            frame_idx = seed_frame - offset * max(1, int(args.negative_frame_step))
            if frame_idx < 0 or frame_idx in exported_frames:
                continue
            frame_path = frames_dir / f"{frame_idx:06d}.jpg"
            if not frame_path.exists():
                continue
            stem = _dataset_file_stem(run_dir.name, frame_idx)
            image_out = output_root / "images" / split_name / f"{stem}.jpg"
            label_out = output_root / "labels" / split_name / f"{stem}.txt"
            _copy_frame(frame_path, image_out)
            _write_label(label_out, [])
            negative_count += 1

        total_positive += positive_count
        total_negative += negative_count
        manifest_runs.append(
            {
                "run_name": run_dir.name,
                "split": split_name,
                "seed_frame": seed_frame,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "tracked_frames": int(oracle_result.get("tracked_frames") or 0),
                "review_status": (get_review_for_run(review_doc, run_dir.name) or {}).get("status", "pending"),
            }
        )

    dataset_yaml = "\n".join(
        [
            f"path: {output_root.as_posix()}",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            "names:",
            "  0: bowling_ball",
            "",
        ]
    )
    (output_root / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")

    summary = {
        "input_root": str(input_root),
        "reviews_path": str(args.reviews_path.resolve()),
        "included_statuses": sorted(included_statuses),
        "output_root": str(output_root),
        "val_ratio": float(args.val_ratio),
        "seed": int(args.seed),
        "split_runs_file": str(args.split_runs_file.resolve()) if args.split_runs_file is not None else "",
        "positive_frame_step": int(args.positive_frame_step),
        "max_positive_frames_per_run": int(args.max_positive_frames_per_run),
        "negative_pre_roll_count": int(args.negative_pre_roll_count),
        "negative_frame_step": int(args.negative_frame_step),
        "min_box_size": float(args.min_box_size),
        "run_count": len(manifest_runs),
        "total_positive_images": total_positive,
        "total_negative_images": total_negative,
        "runs": manifest_runs,
    }
    (output_root / "export_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"dataset.yaml -> {output_root / 'dataset.yaml'}")
    print(f"export_summary.json -> {output_root / 'export_summary.json'}")
    print(f"runs={len(manifest_runs)} positives={total_positive} negatives={total_negative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
