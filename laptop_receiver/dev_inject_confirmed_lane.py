from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Sequence

import cv2
import numpy as np

from laptop_receiver.lane_geometry import (
    camera_ray_to_world_ray,
    image_point_to_camera_ray,
    intersect_ray_plane,
    normalize_vector,
    vector3_to_numpy,
    world_point_to_image_point,
)
from laptop_receiver.lane_lock_solver import _build_lane_rotation
from laptop_receiver.lane_lock_types import (
    CameraIntrinsics,
    FrameCameraState,
    LaneLockConfidenceBreakdown,
    LaneLockResult,
    ReleaseCorridor,
    ReprojectionMetrics,
    SourceFrameRange,
    Vector2,
    Vector3,
)
from laptop_receiver.local_clip_artifact import DecodedFrame, LocalClipArtifact, load_local_clip_artifact
from laptop_receiver.session_state import LANE_CONFIRMED, SHOT_ARMED, mark_lane, mark_shot


DEFAULT_LANE_WIDTH_METERS = 1.0541
DEFAULT_LANE_LENGTH_METERS = 18.288
DEFAULT_MAX_DISPLAY_WIDTH = 1600
DEFAULT_MAX_DISPLAY_HEIGHT = 950
CLICK_LABELS = (
    "near-left foul-line corner",
    "near-right foul-line corner",
    "far-left lane edge",
    "far-right lane edge",
)


@dataclass(frozen=True)
class SelectedFrame:
    frame: DecodedFrame
    frame_state: FrameCameraState
    intrinsics: CameraIntrinsics
    source: str


@dataclass(frozen=True)
class ManualLaneGeometry:
    clicked_points_px: list[Vector2]
    clicked_points_world: list[Vector3]
    lane_origin_world: Vector3
    lane_rotation_world: Any
    right_axis_world: Vector3
    forward_axis_world: Vector3
    floor_plane_point_world: Vector3
    floor_plane_normal_world: Vector3
    selected_width_meters: float
    width_error_meters: float
    visible_downlane_meters: float
    reprojection_error_px: float
    projected_left_polyline: list[Vector2]
    projected_right_polyline: list[Vector2]
    projected_foul_line_polyline: list[Vector2]


def _float_triplet(text: str) -> Vector3:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"Vector {text!r} must be formatted as x,y,z.")
    try:
        return Vector3(x=float(parts[0]), y=float(parts[1]), z=float(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Vector {text!r} must contain numeric x,y,z values.") from exc


def _session_identity(artifact: LocalClipArtifact) -> tuple[str, str]:
    session_id = str(
        artifact.session_metadata.get("sessionId")
        or artifact.session_metadata.get("session_id")
        or artifact.manifest.get("sessionId")
        or artifact.manifest.get("session_id")
        or ""
    ).strip()
    shot_id = str(
        artifact.shot_metadata.get("shotId")
        or artifact.shot_metadata.get("shot_id")
        or artifact.manifest.get("shotId")
        or artifact.manifest.get("shot_id")
        or "live_stream"
    ).strip()
    if not session_id:
        raise RuntimeError("Session metadata is missing sessionId.")
    return session_id, shot_id


def _camera_intrinsics_from_artifact(artifact: LocalClipArtifact) -> CameraIntrinsics:
    intrinsics = CameraIntrinsics.from_session_metadata(artifact.session_metadata)
    if intrinsics.fx == 0.0 or intrinsics.fy == 0.0:
        raise RuntimeError("Session metadata is missing non-zero camera intrinsics.")
    if intrinsics.width <= 0 or intrinsics.height <= 0:
        width = int(artifact.video_info.width)
        height = int(artifact.video_info.height)
        intrinsics = CameraIntrinsics(
            fx=intrinsics.fx,
            fy=intrinsics.fy,
            cx=intrinsics.cx,
            cy=intrinsics.cy,
            width=width,
            height=height,
        )
    return intrinsics


def _frame_seq(metadata: dict[str, Any], fallback: int) -> int:
    try:
        return int(metadata.get("frameSeq", fallback))
    except Exception:
        return int(fallback)


def _target_frame_index(
    artifact: LocalClipArtifact,
    *,
    frame_index: int | None,
    frame_seq: int | None,
) -> int:
    if frame_index is not None:
        if frame_index < 0:
            raise RuntimeError("--frame-index must be non-negative.")
        return int(frame_index)

    if frame_seq is not None:
        for index, metadata in enumerate(artifact.frame_metadata):
            if _frame_seq(metadata, index) == int(frame_seq):
                return index
        raise RuntimeError(f"Could not find frameSeq {frame_seq} in frame metadata.")

    if not artifact.frame_metadata:
        raise RuntimeError("Cannot choose latest frame because frame metadata is empty.")
    return len(artifact.frame_metadata) - 1


def _decode_frame_exact_or_latest(
    artifact: LocalClipArtifact,
    target_index: int,
    *,
    allow_earlier_when_latest: bool,
) -> DecodedFrame:
    latest: DecodedFrame | None = None
    for decoded in artifact.iter_frames():
        latest = decoded
        if int(decoded.frame_index) == int(target_index):
            return decoded
        if int(decoded.frame_index) > int(target_index):
            break

    if allow_earlier_when_latest and latest is not None:
        return latest
    raise RuntimeError(f"Could not decode requested frame index {target_index} from {artifact.video_path}.")


def _select_frame(
    artifact: LocalClipArtifact,
    *,
    frame_index: int | None,
    frame_seq: int | None,
) -> SelectedFrame:
    intrinsics = _camera_intrinsics_from_artifact(artifact)
    target_index = _target_frame_index(artifact, frame_index=frame_index, frame_seq=frame_seq)
    allow_earlier_when_latest = frame_index is None and frame_seq is None
    decoded = _decode_frame_exact_or_latest(
        artifact,
        target_index,
        allow_earlier_when_latest=allow_earlier_when_latest,
    )
    if not decoded.metadata:
        raise RuntimeError(f"Decoded frame {decoded.frame_index} has no frame metadata.")

    frame_state = FrameCameraState.from_frame_metadata(decoded.metadata)
    source = f"frameIndex={decoded.frame_index} frameSeq={frame_state.frame_seq}"
    if int(decoded.frame_index) != int(target_index):
        source += f" requestedLatestIndex={target_index}"
    return SelectedFrame(
        frame=decoded,
        frame_state=frame_state,
        intrinsics=intrinsics,
        source=source,
    )


def _selected_frame_from_decoded(
    decoded: DecodedFrame,
    intrinsics: CameraIntrinsics,
    *,
    target_index: int,
) -> SelectedFrame:
    if not decoded.metadata:
        raise RuntimeError(f"Decoded frame {decoded.frame_index} has no frame metadata.")

    frame_state = FrameCameraState.from_frame_metadata(decoded.metadata)
    source = f"frameIndex={decoded.frame_index} frameSeq={frame_state.frame_seq}"
    if int(decoded.frame_index) != int(target_index):
        source += f" requestedFrameIndex={target_index}"
    return SelectedFrame(
        frame=decoded,
        frame_state=frame_state,
        intrinsics=intrinsics,
        source=source,
    )


def _scaled_image(image_bgr: Any, max_width: int, max_height: int) -> tuple[Any, float]:
    height, width = image_bgr.shape[:2]
    scale = min(float(max_width) / max(float(width), 1.0), float(max_height) / max(float(height), 1.0), 1.0)
    if scale >= 0.999:
        return image_bgr.copy(), 1.0
    resized = cv2.resize(image_bgr, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
    return resized, scale


def _draw_browser_overlay(
    image_bgr: Any,
    selected_frame: SelectedFrame,
    *,
    max_frame_index: int,
) -> Any:
    canvas = image_bgr.copy()
    frame_index = int(selected_frame.frame.frame_index)
    frame_seq = int(selected_frame.frame_state.frame_seq)
    text = (
        f"Choose lane frame | frame {frame_index}/{max_frame_index} seq={frame_seq} | "
        "Left/Right or A/D step | PageUp/PageDown jump | Home/End | Enter choose | Esc cancel"
    )
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(canvas, text, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def _choose_frame_interactive(
    artifact: LocalClipArtifact,
    *,
    max_display_width: int,
    max_display_height: int,
) -> SelectedFrame:
    if not artifact.frame_metadata:
        raise RuntimeError("Cannot browse frames because frame metadata is empty.")

    intrinsics = _camera_intrinsics_from_artifact(artifact)
    max_frame_index = max(len(artifact.frame_metadata) - 1, 0)
    target_index = max_frame_index
    cache: dict[int, SelectedFrame] = {}
    last_error = ""

    def load_for_browser(index: int) -> SelectedFrame:
        clamped_index = max(0, min(int(index), max_frame_index))
        cached = cache.get(clamped_index)
        if cached is not None:
            return cached
        decoded = _decode_frame_exact_or_latest(
            artifact,
            clamped_index,
            allow_earlier_when_latest=clamped_index == max_frame_index,
        )
        selected = _selected_frame_from_decoded(decoded, intrinsics, target_index=clamped_index)
        cache[int(decoded.frame_index)] = selected
        cache[clamped_index] = selected
        return selected

    selected_frame = load_for_browser(target_index)
    target_index = int(selected_frame.frame.frame_index)
    window_name = "Quest Bowling Dev Lane Frame"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        while True:
            display_image, _scale = _scaled_image(selected_frame.frame.image_bgr, max_display_width, max_display_height)
            canvas = _draw_browser_overlay(display_image, selected_frame, max_frame_index=max_frame_index)
            if last_error:
                cv2.rectangle(canvas, (0, canvas.shape[0] - 34), (canvas.shape[1], canvas.shape[0]), (0, 0, 0), -1)
                cv2.putText(
                    canvas,
                    last_error[:180],
                    (10, canvas.shape[0] - 11),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (80, 180, 255),
                    1,
                    cv2.LINE_AA,
                )
            cv2.imshow(window_name, canvas)
            key = cv2.waitKeyEx(30)
            if key in (13, 10):
                return selected_frame
            if key in (27, ord("q"), ord("Q")):
                raise RuntimeError("Manual lane frame selection cancelled.")

            previous_target = target_index
            if key in (2424832, ord("a"), ord("A"), ord("j"), ord("J"), ord(",")):
                target_index -= 1
            elif key in (2555904, ord("d"), ord("D"), ord("l"), ord("L"), ord(".")):
                target_index += 1
            elif key in (2162688, ord("w"), ord("W")):
                target_index -= 30
            elif key in (2228224, ord("s"), ord("S")):
                target_index += 30
            elif key == 2359296:
                target_index = 0
            elif key == 2293760:
                target_index = max_frame_index

            target_index = max(0, min(int(target_index), max_frame_index))
            if target_index == previous_target:
                continue

            try:
                selected_frame = load_for_browser(target_index)
                target_index = int(selected_frame.frame.frame_index)
                last_error = ""
            except Exception as exc:
                target_index = previous_target
                last_error = f"{exc.__class__.__name__}: {exc}"
    finally:
        cv2.destroyWindow(window_name)


def _draw_manual_overlay(image_bgr: Any, points: Sequence[Vector2], scale: float) -> Any:
    canvas = image_bgr.copy()
    scaled_points = [(int(round(point.x * scale)), int(round(point.y * scale))) for point in points]
    colors = [(80, 255, 80), (255, 180, 80), (80, 220, 255), (80, 220, 255)]
    for index, point in enumerate(scaled_points):
        cv2.circle(canvas, point, 6, colors[index], -1, cv2.LINE_AA)
        cv2.putText(
            canvas,
            str(index + 1),
            (point[0] + 8, point[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            colors[index],
            2,
            cv2.LINE_AA,
        )

    if len(scaled_points) >= 2:
        cv2.line(canvas, scaled_points[0], scaled_points[1], (255, 180, 80), 2, cv2.LINE_AA)
    if len(scaled_points) >= 4:
        polyline = np.asarray(
            [scaled_points[0], scaled_points[1], scaled_points[3], scaled_points[2], scaled_points[0]],
            dtype=np.int32,
        )
        cv2.polylines(canvas, [polyline], True, (80, 255, 80), 2, cv2.LINE_AA)

    next_label = CLICK_LABELS[min(len(points), len(CLICK_LABELS) - 1)] if len(points) < 4 else "press Enter"
    instruction = f"Click {len(points) + 1}/4: {next_label} | Backspace/right-click undo | r reset | Enter accept | Esc cancel"
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(canvas, instruction, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return canvas


def _collect_points_interactive(
    image_bgr: Any,
    *,
    max_display_width: int,
    max_display_height: int,
) -> list[Vector2]:
    display_image, scale = _scaled_image(image_bgr, max_display_width, max_display_height)
    points: list[Vector2] = []
    window_name = "Quest Bowling Dev Lane Injector"

    def on_mouse(event: int, x: int, y: int, _flags: int, _userdata: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append(Vector2(x=float(x) / scale, y=float(y) / scale))
        elif event == cv2.EVENT_RBUTTONDOWN and points:
            points.pop()

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, on_mouse)
    try:
        while True:
            canvas = _draw_manual_overlay(display_image, points, scale=scale)
            cv2.imshow(window_name, canvas)
            key = cv2.waitKey(30) & 0xFF
            if key in (13, 10) and len(points) == 4:
                return list(points)
            if key in (8, 127) and points:
                points.pop()
            elif key in (ord("r"), ord("R")):
                points.clear()
            elif key in (27, ord("q"), ord("Q")):
                raise RuntimeError("Manual lane injection cancelled.")
    finally:
        cv2.destroyWindow(window_name)


def _intersect_image_point_with_floor(
    image_point: Vector2,
    intrinsics: CameraIntrinsics,
    frame_state: FrameCameraState,
    floor_point_world: np.ndarray,
    floor_normal_world: np.ndarray,
) -> np.ndarray:
    ray_camera = image_point_to_camera_ray(image_point, intrinsics)
    ray_origin_world, ray_direction_world = camera_ray_to_world_ray(ray_camera, frame_state.camera_pose_world)
    intersection = intersect_ray_plane(
        ray_origin_world,
        ray_direction_world,
        floor_point_world,
        floor_normal_world,
    )
    if intersection is None:
        raise RuntimeError(
            f"Clicked point ({image_point.x:.1f},{image_point.y:.1f}) did not intersect the configured floor plane."
        )
    return intersection.point_world


def _vector3_from_numpy(values: np.ndarray) -> Vector3:
    return Vector3(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def _lane_world_point(
    origin_world: np.ndarray,
    right_axis_world: np.ndarray,
    forward_axis_world: np.ndarray,
    lane_width_meters: float,
    lateral_sign: float,
    downlane_meters: float,
) -> np.ndarray:
    return (
        origin_world
        + float(lateral_sign) * 0.5 * float(lane_width_meters) * right_axis_world
        + float(downlane_meters) * forward_axis_world
    )


def _project_lane_edges(
    origin_world: np.ndarray,
    right_axis_world: np.ndarray,
    forward_axis_world: np.ndarray,
    lane_width_meters: float,
    lane_length_meters: float,
    intrinsics: CameraIntrinsics,
    frame_state: FrameCameraState,
    sample_count: int = 32,
) -> tuple[list[Vector2], list[Vector2], list[Vector2]]:
    left_polyline: list[Vector2] = []
    right_polyline: list[Vector2] = []
    for s_meters in np.linspace(0.0, float(lane_length_meters), int(sample_count), dtype=np.float64):
        left_image = world_point_to_image_point(
            _lane_world_point(origin_world, right_axis_world, forward_axis_world, lane_width_meters, -1.0, float(s_meters)),
            intrinsics,
            frame_state.camera_pose_world,
        )
        right_image = world_point_to_image_point(
            _lane_world_point(origin_world, right_axis_world, forward_axis_world, lane_width_meters, 1.0, float(s_meters)),
            intrinsics,
            frame_state.camera_pose_world,
        )
        if left_image is not None:
            left_polyline.append(left_image)
        if right_image is not None:
            right_polyline.append(right_image)

    foul_line = [
        point
        for point in (
            world_point_to_image_point(
                _lane_world_point(origin_world, right_axis_world, forward_axis_world, lane_width_meters, -1.0, 0.0),
                intrinsics,
                frame_state.camera_pose_world,
            ),
            world_point_to_image_point(
                _lane_world_point(origin_world, right_axis_world, forward_axis_world, lane_width_meters, 1.0, 0.0),
                intrinsics,
                frame_state.camera_pose_world,
            ),
        )
        if point is not None
    ]
    return left_polyline, right_polyline, foul_line


def _visible_downlane_meters(
    origin_world: np.ndarray,
    right_axis_world: np.ndarray,
    forward_axis_world: np.ndarray,
    lane_width_meters: float,
    lane_length_meters: float,
    intrinsics: CameraIntrinsics,
    frame_state: FrameCameraState,
) -> float:
    width = int(frame_state.width or intrinsics.width)
    height = int(frame_state.height or intrinsics.height)
    visible = 0.0
    for s_meters in np.linspace(0.0, float(lane_length_meters), 48, dtype=np.float64):
        for lateral_sign in (-1.0, 1.0):
            point_world = _lane_world_point(
                origin_world,
                right_axis_world,
                forward_axis_world,
                lane_width_meters,
                lateral_sign,
                float(s_meters),
            )
            image_point = world_point_to_image_point(point_world, intrinsics, frame_state.camera_pose_world)
            if image_point is None:
                continue
            if -0.1 * width <= image_point.x <= 1.1 * width and -0.1 * height <= image_point.y <= 1.1 * height:
                visible = max(visible, float(s_meters))
    return visible


def _mean_reprojection_error_px(clicked: Sequence[Vector2], reprojected: Sequence[Vector2 | None]) -> float:
    errors: list[float] = []
    for clicked_point, projected_point in zip(clicked, reprojected):
        if projected_point is None:
            continue
        dx = float(clicked_point.x) - float(projected_point.x)
        dy = float(clicked_point.y) - float(projected_point.y)
        errors.append(float(np.hypot(dx, dy)))
    if not errors:
        return float("inf")
    return float(np.mean(np.asarray(errors, dtype=np.float64)))


def _build_manual_lane_geometry(
    points_px: Sequence[Vector2],
    selected_frame: SelectedFrame,
    *,
    floor_plane_point_world: Vector3,
    floor_plane_normal_world: Vector3,
    lane_width_meters: float,
    lane_length_meters: float,
    max_width_error_meters: float,
    max_reprojection_error_px: float,
) -> ManualLaneGeometry:
    if len(points_px) != 4:
        raise RuntimeError("Manual lane injection requires exactly four clicked points.")

    floor_point_np = vector3_to_numpy(floor_plane_point_world)
    floor_normal_np = normalize_vector(vector3_to_numpy(floor_plane_normal_world))
    clicked_world_np = [
        _intersect_image_point_with_floor(
            image_point=point,
            intrinsics=selected_frame.intrinsics,
            frame_state=selected_frame.frame_state,
            floor_point_world=floor_point_np,
            floor_normal_world=floor_normal_np,
        )
        for point in points_px
    ]

    near_left, near_right, far_left, far_right = clicked_world_np
    near_mid = 0.5 * (near_left + near_right)
    far_mid = 0.5 * (far_left + far_right)
    selected_right = near_right - near_left
    selected_right = selected_right - float(np.dot(selected_right, floor_normal_np)) * floor_normal_np
    selected_width_meters = float(np.linalg.norm(selected_right))
    if selected_width_meters <= 1e-6:
        raise RuntimeError("Near left/right clicks collapse to a near-zero lane width on the floor plane.")

    width_error_meters = abs(selected_width_meters - float(lane_width_meters))
    if width_error_meters > float(max_width_error_meters):
        raise RuntimeError(
            f"Clicked foul-line width is {selected_width_meters:.3f}m, expected {lane_width_meters:.3f}m "
            f"(error {width_error_meters:.3f}m > allowed {max_width_error_meters:.3f}m). "
            "This usually means the floor plane assumption is wrong or the near corners were clicked inaccurately."
        )

    right_axis = normalize_vector(selected_right)
    forward_axis = normalize_vector(np.cross(right_axis, floor_normal_np))
    far_direction = far_mid - near_mid
    far_direction = far_direction - float(np.dot(far_direction, floor_normal_np)) * floor_normal_np
    if float(np.linalg.norm(far_direction)) <= 1e-6:
        raise RuntimeError("Far lane-edge clicks do not define a usable downlane direction.")
    far_direction = normalize_vector(far_direction)
    if float(np.dot(forward_axis, far_direction)) < 0.0:
        raise RuntimeError(
            "Clicked far points appear behind the foul line for this floor normal and left/right order. "
            "Check the point order: near-left, near-right, far-left, far-right."
        )

    reprojected_points = [
        world_point_to_image_point(point_world, selected_frame.intrinsics, selected_frame.frame_state.camera_pose_world)
        for point_world in clicked_world_np
    ]
    reprojection_error_px = _mean_reprojection_error_px(points_px, reprojected_points)
    if reprojection_error_px > float(max_reprojection_error_px):
        raise RuntimeError(
            f"Mean clicked-point reprojection error is {reprojection_error_px:.1f}px "
            f"(allowed {max_reprojection_error_px:.1f}px)."
        )

    left_polyline, right_polyline, foul_line_polyline = _project_lane_edges(
        origin_world=near_mid,
        right_axis_world=right_axis,
        forward_axis_world=forward_axis,
        lane_width_meters=lane_width_meters,
        lane_length_meters=lane_length_meters,
        intrinsics=selected_frame.intrinsics,
        frame_state=selected_frame.frame_state,
    )
    visible_downlane_meters = _visible_downlane_meters(
        origin_world=near_mid,
        right_axis_world=right_axis,
        forward_axis_world=forward_axis,
        lane_width_meters=lane_width_meters,
        lane_length_meters=lane_length_meters,
        intrinsics=selected_frame.intrinsics,
        frame_state=selected_frame.frame_state,
    )

    return ManualLaneGeometry(
        clicked_points_px=list(points_px),
        clicked_points_world=[_vector3_from_numpy(point) for point in clicked_world_np],
        lane_origin_world=_vector3_from_numpy(near_mid),
        lane_rotation_world=_build_lane_rotation(right_axis, floor_normal_np, forward_axis),
        right_axis_world=_vector3_from_numpy(right_axis),
        forward_axis_world=_vector3_from_numpy(forward_axis),
        floor_plane_point_world=floor_plane_point_world,
        floor_plane_normal_world=floor_plane_normal_world,
        selected_width_meters=selected_width_meters,
        width_error_meters=width_error_meters,
        visible_downlane_meters=visible_downlane_meters,
        reprojection_error_px=reprojection_error_px,
        projected_left_polyline=left_polyline,
        projected_right_polyline=right_polyline,
        projected_foul_line_polyline=foul_line_polyline,
    )


def _draw_preview(image_bgr: Any, geometry: ManualLaneGeometry) -> Any:
    preview = image_bgr.copy()
    clicked_points = [(int(round(point.x)), int(round(point.y))) for point in geometry.clicked_points_px]
    if len(clicked_points) == 4:
        polygon = np.asarray(
            [clicked_points[0], clicked_points[1], clicked_points[3], clicked_points[2], clicked_points[0]],
            dtype=np.int32,
        )
        cv2.polylines(preview, [polygon], True, (0, 180, 255), 2, cv2.LINE_AA)

    for point, label in zip(clicked_points, ("NL", "NR", "FL", "FR")):
        cv2.circle(preview, point, 6, (0, 180, 255), -1, cv2.LINE_AA)
        cv2.putText(preview, label, (point[0] + 8, point[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 180, 255), 2)

    for polyline, color in (
        (geometry.projected_left_polyline, (80, 255, 80)),
        (geometry.projected_right_polyline, (80, 255, 80)),
        (geometry.projected_foul_line_polyline, (255, 180, 80)),
    ):
        if len(polyline) < 2:
            continue
        points = np.asarray([[int(round(point.x)), int(round(point.y))] for point in polyline], dtype=np.int32)
        cv2.polylines(preview, [points], False, color, 2, cv2.LINE_AA)

    return preview


def _build_lane_result(
    *,
    session_id: str,
    request_id: str,
    selected_frame: SelectedFrame,
    geometry: ManualLaneGeometry,
    lane_width_meters: float,
    lane_length_meters: float,
) -> LaneLockResult:
    visible_extent = min(max(float(geometry.visible_downlane_meters) / max(float(lane_length_meters), 1e-6), 0.0), 1.0)
    width_fit = min(max(1.0 - float(geometry.width_error_meters) / 0.25, 0.0), 1.0)
    confidence = min(max(0.55 + 0.25 * width_fit + 0.20 * visible_extent, 0.0), 1.0)
    return LaneLockResult(
        schema_version="lane_lock_result",
        session_id=session_id,
        request_id=request_id,
        success=True,
        failure_reason="",
        confidence=confidence,
        confidence_breakdown=LaneLockConfidenceBreakdown(
            edge_fit=1.0,
            selection_agreement=width_fit,
            marking_agreement=0.0,
            temporal_stability=1.0,
            candidate_margin=1.0,
            visible_extent=visible_extent,
        ),
        lock_state="candidate_ready",
        requires_confirmation=True,
        user_confirmed=True,
        preview_frame_seq=int(selected_frame.frame_state.frame_seq),
        lane_origin_world=geometry.lane_origin_world,
        lane_rotation_world=geometry.lane_rotation_world,
        lane_width_meters=float(lane_width_meters),
        lane_length_meters=float(lane_length_meters),
        floor_plane_point_world=geometry.floor_plane_point_world,
        floor_plane_normal_world=geometry.floor_plane_normal_world,
        visible_downlane_meters=float(geometry.visible_downlane_meters),
        release_corridor=ReleaseCorridor(
            s_start_meters=0.0,
            s_end_meters=min(2.5, max(float(geometry.visible_downlane_meters), 0.0)),
            half_width_meters=min(0.45, float(lane_width_meters) * 0.5),
        ),
        reprojection_metrics=ReprojectionMetrics(
            mean_error_px=float(geometry.reprojection_error_px),
            p95_error_px=float(geometry.reprojection_error_px),
            runner_up_margin=1.0,
        ),
        source_frame_range=SourceFrameRange(
            start=int(selected_frame.frame_state.frame_seq),
            end=int(selected_frame.frame_state.frame_seq),
        ),
    )


def _write_confirm(session_dir: Path, *, session_id: str, shot_id: str, request_id: str) -> None:
    confirm_path = session_dir / "lane_lock_confirms.jsonl"
    confirm = {
        "kind": "lane_lock_confirm",
        "session_id": session_id,
        "shot_id": shot_id,
        "requestId": request_id,
        "accepted": True,
        "reason": "dev_manual_trapezoid",
    }
    with confirm_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(confirm, separators=(",", ":")) + "\n")


def _write_outputs(
    session_dir: Path,
    *,
    session_id: str,
    shot_id: str,
    request_id: str,
    selected_frame: SelectedFrame,
    geometry: ManualLaneGeometry,
    lane_result: LaneLockResult,
    video_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    output_dir = session_dir / "analysis_lane_lock" / request_id
    preview_path = output_dir / "lane_lock_preview.jpg"
    frame_path = output_dir / "manual_lane_frame.jpg"
    result_path = output_dir / "lane_lock_result.json"
    result_document = {
        "kind": "dev_manual_lane_lock_injection",
        "sessionDir": str(session_dir),
        "videoPath": str(video_path),
        "requestEnvelope": {
            "kind": "dev_manual_lane_lock_injection",
            "session_id": session_id,
            "shot_id": shot_id,
            "lane_lock_request": None,
        },
        "request": None,
        "requestedAnchorFrameSeq": int(selected_frame.frame_state.frame_seq),
        "anchorFrameSeq": int(selected_frame.frame_state.frame_seq),
        "anchorFrameIndex": int(selected_frame.frame.frame_index),
        "anchorFrameMetadata": selected_frame.frame.metadata,
        "previewPath": str(preview_path),
        "devInjection": {
            "clickedPointsPx": [point.to_dict() for point in geometry.clicked_points_px],
            "clickedPointsWorld": [point.to_dict() for point in geometry.clicked_points_world],
            "rightAxisWorld": geometry.right_axis_world.to_dict(),
            "forwardAxisWorld": geometry.forward_axis_world.to_dict(),
            "selectedWidthMeters": float(geometry.selected_width_meters),
            "widthErrorMeters": float(geometry.width_error_meters),
            "reprojectionErrorPx": float(geometry.reprojection_error_px),
            "floorPlaneAssumption": {
                "pointWorld": geometry.floor_plane_point_world.to_dict(),
                "normalWorld": geometry.floor_plane_normal_world.to_dict(),
            },
        },
        "solve": {
            "geometry": {
                "anchorFrameSeq": int(selected_frame.frame_state.frame_seq),
                "leftSelectionFrameSeq": int(selected_frame.frame_state.frame_seq),
                "rightSelectionFrameSeq": int(selected_frame.frame_state.frame_seq),
                "leftFoulLinePointPx": geometry.clicked_points_px[0].to_dict(),
                "rightFoulLinePointPx": geometry.clicked_points_px[1].to_dict(),
                "leftFoulLineWorld": geometry.clicked_points_world[0].to_dict(),
                "rightFoulLineWorld": geometry.clicked_points_world[1].to_dict(),
                "laneOriginWorld": geometry.lane_origin_world.to_dict(),
                "rightAxisWorld": geometry.right_axis_world.to_dict(),
                "forwardAxisWorld": geometry.forward_axis_world.to_dict(),
                "floorNormalWorld": geometry.floor_plane_normal_world.to_dict(),
                "inferredPlanePointWorld": geometry.floor_plane_point_world.to_dict(),
                "laneWidthResidualMeters": float(geometry.width_error_meters),
                "cameraForwardAlignment": 1.0,
                "headForwardAlignment": 1.0,
            },
            "supportSegments": [],
            "projectedLeftPolyline": [point.to_dict() for point in geometry.projected_left_polyline],
            "projectedRightPolyline": [point.to_dict() for point in geometry.projected_right_polyline],
            "projectedFoulLinePolyline": [point.to_dict() for point in geometry.projected_foul_line_polyline],
            "result": lane_result.to_dict(),
        },
    }

    if dry_run:
        return {
            "resultPath": str(result_path),
            "previewPath": str(preview_path),
            "framePath": str(frame_path),
            "resultDocument": result_document,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(frame_path), selected_frame.frame.image_bgr)
    cv2.imwrite(str(preview_path), _draw_preview(selected_frame.frame.image_bgr, geometry))
    result_path.write_text(json.dumps(result_document, indent=2), encoding="utf-8")
    _write_confirm(session_dir, session_id=session_id, shot_id=shot_id, request_id=request_id)
    mark_lane(
        session_dir,
        LANE_CONFIRMED,
        confirmedRequestId=request_id,
        activeRequestId="",
        candidateRequestId=request_id,
        candidateResultPath=str(result_path),
        confirmedResultPath=str(result_path),
        lastFailureReason="",
    )
    mark_shot(
        session_dir,
        SHOT_ARMED,
        activeLaneLockRequestId=request_id,
        candidateStartFrameSeq=None,
        openWindowId="",
        openFrameSeqStart=None,
        openFrameSeqEnd=None,
        lastFailureReason="",
        lastReason="dev_manual_lane_injected",
    )
    return {
        "resultPath": str(result_path),
        "previewPath": str(preview_path),
        "framePath": str(frame_path),
        "resultDocument": result_document,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dev-only lane injector. Click a lane trapezoid on one decoded Quest frame and write a confirmed "
            "lane_lock_result so the post-lane live pipeline can be tested."
        )
    )
    parser.add_argument("session_dir", type=Path, help="Incoming live session directory.")
    parser.add_argument("--frame-index", type=int, default=None, help="Decoded frame index to use. Skips the frame browser.")
    parser.add_argument("--frame-seq", type=int, default=None, help="FrameSeq to use instead of --frame-index. Skips the frame browser.")
    parser.add_argument("--request-id", default="", help="Request id to inject. Defaults to dev_manual_lane_<unix_ms>.")
    parser.add_argument("--lane-width-meters", type=float, default=DEFAULT_LANE_WIDTH_METERS)
    parser.add_argument("--lane-length-meters", type=float, default=DEFAULT_LANE_LENGTH_METERS)
    parser.add_argument("--floor-point-world", type=_float_triplet, default=Vector3(0.0, 0.0, 0.0))
    parser.add_argument("--floor-normal-world", type=_float_triplet, default=Vector3(0.0, 1.0, 0.0))
    parser.add_argument("--max-width-error-meters", type=float, default=0.25)
    parser.add_argument("--max-reprojection-error-px", type=float, default=2.0)
    parser.add_argument("--max-display-width", type=int, default=DEFAULT_MAX_DISPLAY_WIDTH)
    parser.add_argument("--max-display-height", type=int, default=DEFAULT_MAX_DISPLAY_HEIGHT)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print output paths without writing files.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.frame_index is not None and args.frame_seq is not None:
        raise RuntimeError("Use either --frame-index or --frame-seq, not both.")

    session_dir = args.session_dir.expanduser().resolve()
    artifact = load_local_clip_artifact(session_dir)
    session_id, shot_id = _session_identity(artifact)
    if args.frame_index is None and args.frame_seq is None:
        selected_frame = _choose_frame_interactive(
            artifact,
            max_display_width=int(args.max_display_width),
            max_display_height=int(args.max_display_height),
        )
    else:
        selected_frame = _select_frame(artifact, frame_index=args.frame_index, frame_seq=args.frame_seq)
    points = _collect_points_interactive(
        selected_frame.frame.image_bgr,
        max_display_width=int(args.max_display_width),
        max_display_height=int(args.max_display_height),
    )
    request_id = str(args.request_id or f"dev_manual_lane_{int(time.time() * 1000)}").strip()

    geometry = _build_manual_lane_geometry(
        points,
        selected_frame,
        floor_plane_point_world=args.floor_point_world,
        floor_plane_normal_world=args.floor_normal_world,
        lane_width_meters=float(args.lane_width_meters),
        lane_length_meters=float(args.lane_length_meters),
        max_width_error_meters=float(args.max_width_error_meters),
        max_reprojection_error_px=float(args.max_reprojection_error_px),
    )
    lane_result = _build_lane_result(
        session_id=session_id,
        request_id=request_id,
        selected_frame=selected_frame,
        geometry=geometry,
        lane_width_meters=float(args.lane_width_meters),
        lane_length_meters=float(args.lane_length_meters),
    )
    outputs = _write_outputs(
        session_dir,
        session_id=session_id,
        shot_id=shot_id,
        request_id=request_id,
        selected_frame=selected_frame,
        geometry=geometry,
        lane_result=lane_result,
        video_path=artifact.video_path,
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "kind": "dev_manual_lane_injection",
                "dryRun": bool(args.dry_run),
                "sessionDir": str(session_dir),
                "sessionId": session_id,
                "shotId": shot_id,
                "requestId": request_id,
                "selectedFrame": selected_frame.source,
                "selectedWidthMeters": geometry.selected_width_meters,
                "widthErrorMeters": geometry.width_error_meters,
                "visibleDownlaneMeters": geometry.visible_downlane_meters,
                "reprojectionErrorPx": geometry.reprojection_error_px,
                "laneOriginWorld": geometry.lane_origin_world.to_dict(),
                "rightAxisWorld": geometry.right_axis_world.to_dict(),
                "forwardAxisWorld": geometry.forward_axis_world.to_dict(),
                "resultPath": outputs["resultPath"],
                "previewPath": outputs["previewPath"],
                "framePath": outputs["framePath"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
