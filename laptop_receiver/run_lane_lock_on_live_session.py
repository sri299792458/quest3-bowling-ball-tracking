from __future__ import annotations

import argparse
import json
from pathlib import Path

from laptop_receiver.laptop_result_types import build_lane_lock_result_envelope, publish_laptop_result


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


def _draw_lane_fit_preview(image_bgr, solve_output) -> None:
    import cv2
    import numpy as np

    for segment in solve_output.support_segments:
        x1, y1, x2, y2 = segment.line_xyxy
        cv2.line(image_bgr, (x1, y1), (x2, y2), (0, 120, 255), 1, cv2.LINE_AA)

    geometry = solve_output.geometry
    for point, label, color in (
        (geometry.left_foul_line_point_px, "L", (80, 255, 80)),
        (geometry.right_foul_line_point_px, "R", (255, 180, 80)),
    ):
        center = (int(round(point.x)), int(round(point.y)))
        cv2.circle(image_bgr, center, 7, color, -1, cv2.LINE_AA)
        cv2.putText(image_bgr, label, (center[0] + 8, center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    for polyline, color in (
        (solve_output.projected_left_polyline, (80, 255, 80)),
        (solve_output.projected_right_polyline, (80, 255, 80)),
        (solve_output.projected_foul_line_polyline, (255, 180, 80)),
    ):
        if len(polyline) < 2:
            continue
        points = np.asarray(
            [[int(round(point.x)), int(round(point.y))] for point in polyline],
            dtype=np.int32,
        )
        cv2.polylines(image_bgr, [points], False, color, 2, cv2.LINE_AA)


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    import cv2
    from laptop_receiver.lane_lock_live_session import load_live_session_lane_lock_request
    from laptop_receiver.lane_line_support import extract_lane_support_segments
    from laptop_receiver.lane_lock_solver import solve_lane_lock_from_image

    live_request = load_live_session_lane_lock_request(args.session_dir, request_id=args.request_id)
    request = live_request.request
    frame_states = live_request.frame_states
    artifact = live_request.artifact
    intrinsics = request.to_camera_intrinsics()

    requested_anchor_frame_seq = int(request.selection_frame_seq)
    anchor_frame_seq = None
    anchor_frame_image = None
    anchor_frame_index = None
    anchor_frame_metadata = None
    support_segments_by_frame: dict[int, list] = {}
    best_distance = None
    for decoded_frame in artifact.iter_frames():
        frame_metadata = decoded_frame.metadata or {}
        frame_seq = int(frame_metadata.get("frameSeq", decoded_frame.frame_index))
        if frame_seq < int(request.frame_seq_start) or frame_seq > int(request.frame_seq_end):
            continue

        support_segments_by_frame[frame_seq] = extract_lane_support_segments(
            decoded_frame.image_bgr,
            frame_seq=frame_seq,
            frame_index=decoded_frame.frame_index,
        )
        distance = abs(frame_seq - requested_anchor_frame_seq)
        if frame_seq != requested_anchor_frame_seq:
            continue
        if best_distance is not None and distance >= best_distance:
            continue
        best_distance = distance
        anchor_frame_seq = frame_seq
        anchor_frame_image = decoded_frame.image_bgr.copy()
        anchor_frame_index = int(decoded_frame.frame_index)
        anchor_frame_metadata = frame_metadata

    if anchor_frame_image is None:
        raise SystemExit(
            f"Could not decode any frame inside lane_lock_request range {request.frame_seq_start}..{request.frame_seq_end} from {artifact.video_path}"
        )

    solve_output = solve_lane_lock_from_image(
        request=request,
        intrinsics=intrinsics,
        frame_states=frame_states,
        support_segments_by_frame=support_segments_by_frame,
    )

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else artifact.root_dir / "analysis_lane_lock" / request.request_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "lane_lock_result.json"
    preview_path = output_dir / "lane_lock_preview.jpg"

    preview_image = anchor_frame_image.copy()
    _draw_lane_fit_preview(preview_image, solve_output)
    cv2.imwrite(str(preview_path), preview_image)

    result_document = {
        "kind": "lane_lock_solve",
        "sessionDir": str(artifact.root_dir),
        "videoPath": str(artifact.video_path),
        "requestEnvelope": live_request.request_envelope,
        "request": request.to_dict(),
        "requestedAnchorFrameSeq": requested_anchor_frame_seq,
        "anchorFrameSeq": anchor_frame_seq,
        "anchorFrameIndex": anchor_frame_index,
        "anchorFrameMetadata": anchor_frame_metadata,
        "previewPath": str(preview_path),
        "solve": solve_output.to_dict(),
    }
    result_path.write_text(json.dumps(result_document, indent=2), encoding="utf-8")

    if args.publish_result_host:
        shot_id = str(live_request.request_envelope.get("shot_id") or "")
        envelope = build_lane_lock_result_envelope(
            result=solve_output.result,
            shot_id=shot_id,
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
        print(f"session:   {artifact.root_dir}")
        print(f"request:   {request.request_id}")
        print(f"output:    {result_path}")
        print(f"preview:   {preview_path}")
        print(f"frame_seq: {anchor_frame_seq} (requested {requested_anchor_frame_seq})")
        print(f"success:   {solve_output.result.success}")
        print(f"conf:      {solve_output.result.confidence:.3f}")
        if published_note:
            print(published_note)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
