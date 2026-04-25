from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from lane_lock_calibration.calibrated_workflow import run_calibrated_session_workflow
from lane_lock_calibration.paths import (
    DEFAULT_CALIBRATION_OUTPUT_ROOT,
    DEFAULT_INTRINSICS_PATH,
    DEFAULT_LANE_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    DEFAULT_RECORDING_ANNOTATION_ROOT,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continue the lane-detection V1 workflow across recordings with automatic metadata-break detection and recalibration prompts."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT, help="Directory containing extracted raw runs.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_CALIBRATION_OUTPUT_ROOT,
        help="Root directory where the calibration output session folder will be written.",
    )
    parser.add_argument("--intrinsics", type=Path, default=DEFAULT_INTRINSICS_PATH, help="Camera intrinsics JSON.")
    parser.add_argument("--lane-config", type=Path, default=DEFAULT_LANE_CONFIG_PATH, help="Lane dimensions JSON.")
    parser.add_argument("--start-recording", type=int, default=1, help="1-based recording index to start from.")
    parser.add_argument("--end-recording", type=int, default=None, help="1-based recording index to stop at.")
    parser.add_argument("--max-candidates", type=int, default=26, help="Maximum candidate points shown in the annotation UI.")
    parser.add_argument("--video-name", type=str, default="two_click_continuous_lane_overlay.mp4", help="Output overlay video filename.")
    parser.add_argument("--video-fps", type=float, default=30.0, help="Output overlay video FPS.")
    parser.add_argument(
        "--rotation-warning-deg",
        type=float,
        default=12.0,
        help="Metadata rotation delta where recalibration becomes suggested.",
    )
    parser.add_argument(
        "--rotation-fail-deg",
        type=float,
        default=20.0,
        help="Metadata rotation delta where recalibration becomes required.",
    )
    parser.add_argument(
        "--annotation-root",
        type=Path,
        default=None,
        help="Optional root containing recordingN/reference_annotation.json files.",
    )
    parser.add_argument(
        "--auto-use-existing-annotations",
        action="store_true",
        help="Use existing annotations from --annotation-root instead of manual frame and point selection.",
    )
    parser.add_argument(
        "--auto-continue-warnings",
        action="store_true",
        help="Automatically continue through continuity warnings without prompting.",
    )
    parser.add_argument(
        "--auto-recalibrate-required",
        action="store_true",
        help="Automatically recalibrate required boundaries using existing annotations from --annotation-root.",
    )
    parser.add_argument(
        "--use-default-annotation-root",
        action="store_true",
        help="Shortcut for using the bundled annotations/ folder as --annotation-root.",
    )
    parser.add_argument("--session-name", type=str, default=None, help="Optional output session folder name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    annotation_root = args.annotation_root
    if args.use_default_annotation_root and annotation_root is None:
        annotation_root = DEFAULT_RECORDING_ANNOTATION_ROOT

    summary = run_calibrated_session_workflow(
        raw_root=args.raw_root,
        output_root=args.output_root,
        intrinsics_path=args.intrinsics,
        lane_config_path=args.lane_config,
        start_recording=args.start_recording,
        end_recording=args.end_recording,
        max_candidates=max(2, int(args.max_candidates)),
        video_name=args.video_name,
        video_fps=max(1.0, float(args.video_fps)),
        rotation_warning_deg=float(args.rotation_warning_deg),
        rotation_fail_deg=float(args.rotation_fail_deg),
        annotation_root=annotation_root,
        auto_use_existing_annotations=bool(args.auto_use_existing_annotations),
        auto_continue_warnings=bool(args.auto_continue_warnings),
        auto_recalibrate_required=bool(args.auto_recalibrate_required),
        session_name=args.session_name,
    )

    session_dir = Path(summary["output_root"])
    print(f"Calibration workflow complete: {summary['session_name']}")
    print(f"session summary -> {session_dir / 'session_summary.json'}")
    print(f"session markdown -> {session_dir / 'session_summary.md'}")
    print(
        "calibration recordings -> "
        + ", ".join(f"recording{value}" for value in summary["calibration_recordings"])
    )


if __name__ == "__main__":
    main()
