from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LiveLaneLockStageOutput:
    session_dir: Path
    request_id: str
    shot_id: str
    result_path: Path
    preview_path: Path
    result_document: dict[str, Any]
    solve_output: Any


def draw_lane_fit_preview(image_bgr: Any, solve_output: Any) -> None:
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
        if point is None:
            continue
        center = (int(round(point.x)), int(round(point.y)))
        cv2.circle(image_bgr, center, 7, color, -1, cv2.LINE_AA)
        cv2.putText(
            image_bgr,
            label,
            (center[0] + 8, center[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )

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


def solve_lane_lock_stage_for_live_session(
    session_dir: Path | str,
    *,
    request_id: str | None = None,
    output_dir: Path | None = None,
) -> LiveLaneLockStageOutput:
    import cv2

    from laptop_receiver.lane_line_support import extract_lane_support_segments
    from laptop_receiver.lane_lock_live_session import load_live_session_lane_lock_request
    from laptop_receiver.lane_lock_solver import solve_lane_lock_from_world_points

    live_request = load_live_session_lane_lock_request(session_dir, request_id=request_id)
    request = live_request.request
    frame_states = live_request.frame_states
    artifact = live_request.artifact
    intrinsics = request.to_camera_intrinsics()

    requested_anchor_frame_seq = int(request.anchor_frame_seq)
    anchor_frame_seq = None
    anchor_frame_image = None
    anchor_frame_index = None
    anchor_frame_metadata = None
    support_segments_by_frame: dict[int, list[Any]] = {}

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
        if frame_seq != requested_anchor_frame_seq:
            continue

        anchor_frame_seq = frame_seq
        anchor_frame_image = decoded_frame.image_bgr.copy()
        anchor_frame_index = int(decoded_frame.frame_index)
        anchor_frame_metadata = frame_metadata

    if anchor_frame_image is None:
        raise RuntimeError(
            "Could not decode the exact lane-lock selection frame "
            f"{requested_anchor_frame_seq} inside request range "
            f"{request.frame_seq_start}..{request.frame_seq_end} from {artifact.video_path}"
        )

    solve_output = solve_lane_lock_from_world_points(
        request=request,
        intrinsics=intrinsics,
        frame_states=frame_states,
        support_segments_by_frame=support_segments_by_frame,
    )

    resolved_output_dir = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else artifact.root_dir / "analysis_lane_lock" / request.request_id
    )
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    result_path = resolved_output_dir / "lane_lock_result.json"
    preview_path = resolved_output_dir / "lane_lock_preview.jpg"

    preview_image = anchor_frame_image.copy()
    draw_lane_fit_preview(preview_image, solve_output)
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

    return LiveLaneLockStageOutput(
        session_dir=artifact.root_dir,
        request_id=request.request_id,
        shot_id=str(live_request.request_envelope.get("shot_id") or ""),
        result_path=result_path,
        preview_path=preview_path,
        result_document=result_document,
        solve_output=solve_output,
    )
