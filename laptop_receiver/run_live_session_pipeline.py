from __future__ import annotations

import argparse
import json
from pathlib import Path

from laptop_receiver.live_session_pipeline import build_pipeline_from_paths
from laptop_receiver.live_stream_receiver import DEFAULT_INCOMING_ROOT


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
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    session_dir = args.session_dir.expanduser().resolve() if args.session_dir is not None else None
    if session_dir is not None and not session_dir.exists():
        parser.error(f"--session-dir does not exist: {session_dir}")

    pipeline = build_pipeline_from_paths(
        incoming_root=args.incoming_root.expanduser().resolve(),
        session_dir=session_dir,
        publish_result_host=None if args.no_publish else args.publish_result_host,
        publish_result_port=args.publish_result_port,
        poll_interval_seconds=args.poll_interval,
        idle_log_interval_seconds=args.idle_log_interval,
    )

    if args.once:
        summary = pipeline.process_once()
        document = {"kind": "live_pipeline_once", **summary.to_dict()}
        if args.emit_json:
            print(json.dumps(document, indent=2))
        else:
            print(f"sessions:      {summary.discovered_sessions}")
            print(f"lane seen:     {summary.lane_lock_requests_seen}")
            print(f"lane done:     {summary.lane_lock_requests_processed}")
            print(f"lane skipped:  {summary.lane_lock_requests_skipped}")
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
