from __future__ import annotations

import argparse
import json
from pathlib import Path

from laptop_receiver.live_session_pipeline import build_pipeline_from_paths
from laptop_receiver.live_camera_sam2_tracker import LiveCameraSam2Config
from laptop_receiver.live_shot_boundary_detector import LiveShotBoundaryDetectorConfig
from laptop_receiver.live_shot_tracking_stage import LiveShotTrackingStageConfig
from laptop_receiver.live_stream_receiver import DEFAULT_INCOMING_ROOT
from laptop_receiver.standalone_warm_sam2_tracker import (
    DEFAULT_SAM2_CACHE_ROOT,
    DEFAULT_SAM2_CHECKPOINT,
    DEFAULT_SAM2_ROOT,
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the laptop live-session analysis pipeline over incoming Quest stream sessions."
    )
    parser.add_argument(
        "--incoming-root",
        type=Path,
        default=DEFAULT_INCOMING_ROOT,
        help="Root folder where live_<session>_<stream> directories land.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=None,
        help="Optional single live session directory to process instead of polling the incoming root.",
    )
    parser.add_argument(
        "--publish-result-host",
        type=str,
        default="127.0.0.1",
        help="Host for the local live receiver result publish endpoint.",
    )
    parser.add_argument(
        "--publish-result-port",
        type=int,
        default=8770,
        help="Port for the local live receiver result publish endpoint.",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Process requests without sending laptop result envelopes back to the live receiver.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between polling passes in continuous mode.",
    )
    parser.add_argument(
        "--idle-log-interval",
        type=float,
        default=5.0,
        help="Seconds between idle status lines in continuous mode.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling pass and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the one-shot summary as JSON.",
    )
    parser.add_argument(
        "--yolo-checkpoint",
        type=Path,
        default=None,
        help="Enable shot tracking with this YOLO checkpoint.",
    )
    parser.add_argument("--yolo-imgsz", type=int, default=1280)
    parser.add_argument("--yolo-device", default="0")
    parser.add_argument("--yolo-det-conf", type=float, default=0.05)
    parser.add_argument("--yolo-seed-conf", type=float, default=0.8)
    parser.add_argument("--yolo-min-box-size", type=float, default=10.0)
    parser.add_argument("--yolo-scan-stride", type=int, default=2)
    parser.add_argument(
        "--run-sam2",
        action="store_true",
        help="Enable SAM2 shot-result generation from live YOLO shot windows.",
    )
    parser.add_argument("--sam2-root", type=Path, default=DEFAULT_SAM2_ROOT)
    parser.add_argument("--sam2-checkpoint", type=Path, default=DEFAULT_SAM2_CHECKPOINT)
    parser.add_argument("--sam2-cache-root", type=Path, default=DEFAULT_SAM2_CACHE_ROOT)
    parser.add_argument("--sam2-model-cfg", default="configs/sam2.1/sam2.1_hiera_t.yaml")
    parser.add_argument("--sam2-track-seconds", type=float, default=5.0)
    parser.add_argument("--sam2-lost-grace-frames", type=int, default=5)
    parser.add_argument("--live-tail-seconds", type=float, default=2.0)
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    session_dir = args.session_dir.expanduser().resolve() if args.session_dir is not None else None
    if session_dir is not None and not session_dir.exists():
        parser.error(f"--session-dir does not exist: {session_dir}")

    shot_boundary_detector_config = None
    shot_tracking_config = None
    if args.run_sam2 and args.yolo_checkpoint is None:
        parser.error("--run-sam2 requires --yolo-checkpoint.")

    if args.yolo_checkpoint is not None:
        yolo_checkpoint = args.yolo_checkpoint.expanduser().resolve()
        if not yolo_checkpoint.exists():
            parser.error(f"--yolo-checkpoint does not exist: {yolo_checkpoint}")

        sam2_config = None
        if args.run_sam2:
            sam2_root = args.sam2_root.expanduser().resolve()
            sam2_checkpoint = args.sam2_checkpoint.expanduser().resolve()
            if not sam2_root.exists():
                parser.error(f"--sam2-root does not exist: {sam2_root}")
            if not sam2_checkpoint.exists():
                parser.error(f"--sam2-checkpoint does not exist: {sam2_checkpoint}")

            sam2_config = LiveCameraSam2Config(
                sam2_root=sam2_root,
                cache_root=args.sam2_cache_root.expanduser().resolve(),
                checkpoint=sam2_checkpoint,
                model_cfg=str(args.sam2_model_cfg),
                max_track_seconds=float(args.sam2_track_seconds),
                lost_track_grace_frames=int(args.sam2_lost_grace_frames),
            )

        if args.run_sam2:
            shot_tracking_config = LiveShotTrackingStageConfig(
                yolo_checkpoint_path=yolo_checkpoint,
                yolo_imgsz=int(args.yolo_imgsz),
                yolo_device=str(args.yolo_device),
                yolo_det_conf=float(args.yolo_det_conf),
                yolo_seed_conf=float(args.yolo_seed_conf),
                yolo_min_box_size=float(args.yolo_min_box_size),
                run_sam2=True,
                sam2_config=sam2_config,
            )
        shot_boundary_detector_config = LiveShotBoundaryDetectorConfig(
            yolo_checkpoint_path=yolo_checkpoint,
            yolo_imgsz=int(args.yolo_imgsz),
            yolo_device=str(args.yolo_device),
            yolo_det_conf=float(args.yolo_det_conf),
            yolo_start_conf=float(args.yolo_seed_conf),
            yolo_min_box_size=float(args.yolo_min_box_size),
            scan_stride_frames=max(int(args.yolo_scan_stride), 1),
            shot_window_seconds=float(args.sam2_track_seconds),
            max_live_idle_backlog_seconds=float(args.live_tail_seconds),
        )

    pipeline = build_pipeline_from_paths(
        incoming_root=args.incoming_root.expanduser().resolve(),
        session_dir=session_dir,
        publish_result_host=None if args.no_publish else args.publish_result_host,
        publish_result_port=args.publish_result_port,
        poll_interval_seconds=args.poll_interval,
        idle_log_interval_seconds=args.idle_log_interval,
        shot_boundary_detector_config=shot_boundary_detector_config,
        shot_tracking_config=shot_tracking_config,
    )

    if args.once:
        summary = pipeline.process_once()
        document = {"kind": "live_pipeline_once", **summary.to_dict()}
        if args.emit_json:
            print(json.dumps(document, indent=2))
        else:
            print(f"sessions:      {summary.discovered_sessions}")
            print(f"auto frames:   {summary.auto_shot_boundary_frames_scanned}")
            print(f"auto yolo:     {summary.auto_shot_boundary_yolo_frames}")
            print(f"auto events:   {summary.auto_shot_boundary_events_emitted}")
            print(f"shot events:   {summary.shot_boundary_events_seen}")
            print(f"shot windows:  {summary.completed_shot_windows_seen}")
            print(f"shot done:     {summary.completed_shot_windows_processed}")
            print(f"shot skipped:  {summary.completed_shot_windows_skipped}")
            print(f"shot open:     {summary.open_shot_windows_seen}")
            for error in summary.errors:
                print(f"error:         {error}")
        return 1 if summary.errors else 0

    try:
        pipeline.run_forever()
    except KeyboardInterrupt:
        print("live pipeline stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
