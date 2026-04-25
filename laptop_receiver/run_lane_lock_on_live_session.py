from __future__ import annotations

import argparse
import json
from pathlib import Path

from laptop_receiver.laptop_result_types import build_lane_lock_result_envelope, publish_laptop_result
from laptop_receiver.live_lane_lock_stage import solve_lane_lock_stage_for_live_session


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Solve lane lock from a live session directory and its latest lane_lock_request event."
    )
    parser.add_argument("session_dir", type=Path, help="Path to the live session directory.")
    parser.add_argument("--request-id", type=str, default=None, help="Optional explicit lane_lock_request requestId.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional explicit output directory. Defaults to analysis_lane_lock/<requestId> inside the session.",
    )
    parser.add_argument(
        "--publish-result-host",
        type=str,
        default=None,
        help="Optional host for the local live receiver result publish endpoint.",
    )
    parser.add_argument(
        "--publish-result-port",
        type=int,
        default=8770,
        help="Port for the local live receiver result publish endpoint.",
    )
    parser.add_argument("--json", action="store_true", dest="emit_json", help="Emit the full result document as JSON.")
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    stage_output = solve_lane_lock_stage_for_live_session(
        args.session_dir,
        request_id=args.request_id,
        output_dir=args.output_dir,
    )
    solve_output = stage_output.solve_output
    result_document = stage_output.result_document

    if args.publish_result_host:
        envelope = build_lane_lock_result_envelope(
            result=solve_output.result,
            shot_id=stage_output.shot_id,
        )
        publish_laptop_result(
            envelope,
            host=str(args.publish_result_host),
            port=int(args.publish_result_port),
        )
        published_note = f"published: tcp://{args.publish_result_host}:{args.publish_result_port}"
    else:
        published_note = ""

    if args.emit_json:
        print(json.dumps(result_document, indent=2))
    else:
        print(f"session:   {stage_output.session_dir}")
        print(f"request:   {stage_output.request_id}")
        print(f"output:    {stage_output.result_path}")
        print(f"preview:   {stage_output.preview_path}")
        print(
            "frame_seq: "
            f"{result_document['anchorFrameSeq']} "
            f"(requested {result_document['requestedAnchorFrameSeq']})"
        )
        print(f"success:   {solve_output.result.success}")
        print(f"conf:      {solve_output.result.confidence:.3f}")
        if published_note:
            print(published_note)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
