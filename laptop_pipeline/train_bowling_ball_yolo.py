from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .path_config import LAPTOP_PIPELINE_ROOT
except ImportError:
    from path_config import LAPTOP_PIPELINE_ROOT


DEFAULT_DATASET_YAML = LAPTOP_PIPELINE_ROOT / "datasets" / "bowling_ball_oracle_yolo" / "dataset.yaml"
DEFAULT_EXPORT_SUMMARY = LAPTOP_PIPELINE_ROOT / "datasets" / "bowling_ball_oracle_yolo" / "export_summary.json"
DEFAULT_PROJECT_DIR = LAPTOP_PIPELINE_ROOT / "runs" / "yolo_training"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO detector to initialize SAM2 on bowling-ball release clips.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET_YAML)
    parser.add_argument("--export-summary", type=Path, default=DEFAULT_EXPORT_SUMMARY)
    parser.add_argument("--model", default="yolo11s.pt")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--name", default="bowling_ball_yolo11s_img1280_v1")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--patience", type=int, default=25)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--time-hours", type=float, default=0.0, help="Optional fixed wall-clock training budget in hours.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--exist-ok", action="store_true")
    parser.add_argument("--optimizer", default="auto")
    parser.add_argument("--hsv-h", type=float, default=0.0)
    parser.add_argument("--hsv-s", type=float, default=0.0)
    parser.add_argument("--hsv-v", type=float, default=0.0)
    parser.add_argument("--degrees", type=float, default=0.0)
    parser.add_argument("--translate", type=float, default=0.0)
    parser.add_argument("--scale", type=float, default=0.0)
    parser.add_argument("--shear", type=float, default=0.0)
    parser.add_argument("--perspective", type=float, default=0.0)
    parser.add_argument("--fliplr", type=float, default=0.0)
    parser.add_argument("--flipud", type=float, default=0.0)
    parser.add_argument("--mosaic", type=float, default=0.0)
    parser.add_argument("--mixup", type=float, default=0.0)
    parser.add_argument("--copy-paste", type=float, default=0.0)
    parser.add_argument("--erasing", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved training config without starting training.")
    return parser.parse_args()


def build_train_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs = {
        "data": str(args.data.resolve()),
        "epochs": int(args.epochs),
        "patience": int(args.patience),
        "imgsz": int(args.imgsz),
        "batch": int(args.batch),
        "device": args.device,
        "workers": int(args.workers),
        "project": str(args.project.resolve()),
        "name": args.name,
        "pretrained": True,
        "optimizer": args.optimizer,
        "seed": int(args.seed),
        "deterministic": True,
        "single_cls": True,
        "cache": bool(args.cache),
        "plots": True,
        "save": True,
        "save_period": 10,
        "exist_ok": bool(args.exist_ok),
        "resume": bool(args.resume),
        "hsv_h": float(args.hsv_h),
        "hsv_s": float(args.hsv_s),
        "hsv_v": float(args.hsv_v),
        "degrees": float(args.degrees),
        "translate": float(args.translate),
        "scale": float(args.scale),
        "shear": float(args.shear),
        "perspective": float(args.perspective),
        "fliplr": float(args.fliplr),
        "flipud": float(args.flipud),
        "mosaic": float(args.mosaic),
        "mixup": float(args.mixup),
        "copy_paste": float(args.copy_paste),
        "erasing": float(args.erasing),
        "close_mosaic": 0,
    }
    if float(args.time_hours) > 0.0:
        kwargs["time"] = float(args.time_hours)
    return kwargs


def main() -> int:
    args = parse_args()
    if not args.data.exists():
        raise SystemExit(f"Dataset YAML does not exist: {args.data}")
    if args.export_summary.exists():
        export_summary = _load_json(args.export_summary)
        print(
            f"[train] dataset runs={export_summary.get('run_count')} "
            f"positives={export_summary.get('total_positive_images')} "
            f"negatives={export_summary.get('total_negative_images')}"
        )

    train_kwargs = build_train_kwargs(args)
    print(f"[train] model={args.model}")
    print(f"[train] project={args.project.resolve()}")
    print(f"[train] name={args.name}")
    print("[train] kwargs:")
    print(json.dumps(train_kwargs, indent=2))

    if args.dry_run:
        return 0

    from ultralytics import YOLO

    model = YOLO(args.model)
    results = model.train(**train_kwargs)
    print(f"[train] done -> {results.save_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
