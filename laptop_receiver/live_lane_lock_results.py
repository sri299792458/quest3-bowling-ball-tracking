from __future__ import annotations

import json
from pathlib import Path

from laptop_receiver.lane_lock_types import LaneLockResult


def load_latest_successful_lane_lock(session_dir: Path | str) -> LaneLockResult | None:
    root = Path(session_dir).expanduser().resolve()
    lane_lock_root = root / "analysis_lane_lock"
    if not lane_lock_root.exists():
        return None

    result_paths = sorted(
        lane_lock_root.glob("*/lane_lock_result.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for result_path in result_paths:
        document = json.loads(result_path.read_text(encoding="utf-8"))
        solve_payload = document.get("solve")
        if not isinstance(solve_payload, dict):
            continue
        result_payload = solve_payload.get("result")
        if not isinstance(result_payload, dict):
            continue
        lane_lock = LaneLockResult.from_dict(result_payload)
        if lane_lock.success:
            return lane_lock
    return None
