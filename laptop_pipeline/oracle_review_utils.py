from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .oracle_seed_utils import DEFAULT_INPUT_ROOT
except ImportError:
    from oracle_seed_utils import DEFAULT_INPUT_ROOT


DEFAULT_ORACLE_REVIEW_PATH = DEFAULT_INPUT_ROOT / "oracle_reviews.json"
VALID_REVIEW_STATUSES = {"accepted", "rejected", "needs_work", "pending"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_oracle_reviews(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "description": "Review decisions for oracle SAM2 runs.",
            "updated_at": utc_now_iso(),
            "runs": {},
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs") if isinstance(payload, dict) else {}
    normalized_runs: dict[str, Any] = {}
    if isinstance(runs, dict):
        for run_name, entry in runs.items():
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "pending")).strip().lower()
            if status not in VALID_REVIEW_STATUSES:
                status = "pending"
            normalized = dict(entry)
            normalized["status"] = status
            normalized_runs[str(run_name)] = normalized
    return {
        "version": int(payload.get("version", 1)) if isinstance(payload, dict) else 1,
        "description": payload.get("description", "Review decisions for oracle SAM2 runs.") if isinstance(payload, dict) else "Review decisions for oracle SAM2 runs.",
        "updated_at": payload.get("updated_at", utc_now_iso()) if isinstance(payload, dict) else utc_now_iso(),
        "runs": normalized_runs,
    }


def save_oracle_reviews(path: Path, document: dict[str, Any]) -> None:
    payload = {
        "version": int(document.get("version", 1)),
        "description": document.get("description") or "Review decisions for oracle SAM2 runs.",
        "updated_at": utc_now_iso(),
        "runs": document.get("runs", {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_review_for_run(document: dict[str, Any], run_name: str) -> dict[str, Any] | None:
    runs = document.get("runs", {})
    if not isinstance(runs, dict):
        return None
    entry = runs.get(run_name)
    return entry if isinstance(entry, dict) else None


def set_review_for_run(document: dict[str, Any], run_name: str, status: str, notes: str = "") -> dict[str, Any]:
    normalized_status = status.strip().lower()
    if normalized_status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {status}")
    entry = {
        "status": normalized_status,
        "notes": notes,
        "updated_at": utc_now_iso(),
    }
    document.setdefault("runs", {})[run_name] = entry
    return entry


def sync_review_into_result(run_dir: Path, review_entry: dict[str, Any]) -> None:
    result_path = run_dir / "oracle_tracking_result.json"
    if not result_path.exists():
        return
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["review_status"] = review_entry.get("status", "pending")
    payload["review_notes"] = review_entry.get("notes", "")
    result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
