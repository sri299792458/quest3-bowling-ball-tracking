from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import cv2
import numpy as np

from laptop_receiver.lane_geometry import (
    camera_ray_to_world_ray,
    image_point_to_camera_ray,
    normalize_vector,
    rotate_vector,
    vector3_to_numpy,
    world_point_to_image_point,
)
from laptop_receiver.lane_line_support import LaneSupportSegment
from laptop_receiver.lane_lock_types import (
    CameraIntrinsics,
    FrameCameraState,
    LaneLockConfidenceBreakdown,
    LaneLockRequest,
    LaneLockResult,
    Quaternion,
    ReleaseCorridor,
    ReprojectionMetrics,
    SourceFrameRange,
    Vector2,
    Vector3,
)


@dataclass(frozen=True)
class FoulLineLaneLockGeometry:
    selection_frame_seq: int
    left_foul_line_point_px: Vector2
    right_foul_line_point_px: Vector2
    left_foul_line_world: Vector3
    right_foul_line_world: Vector3
    lane_origin_world: Vector3
    right_axis_world: Vector3
    forward_axis_world: Vector3
    floor_normal_world: Vector3
    inferred_plane_point_world: Vector3
    lane_width_residual_meters: float
    camera_forward_alignment: float
    head_forward_alignment: float

    def to_dict(self) -> dict[str, object]:
        return {
            "selectionFrameSeq": self.selection_frame_seq,
            "leftFoulLinePointPx": self.left_foul_line_point_px.to_dict(),
            "rightFoulLinePointPx": self.right_foul_line_point_px.to_dict(),
            "leftFoulLineWorld": self.left_foul_line_world.to_dict(),
            "rightFoulLineWorld": self.right_foul_line_world.to_dict(),
            "laneOriginWorld": self.lane_origin_world.to_dict(),
            "rightAxisWorld": self.right_axis_world.to_dict(),
            "forwardAxisWorld": self.forward_axis_world.to_dict(),
            "floorNormalWorld": self.floor_normal_world.to_dict(),
            "inferredPlanePointWorld": self.inferred_plane_point_world.to_dict(),
            "laneWidthResidualMeters": self.lane_width_residual_meters,
            "cameraForwardAlignment": self.camera_forward_alignment,
            "headForwardAlignment": self.head_forward_alignment,
        }


@dataclass(frozen=True)
class LaneLockSolveOutput:
    geometry: FoulLineLaneLockGeometry
    support_segments: list[LaneSupportSegment]
    projected_left_polyline: list[Vector2]
    projected_right_polyline: list[Vector2]
    projected_foul_line_polyline: list[Vector2]
    result: LaneLockResult

    def to_dict(self) -> dict[str, object]:
        return {
            "geometry": self.geometry.to_dict(),
            "supportSegments": [segment.to_dict() for segment in self.support_segments],
            "projectedLeftPolyline": [point.to_dict() for point in self.projected_left_polyline],
            "projectedRightPolyline": [point.to_dict() for point in self.projected_right_polyline],
            "projectedFoulLinePolyline": [point.to_dict() for point in self.projected_foul_line_polyline],
            "result": self.result.to_dict(),
        }


def _normalized_point_to_pixel(point_norm: Vector2, width: int, height: int, field_name: str) -> Vector2:
    if not (0.0 <= float(point_norm.x) <= 1.0 and 0.0 <= float(point_norm.y) <= 1.0):
        raise RuntimeError(f"{field_name} must be normalized into [0, 1].")
    return Vector2(
        x=float(point_norm.x) * float(max(int(width) - 1, 1)),
        y=float(point_norm.y) * float(max(int(height) - 1, 1)),
    )


def _vector3_from_numpy(values: np.ndarray) -> Vector3:
    return Vector3(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _select_frame_state(frame_states: Sequence[FrameCameraState], frame_seq: int) -> FrameCameraState:
    for frame_state in frame_states:
        if int(frame_state.frame_seq) == int(frame_seq):
            return frame_state
    raise RuntimeError(f"Selection frame {frame_seq} is missing from the lane-lock frame metadata.")


def _rotation_forward_world(frame_state: FrameCameraState, source: str) -> np.ndarray:
    pose = frame_state.head_pose_world if source == "head" else frame_state.camera_pose_world
    return normalize_vector(rotate_vector(pose.rotation, np.asarray([0.0, 0.0, 1.0], dtype=np.float64)))


def _project_direction_onto_plane(direction_world: np.ndarray, plane_normal_world: np.ndarray) -> np.ndarray:
    direction = np.asarray(direction_world, dtype=np.float64)
    normal = normalize_vector(np.asarray(plane_normal_world, dtype=np.float64))
    projected = direction - float(np.dot(direction, normal)) * normal
    return normalize_vector(projected)


def _quaternion_from_rotation_matrix(rotation_matrix: np.ndarray) -> Quaternion:
    matrix = np.asarray(rotation_matrix, dtype=np.float64)
    trace = float(matrix[0, 0] + matrix[1, 1] + matrix[2, 2])
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (matrix[2, 1] - matrix[1, 2]) / scale
        y = (matrix[0, 2] - matrix[2, 0]) / scale
        z = (matrix[1, 0] - matrix[0, 1]) / scale
    elif matrix[0, 0] > matrix[1, 1] and matrix[0, 0] > matrix[2, 2]:
        scale = np.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
        w = (matrix[2, 1] - matrix[1, 2]) / scale
        x = 0.25 * scale
        y = (matrix[0, 1] + matrix[1, 0]) / scale
        z = (matrix[0, 2] + matrix[2, 0]) / scale
    elif matrix[1, 1] > matrix[2, 2]:
        scale = np.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
        w = (matrix[0, 2] - matrix[2, 0]) / scale
        x = (matrix[0, 1] + matrix[1, 0]) / scale
        y = 0.25 * scale
        z = (matrix[1, 2] + matrix[2, 1]) / scale
    else:
        scale = np.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
        w = (matrix[1, 0] - matrix[0, 1]) / scale
        x = (matrix[0, 2] + matrix[2, 0]) / scale
        y = (matrix[1, 2] + matrix[2, 1]) / scale
        z = 0.25 * scale

    quaternion = np.asarray([x, y, z, w], dtype=np.float64)
    quaternion = quaternion / max(float(np.linalg.norm(quaternion)), 1e-8)
    return Quaternion(
        x=float(quaternion[0]),
        y=float(quaternion[1]),
        z=float(quaternion[2]),
        w=float(quaternion[3]),
    )


def _build_lane_rotation(right_axis_world: np.ndarray, floor_normal_world: np.ndarray, forward_axis_world: np.ndarray) -> Quaternion:
    rotation_matrix = np.column_stack((right_axis_world, floor_normal_world, forward_axis_world))
    return _quaternion_from_rotation_matrix(rotation_matrix)


def _solve_foul_line_geometry(
    request: LaneLockRequest,
    intrinsics: CameraIntrinsics,
    selection_frame: FrameCameraState,
) -> FoulLineLaneLockGeometry:
    if float(request.lane_width_meters) <= 0.0 or float(request.lane_length_meters) <= 0.0:
        raise RuntimeError("Lane dimensions must be positive.")
    if float(request.left_foul_line_point_norm.x) >= float(request.right_foul_line_point_norm.x):
        raise RuntimeError("leftFoulLinePointNorm must be left of rightFoulLinePointNorm in image space.")

    width = int(selection_frame.width or intrinsics.width or request.image_width)
    height = int(selection_frame.height or intrinsics.height or request.image_height)
    left_px = _normalized_point_to_pixel(request.left_foul_line_point_norm, width, height, "leftFoulLinePointNorm")
    right_px = _normalized_point_to_pixel(request.right_foul_line_point_norm, width, height, "rightFoulLinePointNorm")

    floor_normal = normalize_vector(vector3_to_numpy(request.floor_plane_normal_world))
    left_camera_ray = image_point_to_camera_ray(left_px, intrinsics)
    right_camera_ray = image_point_to_camera_ray(right_px, intrinsics)
    ray_origin, left_world_ray = camera_ray_to_world_ray(left_camera_ray, selection_frame.camera_pose_world)
    _, right_world_ray = camera_ray_to_world_ray(right_camera_ray, selection_frame.camera_pose_world)

    left_denom = float(np.dot(floor_normal, left_world_ray))
    right_denom = float(np.dot(floor_normal, right_world_ray))
    if abs(left_denom) <= 1e-8 or abs(right_denom) <= 1e-8:
        raise RuntimeError("One selected foul-line ray is nearly parallel to the floor plane.")

    scale_vector = (right_world_ray / right_denom) - (left_world_ray / left_denom)
    scale_norm = float(np.linalg.norm(scale_vector))
    if scale_norm <= 1e-8:
        raise RuntimeError("Selected foul-line rays do not form a stable lane-width solve.")

    lane_width = float(request.lane_width_meters)
    viable_alphas: list[float] = []
    for alpha in (lane_width / scale_norm, -lane_width / scale_norm):
        left_t = float(alpha / left_denom)
        right_t = float(alpha / right_denom)
        if left_t > 0.0 and right_t > 0.0 and alpha < 0.0:
            viable_alphas.append(float(alpha))

    if not viable_alphas:
        raise RuntimeError("Foul-line width solve did not produce a lane plane below the camera.")

    alpha = sorted(viable_alphas, key=abs)[0]
    left_world = ray_origin + (alpha / left_denom) * left_world_ray
    right_world = ray_origin + (alpha / right_denom) * right_world_ray
    inferred_plane_point_world = ray_origin + alpha * floor_normal

    selected_width = right_world - left_world
    selected_width_on_plane = selected_width - float(np.dot(selected_width, floor_normal)) * floor_normal
    right_axis = normalize_vector(selected_width_on_plane)

    camera_forward = _project_direction_onto_plane(_rotation_forward_world(selection_frame, "camera"), floor_normal)
    head_forward = _project_direction_onto_plane(_rotation_forward_world(selection_frame, "head"), floor_normal)
    forward_axis = normalize_vector(np.cross(right_axis, floor_normal))
    if float(np.dot(forward_axis, head_forward)) < 0.0 and float(np.dot(forward_axis, camera_forward)) < 0.0:
        forward_axis = -forward_axis
    right_axis = normalize_vector(np.cross(floor_normal, forward_axis))

    lane_origin = 0.5 * (left_world + right_world)
    lane_width_residual = abs(float(np.linalg.norm(right_world - left_world)) - lane_width)

    return FoulLineLaneLockGeometry(
        selection_frame_seq=int(selection_frame.frame_seq),
        left_foul_line_point_px=left_px,
        right_foul_line_point_px=right_px,
        left_foul_line_world=_vector3_from_numpy(left_world),
        right_foul_line_world=_vector3_from_numpy(right_world),
        lane_origin_world=_vector3_from_numpy(lane_origin),
        right_axis_world=_vector3_from_numpy(right_axis),
        forward_axis_world=_vector3_from_numpy(forward_axis),
        floor_normal_world=_vector3_from_numpy(floor_normal),
        inferred_plane_point_world=_vector3_from_numpy(inferred_plane_point_world),
        lane_width_residual_meters=lane_width_residual,
        camera_forward_alignment=float(np.dot(forward_axis, camera_forward)),
        head_forward_alignment=float(np.dot(forward_axis, head_forward)),
    )


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


def _project_lane_polylines(
    geometry: FoulLineLaneLockGeometry,
    request: LaneLockRequest,
    intrinsics: CameraIntrinsics,
    frame_state: FrameCameraState,
    sample_count: int = 32,
) -> tuple[list[Vector2], list[Vector2], list[Vector2]]:
    origin = vector3_to_numpy(geometry.lane_origin_world)
    right_axis = vector3_to_numpy(geometry.right_axis_world)
    forward_axis = vector3_to_numpy(geometry.forward_axis_world)
    samples = np.linspace(0.0, float(request.lane_length_meters), int(sample_count), dtype=np.float64)

    left_polyline: list[Vector2] = []
    right_polyline: list[Vector2] = []
    for s_meters in samples:
        left_point = _lane_world_point(origin, right_axis, forward_axis, request.lane_width_meters, -1.0, float(s_meters))
        right_point = _lane_world_point(origin, right_axis, forward_axis, request.lane_width_meters, 1.0, float(s_meters))
        left_image = world_point_to_image_point(left_point, intrinsics, frame_state.camera_pose_world)
        right_image = world_point_to_image_point(right_point, intrinsics, frame_state.camera_pose_world)
        if left_image is not None:
            left_polyline.append(left_image)
        if right_image is not None:
            right_polyline.append(right_image)

    foul_left = _lane_world_point(origin, right_axis, forward_axis, request.lane_width_meters, -1.0, 0.0)
    foul_right = _lane_world_point(origin, right_axis, forward_axis, request.lane_width_meters, 1.0, 0.0)
    foul_line_polyline = [
        image_point
        for image_point in (
            world_point_to_image_point(foul_left, intrinsics, frame_state.camera_pose_world),
            world_point_to_image_point(foul_right, intrinsics, frame_state.camera_pose_world),
        )
        if image_point is not None
    ]
    return left_polyline, right_polyline, foul_line_polyline


def _visible_downlane_meters(
    geometry: FoulLineLaneLockGeometry,
    request: LaneLockRequest,
    intrinsics: CameraIntrinsics,
    frame_state: FrameCameraState,
) -> float:
    origin = vector3_to_numpy(geometry.lane_origin_world)
    right_axis = vector3_to_numpy(geometry.right_axis_world)
    forward_axis = vector3_to_numpy(geometry.forward_axis_world)
    width = int(frame_state.width or intrinsics.width)
    height = int(frame_state.height or intrinsics.height)
    visible = 0.0
    for s_meters in np.linspace(0.0, float(request.lane_length_meters), 48, dtype=np.float64):
        for lateral_sign in (-1.0, 1.0):
            world_point = _lane_world_point(
                origin,
                right_axis,
                forward_axis,
                request.lane_width_meters,
                lateral_sign,
                float(s_meters),
            )
            image_point = world_point_to_image_point(world_point, intrinsics, frame_state.camera_pose_world)
            if image_point is None:
                continue
            if -0.1 * width <= image_point.x <= 1.1 * width and -0.1 * height <= image_point.y <= 1.1 * height:
                visible = max(visible, float(s_meters))
    return visible


def _distance_map_from_support_segments(
    image_width: int,
    image_height: int,
    support_segments: Sequence[LaneSupportSegment],
) -> np.ndarray | None:
    if not support_segments:
        return None
    support_mask = np.zeros((int(image_height), int(image_width)), dtype=np.uint8)
    for segment in support_segments:
        x1, y1, x2, y2 = segment.line_xyxy
        cv2.line(support_mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, 2, cv2.LINE_AA)
    return cv2.distanceTransform(255 - support_mask, cv2.DIST_L2, 3)


def _sample_polyline_distances(polyline: Sequence[Vector2], distance_map: np.ndarray, sample_spacing_px: float = 32.0) -> list[float]:
    if len(polyline) < 2:
        return []
    height, width = distance_map.shape[:2]
    distances: list[float] = []
    for index in range(len(polyline) - 1):
        start = np.asarray([float(polyline[index].x), float(polyline[index].y)], dtype=np.float64)
        end = np.asarray([float(polyline[index + 1].x), float(polyline[index + 1].y)], dtype=np.float64)
        segment = end - start
        length = float(np.linalg.norm(segment))
        if length <= 1e-6:
            continue
        sample_count = max(2, int(np.ceil(length / max(float(sample_spacing_px), 1.0))))
        for step in range(sample_count + 1):
            t = float(step) / float(sample_count)
            point = start * (1.0 - t) + end * t
            x = int(round(float(point[0])))
            y = int(round(float(point[1])))
            if 0 <= x < width and 0 <= y < height:
                distances.append(float(distance_map[y, x]))
    return distances


def _compute_reprojection_metrics(
    support_segments: Sequence[LaneSupportSegment],
    left_polyline: Sequence[Vector2],
    right_polyline: Sequence[Vector2],
    image_width: int,
    image_height: int,
) -> ReprojectionMetrics:
    distance_map = _distance_map_from_support_segments(image_width, image_height, support_segments)
    if distance_map is None:
        return ReprojectionMetrics(mean_error_px=0.0, p95_error_px=0.0, runner_up_margin=1.0)

    distances = (
        _sample_polyline_distances(left_polyline, distance_map)
        + _sample_polyline_distances(right_polyline, distance_map)
    )
    if not distances:
        return ReprojectionMetrics(mean_error_px=0.0, p95_error_px=0.0, runner_up_margin=1.0)

    values = np.asarray(distances, dtype=np.float64)
    return ReprojectionMetrics(
        mean_error_px=float(np.mean(values)),
        p95_error_px=float(np.percentile(values, 95)),
        runner_up_margin=1.0,
    )


def solve_lane_lock_from_image(
    request: LaneLockRequest,
    intrinsics: CameraIntrinsics,
    frame_states: Sequence[FrameCameraState],
    support_segments_by_frame: Mapping[int, Sequence[LaneSupportSegment]],
) -> LaneLockSolveOutput:
    if not frame_states:
        raise RuntimeError("Lane lock requires frame metadata.")

    selection_frame = _select_frame_state(frame_states, int(request.selection_frame_seq))
    geometry = _solve_foul_line_geometry(request, intrinsics, selection_frame)
    support_segments = list(support_segments_by_frame.get(int(selection_frame.frame_seq), []))
    left_polyline, right_polyline, foul_line_polyline = _project_lane_polylines(
        geometry,
        request,
        intrinsics,
        selection_frame,
    )
    visible_downlane_meters = _visible_downlane_meters(geometry, request, intrinsics, selection_frame)
    reprojection_metrics = _compute_reprojection_metrics(
        support_segments,
        left_polyline,
        right_polyline,
        int(selection_frame.width or intrinsics.width),
        int(selection_frame.height or intrinsics.height),
    )

    edge_fit = 1.0 if reprojection_metrics.mean_error_px <= 0.0 else _clamp01(1.0 - reprojection_metrics.mean_error_px / 24.0)
    visible_extent = _clamp01(visible_downlane_meters / max(float(request.lane_length_meters), 1e-6))
    width_fit = _clamp01(1.0 - geometry.lane_width_residual_meters / 0.01)
    direction_agreement = _clamp01(max(geometry.head_forward_alignment, geometry.camera_forward_alignment))

    confidence_breakdown = LaneLockConfidenceBreakdown(
        edge_fit=edge_fit,
        selection_agreement=width_fit,
        marking_agreement=0.0,
        temporal_stability=direction_agreement,
        candidate_margin=1.0,
        visible_extent=visible_extent,
    )
    confidence = _clamp01(
        (
            0.7 * edge_fit
            + 1.0 * width_fit
            + 0.7 * direction_agreement
            + 0.6 * visible_extent
            + 0.5
        )
        / 3.5
    )

    floor_normal = vector3_to_numpy(geometry.floor_normal_world)
    right_axis = vector3_to_numpy(geometry.right_axis_world)
    forward_axis = vector3_to_numpy(geometry.forward_axis_world)
    result = LaneLockResult(
        schema_version="lane_lock_result",
        session_id=request.session_id,
        request_id=request.request_id,
        success=True,
        failure_reason="",
        confidence=confidence,
        confidence_breakdown=confidence_breakdown,
        lock_state="candidate_ready",
        requires_confirmation=True,
        user_confirmed=False,
        preview_frame_seq=int(selection_frame.frame_seq),
        lane_origin_world=geometry.lane_origin_world,
        lane_rotation_world=_build_lane_rotation(right_axis, floor_normal, forward_axis),
        lane_width_meters=float(request.lane_width_meters),
        lane_length_meters=float(request.lane_length_meters),
        floor_plane_point_world=geometry.inferred_plane_point_world,
        floor_plane_normal_world=geometry.floor_normal_world,
        visible_downlane_meters=visible_downlane_meters,
        release_corridor=ReleaseCorridor(
            s_start_meters=0.0,
            s_end_meters=min(2.5, max(visible_downlane_meters, 0.0)),
            half_width_meters=min(0.45, float(request.lane_width_meters) * 0.5),
        ),
        reprojection_metrics=reprojection_metrics,
        source_frame_range=SourceFrameRange(
            start=int(request.frame_seq_start),
            end=int(request.frame_seq_end),
        ),
    )
    return LaneLockSolveOutput(
        geometry=geometry,
        support_segments=support_segments,
        projected_left_polyline=left_polyline,
        projected_right_polyline=right_polyline,
        projected_foul_line_polyline=foul_line_polyline,
        result=result,
    )
