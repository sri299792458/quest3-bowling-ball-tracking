from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

try:
    from .path_config import LAPTOP_PIPELINE_ROOT
    from .train_bowling_ball_yolo import DEFAULT_DATASET_YAML, DEFAULT_EXPORT_SUMMARY
except ImportError:
    from path_config import LAPTOP_PIPELINE_ROOT
    from training.train_bowling_ball_yolo import DEFAULT_DATASET_YAML, DEFAULT_EXPORT_SUMMARY


DEFAULT_ROOT = LAPTOP_PIPELINE_ROOT / "runs" / "yolo_hillclimb"


@dataclass(frozen=True)
class Experiment:
    slug: str
    description: str
    model: str
    imgsz: int
    batch: int
    augment: str
    kwargs: dict[str, Any]


def _timestamp_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _read_results_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _best_row(rows: list[dict[str, str]]) -> dict[str, str]:
    def score(row: dict[str, str]) -> tuple[float, float, float]:
        return (
            float(row.get("metrics/mAP50(B)", 0.0) or 0.0),
            float(row.get("metrics/recall(B)", 0.0) or 0.0),
            float(row.get("metrics/mAP50-95(B)", 0.0) or 0.0),
        )

    return max(rows, key=score)


def _build_experiments(time_hours: float) -> list[Experiment]:
    base_kwargs = {
        "epochs": 120,
        "patience": 25,
        "workers": 4,
        "device": "0",
        "seed": 1337,
    }
    return [
        Experiment(
            slug="e01_yolo11s_img1280_noaug",
            description="baseline yolo11s 1280 no augmentation",
            model="yolo11s.pt",
            imgsz=1280,
            batch=2,
            augment="none",
            kwargs={**base_kwargs},
        ),
        Experiment(
            slug="e02_yolo11s_img1280_lightaug",
            description="same model with only mild photometric and small geometric aug",
            model="yolo11s.pt",
            imgsz=1280,
            batch=2,
            augment="light",
            kwargs={
                **base_kwargs,
                "hsv_h": 0.01,
                "hsv_s": 0.35,
                "hsv_v": 0.25,
                "degrees": 1.0,
                "translate": 0.05,
                "scale": 0.15,
                "perspective": 0.0005,
            },
        ),
        Experiment(
            slug="e03_yolo11n_img1280_noaug",
            description="smaller yolo11n baseline at same resolution and no aug",
            model="yolo11n.pt",
            imgsz=1280,
            batch=2,
            augment="none",
            kwargs={**base_kwargs},
        ),
    ]


def _write_header(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\t".join(
            [
                "experiment",
                "model",
                "imgsz",
                "batch",
                "augment",
                "time_minutes",
                "best_epoch",
                "best_map50",
                "best_recall",
                "best_map50_95",
                "status",
                "description",
                "run_dir",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _append_result(path: Path, row: list[str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(row) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Small fixed-budget hill-climb for the bowling-ball YOLO initializer.")
    parser.add_argument("--run-tag", default=_timestamp_tag())
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET_YAML)
    parser.add_argument("--export-summary", type=Path, default=DEFAULT_EXPORT_SUMMARY)
    parser.add_argument("--time-hours", type=float, default=0.25, help="Fixed per-experiment wall-clock budget.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_root = args.root.resolve() / args.run_tag
    project_dir = run_root / "training_runs"
    results_tsv = run_root / "results.tsv"
    summary_json = run_root / "summary.json"
    experiments = _build_experiments(float(args.time_hours))
    _write_header(results_tsv)

    summary = {
        "run_tag": args.run_tag,
        "time_hours": float(args.time_hours),
        "dataset_yaml": str(args.data.resolve()),
        "export_summary": str(args.export_summary.resolve()),
        "experiments": [],
    }

    if args.dry_run:
        print(json.dumps(summary | {"experiments": [exp.__dict__ for exp in experiments]}, indent=2))
        return 0

    from ultralytics import YOLO

    for experiment in experiments:
        save_dir = project_dir / experiment.slug
        print(f"[hillclimb] starting {experiment.slug}: {experiment.description}")
        model = YOLO(experiment.model)
        train_kwargs = {
            "data": str(args.data.resolve()),
            "project": str(project_dir),
            "name": experiment.slug,
            "exist_ok": False,
            "pretrained": True,
            "optimizer": "auto",
            "seed": 1337,
            "deterministic": True,
            "single_cls": True,
            "cache": False,
            "plots": True,
            "save": True,
            "save_period": 10,
            "close_mosaic": 0,
            "hsv_h": 0.0,
            "hsv_s": 0.0,
            "hsv_v": 0.0,
            "degrees": 0.0,
            "translate": 0.0,
            "scale": 0.0,
            "perspective": 0.0,
            "fliplr": 0.0,
            "flipud": 0.0,
            "mosaic": 0.0,
            "mixup": 0.0,
            "copy_paste": 0.0,
            "erasing": 0.0,
            "shear": 0.0,
            "auto_augment": "none",
            "bgr": 0.0,
            "device": "0",
            "workers": 4,
            "imgsz": experiment.imgsz,
            "batch": experiment.batch,
            "time": float(args.time_hours),
        }
        train_kwargs.update(experiment.kwargs)
        started = time.perf_counter()
        model.train(**train_kwargs)
        elapsed_minutes = (time.perf_counter() - started) / 60.0

        results_csv = save_dir / "results.csv"
        if not results_csv.exists():
            raise RuntimeError(f"Missing results.csv for {experiment.slug}")
        rows = _read_results_csv(results_csv)
        if not rows:
            raise RuntimeError(f"Empty results.csv for {experiment.slug}")
        best = _best_row(rows)
        entry = {
            "experiment": experiment.slug,
            "model": experiment.model,
            "imgsz": experiment.imgsz,
            "batch": experiment.batch,
            "augment": experiment.augment,
            "time_minutes": round(elapsed_minutes, 2),
            "best_epoch": int(float(best["epoch"])),
            "best_map50": float(best["metrics/mAP50(B)"]),
            "best_recall": float(best["metrics/recall(B)"]),
            "best_map50_95": float(best["metrics/mAP50-95(B)"]),
            "description": experiment.description,
            "run_dir": str(save_dir),
        }
        summary["experiments"].append(entry)
        _append_result(
            results_tsv,
            [
                entry["experiment"],
                entry["model"],
                str(entry["imgsz"]),
                str(entry["batch"]),
                entry["augment"],
                f"{entry['time_minutes']:.2f}",
                str(entry["best_epoch"]),
                f"{entry['best_map50']:.6f}",
                f"{entry['best_recall']:.6f}",
                f"{entry['best_map50_95']:.6f}",
                "done",
                entry["description"],
                entry["run_dir"],
            ],
        )
        summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(
            f"[hillclimb] done {experiment.slug} "
            f"mAP50={entry['best_map50']:.4f} "
            f"recall={entry['best_recall']:.4f} "
            f"mAP50-95={entry['best_map50_95']:.4f}"
        )

    print(f"[hillclimb] summary -> {summary_json}")
    print(f"[hillclimb] results -> {results_tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
