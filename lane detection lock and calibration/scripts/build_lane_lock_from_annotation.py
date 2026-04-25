from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from lane_lock_calibration.lane_lock_service import build_lane_lock_from_annotation
from lane_lock_calibration.legacy import load_legacy_lane_modules
from lane_lock_calibration.paths import (
    DEFAULT_INTRINSICS_PATH,
    DEFAULT_LANE_CONFIG_PATH,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_RAW_ROOT,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lane lock from one recording and one saved 2-click annotation.")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT, help="Directory containing extracted raw runs.")
    parser.add_argument("--recording-number", type=int, required=True, help="1-based recording number.")
    parser.add_argument("--annotation", type=Path, required=True, help="Saved reference annotation JSON.")
    parser.add_argument("--intrinsics", type=Path, default=DEFAULT_INTRINSICS_PATH, help="Camera intrinsics JSON.")
    parser.add_argument("--lane-config", type=Path, default=DEFAULT_LANE_CONFIG_PATH, help="Lane dimensions JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory. Defaults to lane detection lock and calibration/outputs/lane_locks/recordingN/",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    legacy = load_legacy_lane_modules()
    run_dirs = legacy["list_run_dirs"](args.raw_root)
    if args.recording_number < 1 or args.recording_number > len(run_dirs):
        raise SystemExit(f"Recording number {args.recording_number} is out of range for {args.raw_root}")

    run_dir = run_dirs[args.recording_number - 1]
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / "lane_locks" / f"recording{args.recording_number}")
    lane_lock = build_lane_lock_from_annotation(
        run_dir=run_dir,
        annotation_path=args.annotation,
        intrinsics_path=args.intrinsics,
        lane_config_path=args.lane_config,
        output_dir=output_dir,
    )

    print(f"Built lane lock for {lane_lock.run_name}")
    print(f"lane_lock.json -> {output_dir / 'lane_lock.json'}")
    print(f"reference overlay -> {output_dir / 'lane_lock_reference_overlay.jpg'}")
    print(f"max corner residual -> {lane_lock.max_corner_residual_m:.6f} m")
    print(f"confidence -> {lane_lock.confidence_label} ({lane_lock.confidence:.3f})")


if __name__ == "__main__":
    main()
