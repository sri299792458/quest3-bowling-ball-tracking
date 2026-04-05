from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .path_config import LAPTOP_PIPELINE_ROOT
except ImportError:
    from path_config import LAPTOP_PIPELINE_ROOT


DEFAULT_INPUT_ROOT = LAPTOP_PIPELINE_ROOT / "runs" / "bowling_tests"
DEFAULT_MANUAL_SEEDS_PATH = DEFAULT_INPUT_ROOT / "manual_seeds.json"


def list_run_dirs(input_root: Path) -> list[Path]:
    run_dirs: list[Path] = []
    for path in sorted(input_root.iterdir()):
        if not path.is_dir():
            continue
        if (path / "raw" / "frames").exists():
            run_dirs.append(path)
    return run_dirs


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    frame_idx = entry.get("frame_idx")
    box = entry.get("box")
    if frame_idx is None or box is None:
        return None
    if not isinstance(box, list) or len(box) != 4:
        return None
    x1, y1, x2, y2 = (float(value) for value in box)
    if x2 <= x1 or y2 <= y1:
        return None
    normalized = dict(entry)
    normalized["frame_idx"] = int(frame_idx)
    normalized["box"] = [x1, y1, x2, y2]
    points = entry.get("points")
    point_labels = entry.get("point_labels")
    if points is not None:
        if not isinstance(points, list):
            return None
        normalized_points: list[list[float]] = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                return None
            px, py = (float(value) for value in point)
            normalized_points.append([px, py])
        normalized["points"] = normalized_points
    if point_labels is not None:
        if not isinstance(point_labels, list):
            return None
        normalized_labels = [int(value) for value in point_labels]
        if "points" in normalized and len(normalized_labels) != len(normalized["points"]):
            return None
        normalized["point_labels"] = normalized_labels
    return normalized


def load_manual_seeds(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "description": "One manual SAM2 seed prompt per run. Box is [x1, y1, x2, y2] in source-frame pixels. Optional points use [x, y] pixel coordinates.",
            "updated_at": utc_now_iso(),
            "runs": {},
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else {}
    normalized_runs: dict[str, Any] = {}
    if isinstance(runs, dict):
        for run_name, entry in runs.items():
            normalized = _normalize_entry(entry)
            if normalized is not None:
                normalized_runs[str(run_name)] = normalized

    result = {
        "version": int(payload.get("version", 1)) if isinstance(payload, dict) else 1,
        "description": payload.get("description", "") if isinstance(payload, dict) else "",
        "updated_at": payload.get("updated_at", utc_now_iso()) if isinstance(payload, dict) else utc_now_iso(),
        "runs": normalized_runs,
    }
    if not result["description"]:
        result["description"] = "One manual SAM2 seed prompt per run. Box is [x1, y1, x2, y2] in source-frame pixels. Optional points use [x, y] pixel coordinates."
    return result


def save_manual_seeds(path: Path, document: dict[str, Any]) -> None:
    payload = {
        "version": int(document.get("version", 1)),
        "description": document.get("description") or "One manual SAM2 seed prompt per run. Box is [x1, y1, x2, y2] in source-frame pixels. Optional points use [x, y] pixel coordinates.",
        "updated_at": utc_now_iso(),
        "runs": document.get("runs", {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_seed_for_run(document: dict[str, Any], run_name: str) -> dict[str, Any] | None:
    runs = document.get("runs", {})
    if not isinstance(runs, dict):
        return None
    entry = runs.get(run_name)
    return _normalize_entry(entry)


def set_seed_for_run(document: dict[str, Any], run_name: str, frame_idx: int, box: list[float], **extra: Any) -> dict[str, Any]:
    normalized_box = [float(value) for value in box]
    entry = {
        "frame_idx": int(frame_idx),
        "box": normalized_box,
        "source": "manual",
        "updated_at": utc_now_iso(),
    }
    entry.update(extra)
    document.setdefault("runs", {})[run_name] = entry
    return entry


def load_suggested_seed(run_dir: Path) -> dict[str, Any] | None:
    candidates = [
        run_dir / "analysis" / "seed.json",
        run_dir / "analysis_lanefirst_debug" / "seed.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalized = _normalize_entry(payload)
        if normalized is None:
            continue
        normalized["source"] = "suggested"
        normalized["source_path"] = str(path)
        return normalized
    return None
