from __future__ import annotations

import json
from pathlib import Path

from laptop_receiver.lane_lock_types import LaneLockResult


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def load_lane_lock_result_for_request(session_dir: Path | str, request_id: str) -> LaneLockResult | None:
    root = Path(session_dir).expanduser().resolve()
    if not request_id:
        return None

    result_path = root / "analysis_lane_lock" / request_id / "lane_lock_result.json"
    if not result_path.exists():
        return None

    document = json.loads(result_path.read_text(encoding="utf-8"))
    solve_payload = document.get("solve")
    if not isinstance(solve_payload, dict):
        return None

    result_payload = solve_payload.get("result")
    if not isinstance(result_payload, dict):
        return None

    lane_lock = LaneLockResult.from_dict(result_payload)
    return lane_lock if lane_lock.success else None


def load_confirmed_lane_lock(session_dir: Path | str) -> LaneLockResult | None:
    root = Path(session_dir).expanduser().resolve()
    confirms = _load_jsonl(root / "lane_lock_confirms.jsonl")
    for confirm in reversed(confirms):
        accepted = bool(confirm.get("accepted"))
        request_id = str(confirm.get("requestId") or confirm.get("request_id") or "").strip()
        if not accepted:
            return None

        lane_lock = load_lane_lock_result_for_request(root, request_id)
        if lane_lock is not None:
            return lane_lock
    return None
