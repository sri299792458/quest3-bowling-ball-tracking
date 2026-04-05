from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .oracle_review_utils import (
        DEFAULT_ORACLE_REVIEW_PATH,
        VALID_REVIEW_STATUSES,
        get_review_for_run,
        load_oracle_reviews,
        save_oracle_reviews,
        set_review_for_run,
        sync_review_into_result,
    )
    from .oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
except ImportError:
    from oracle_review_utils import (
        DEFAULT_ORACLE_REVIEW_PATH,
        VALID_REVIEW_STATUSES,
        get_review_for_run,
        load_oracle_reviews,
        save_oracle_reviews,
        set_review_for_run,
        sync_review_into_result,
    )
    from oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_row(run_dir: Path, review_doc: dict[str, Any]) -> dict[str, Any]:
    result_path = run_dir / "oracle_tracking_result.json"
    result = _load_json(result_path) if result_path.exists() else {}
    review = get_review_for_run(review_doc, run_dir.name) or {"status": "pending", "notes": ""}
    return {
        "run_name": run_dir.name,
        "review_status": review.get("status", "pending"),
        "tracked_frames": int(result.get("tracked_frames") or 0),
        "success": bool(result.get("success")),
        "failure_reason": result.get("failure_reason", ""),
        "preview_path": result.get("preview_path", ""),
        "notes": review.get("notes", ""),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Review bookkeeping for oracle-seeded SAM2 bowling runs.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--reviews-path", type=Path, default=DEFAULT_ORACLE_REVIEW_PATH)
    parser.add_argument("--run-name", action="append", default=[], help="Run name to update. Can be repeated.")
    parser.add_argument("--status", choices=sorted(VALID_REVIEW_STATUSES))
    parser.add_argument("--notes", default="", help="Optional short note for the updated runs.")
    parser.add_argument("--list", action="store_true", help="List current review status for all runs.")
    parser.add_argument("--only-status", choices=sorted(VALID_REVIEW_STATUSES), default="", help="Filter --list output to one status.")
    parser.add_argument("--summary-only", action="store_true", help="With --list, print only status counts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    reviews_path = args.reviews_path.resolve()
    run_dirs = list_run_dirs(input_root)
    review_doc = load_oracle_reviews(reviews_path)

    if args.status:
        if not args.run_name:
            raise SystemExit("--status requires at least one --run-name.")
        run_lookup = {run_dir.name: run_dir for run_dir in run_dirs}
        for run_name in args.run_name:
            run_dir = run_lookup.get(run_name)
            if run_dir is None:
                raise SystemExit(f"Run not found under {input_root}: {run_name}")
            review_entry = set_review_for_run(review_doc, run_name, args.status, notes=args.notes)
            sync_review_into_result(run_dir, review_entry)
        save_oracle_reviews(reviews_path, review_doc)

    rows = [_build_row(run_dir, review_doc) for run_dir in run_dirs]
    if args.only_status:
        rows = [row for row in rows if row["review_status"] == args.only_status]

    counts = {status: 0 for status in sorted(VALID_REVIEW_STATUSES)}
    for row in rows:
        counts[row["review_status"]] = counts.get(row["review_status"], 0) + 1

    if args.list or not args.status:
        if not args.summary_only:
            for row in rows:
                print(
                    f"{row['review_status']:>10} | "
                    f"tracked={row['tracked_frames']:>3} | "
                    f"success={str(row['success']).lower():<5} | "
                    f"{row['run_name']}"
                )
                if row["notes"]:
                    print(f"           notes: {row['notes']}")
                if row["failure_reason"]:
                    print(f"           failure: {row['failure_reason']}")
        print("summary:")
        for status in sorted(counts):
            print(f"  {status}: {counts[status]}")
        print(f"reviews_path: {reviews_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
