from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from laptop_receiver.lane_lock_types import (
    CameraIntrinsics,
    FrameCameraState,
    LaneLockResult,
    LanePoint,
    LaneSpaceBallPoint,
    Pose3D,
    Quaternion,
    Vector2,
    Vector3,
)


EPSILON = 1e-8


def vector3_to_numpy(vector: Vector3) -> np.ndarray:
    return np.asarray([vector.x, vector.y, vector.z], dtype=np.float64)


def quaternion_to_numpy(quaternion: Quaternion) -> np.ndarray:
    return np.asarray([quaternion.x, quaternion.y, quaternion.z, quaternion.w], dtype=np.float64)


def normalize_vector(vector: np.ndarray, epsilon: float = EPSILON) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= float(epsilon):
        raise ValueError("Cannot normalize a near-zero vector.")
    return vector / norm


def quaternion_to_rotation_matrix(quaternion: Quaternion) -> np.ndarray:
    x, y, z, w = quaternion_to_numpy(quaternion)
    norm = x * x + y * y + z * z + w * w
    if norm <= EPSILON:
        raise ValueError("Quaternion norm is zero.")

    s = 2.0 / norm
    xx = x * x * s
    yy = y * y * s
    zz = z * z * s
    xy = x * y * s
    xz = x * z * s
    yz = y * z * s
    wx = w * x * s
    wy = w * y * s
    wz = w * z * s

    return np.asarray(
        [
            [1.0 - (yy + zz), xy - wz, xz + wy],
            [xy + wz, 1.0 - (xx + zz), yz - wx],
            [xz - wy, yz + wx, 1.0 - (xx + yy)],
        ],
        dtype=np.float64,
    )


def rotate_vector(quaternion: Quaternion, vector: np.ndarray) -> np.ndarray:
    return quaternion_to_rotation_matrix(quaternion) @ np.asarray(vector, dtype=np.float64)


def image_point_to_camera_ray(image_point_px: Vector2, intrinsics: CameraIntrinsics) -> np.ndarray:
    if intrinsics.fx == 0.0 or intrinsics.fy == 0.0:
        raise ValueError("Camera intrinsics must have non-zero focal lengths.")

    # Unity world/camera poses use +Y up, while image-space v grows downward.
    direction = np.asarray(
        [
            (float(image_point_px.x) - float(intrinsics.cx)) / float(intrinsics.fx),
            -(float(image_point_px.y) - float(intrinsics.cy)) / float(intrinsics.fy),
            1.0,
        ],
        dtype=np.float64,
    )
    return normalize_vector(direction)


def camera_ray_to_world_ray(camera_ray_c: np.ndarray, camera_pose_world: Pose3D) -> tuple[np.ndarray, np.ndarray]:
    origin_world = vector3_to_numpy(camera_pose_world.position)
    direction_world = rotate_vector(camera_pose_world.rotation, camera_ray_c)
    return origin_world, normalize_vector(direction_world)


def world_point_to_image_point(
    world_point: np.ndarray,
    intrinsics: CameraIntrinsics,
    camera_pose_world: Pose3D,
) -> Vector2 | None:
    point_world = np.asarray(world_point, dtype=np.float64)
    camera_origin_world = vector3_to_numpy(camera_pose_world.position)
    rotation_world_from_camera = quaternion_to_rotation_matrix(camera_pose_world.rotation)
    rotation_camera_from_world = rotation_world_from_camera.T
    point_camera = rotation_camera_from_world @ (point_world - camera_origin_world)

    z = float(point_camera[2])
    if z <= EPSILON:
        return None

    u = float(intrinsics.fx) * float(point_camera[0]) / z + float(intrinsics.cx)
    v = -float(intrinsics.fy) * float(point_camera[1]) / z + float(intrinsics.cy)
    return Vector2(x=u, y=v)


@dataclass(frozen=True)
class RayPlaneIntersection:
    point_world: np.ndarray
    ray_parameter_t: float


def intersect_ray_plane(
    ray_origin_world: np.ndarray,
    ray_direction_world: np.ndarray,
    plane_point_world: np.ndarray,
    plane_normal_world: np.ndarray,
    epsilon: float = EPSILON,
) -> RayPlaneIntersection | None:
    normal = normalize_vector(np.asarray(plane_normal_world, dtype=np.float64), epsilon=epsilon)
    origin = np.asarray(ray_origin_world, dtype=np.float64)
    direction = normalize_vector(np.asarray(ray_direction_world, dtype=np.float64), epsilon=epsilon)
    plane_point = np.asarray(plane_point_world, dtype=np.float64)

    denominator = float(np.dot(normal, direction))
    if abs(denominator) <= float(epsilon):
        return None

    t = float(np.dot(normal, plane_point - origin) / denominator)
    if t <= 0.0:
        return None

    point_world = origin + t * direction
    return RayPlaneIntersection(point_world=point_world, ray_parameter_t=t)


@dataclass(frozen=True)
class LaneBasis:
    origin_world: np.ndarray
    right_axis_world: np.ndarray
    up_axis_world: np.ndarray
    downlane_axis_world: np.ndarray


def lane_basis_from_lock(lane_lock: LaneLockResult) -> LaneBasis:
    origin_world = vector3_to_numpy(lane_lock.lane_origin_world)
    up_axis_world = normalize_vector(vector3_to_numpy(lane_lock.floor_plane_normal_world))
    nominal_downlane_world = normalize_vector(
        rotate_vector(lane_lock.lane_rotation_world, np.asarray([0.0, 0.0, 1.0], dtype=np.float64))
    )
    nominal_right_world = normalize_vector(
        rotate_vector(lane_lock.lane_rotation_world, np.asarray([1.0, 0.0, 0.0], dtype=np.float64))
    )

    downlane_projection = nominal_downlane_world - float(np.dot(nominal_downlane_world, up_axis_world)) * up_axis_world
    if float(np.linalg.norm(downlane_projection)) <= EPSILON:
        downlane_projection = nominal_right_world - float(np.dot(nominal_right_world, up_axis_world)) * up_axis_world
    downlane_axis_world = normalize_vector(downlane_projection)
    right_axis_world = normalize_vector(np.cross(up_axis_world, downlane_axis_world))

    return LaneBasis(
        origin_world=origin_world,
        right_axis_world=right_axis_world,
        up_axis_world=up_axis_world,
        downlane_axis_world=downlane_axis_world,
    )


def lane_plane_from_lock(lane_lock: LaneLockResult) -> tuple[np.ndarray, np.ndarray]:
    return vector3_to_numpy(lane_lock.floor_plane_point_world), normalize_vector(vector3_to_numpy(lane_lock.floor_plane_normal_world))


def world_point_to_lane_coordinates(world_point: np.ndarray, lane_lock: LaneLockResult) -> LanePoint:
    basis = lane_basis_from_lock(lane_lock)
    delta = np.asarray(world_point, dtype=np.float64) - basis.origin_world
    return LanePoint(
        x_meters=float(np.dot(delta, basis.right_axis_world)),
        s_meters=float(np.dot(delta, basis.downlane_axis_world)),
        h_meters=float(np.dot(delta, basis.up_axis_world)),
    )


def is_lane_point_plausible(
    lane_point: LanePoint,
    lane_lock: LaneLockResult,
    lateral_margin_meters: float = 0.10,
    downlane_margin_meters: float = 0.25,
) -> bool:
    half_width = float(lane_lock.lane_width_meters) * 0.5 + float(lateral_margin_meters)
    if abs(float(lane_point.x_meters)) > half_width:
        return False

    visible_limit = float(lane_lock.visible_downlane_meters or lane_lock.lane_length_meters)
    if float(lane_point.s_meters) < -float(downlane_margin_meters):
        return False
    if float(lane_point.s_meters) > visible_limit + float(downlane_margin_meters):
        return False
    return True


def lane_projection_confidence(lane_point: LanePoint, lane_lock: LaneLockResult) -> float:
    half_width = max(float(lane_lock.lane_width_meters) * 0.5, EPSILON)
    visible_limit = max(float(lane_lock.visible_downlane_meters or lane_lock.lane_length_meters), EPSILON)

    lateral_penalty = min(abs(float(lane_point.x_meters)) / half_width, 1.5)
    downlane_penalty = 0.0
    if float(lane_point.s_meters) < 0.0:
        downlane_penalty = min(abs(float(lane_point.s_meters)) / max(0.5, visible_limit), 1.0)
    elif float(lane_point.s_meters) > visible_limit:
        downlane_penalty = min((float(lane_point.s_meters) - visible_limit) / max(0.5, visible_limit), 1.0)

    height_penalty = min(abs(float(lane_point.h_meters)) / 0.05, 1.0)
    base = float(lane_lock.confidence)
    confidence = base * max(0.0, 1.0 - 0.35 * lateral_penalty - 0.35 * downlane_penalty - 0.30 * height_penalty)
    return max(0.0, min(1.0, confidence))


def project_image_point_to_lane(
    image_point_px: Vector2,
    intrinsics: CameraIntrinsics,
    frame_camera_state: FrameCameraState,
    lane_lock: LaneLockResult,
) -> tuple[np.ndarray, LanePoint, bool, float]:
    ray_camera = image_point_to_camera_ray(image_point_px, intrinsics)
    ray_origin_world, ray_direction_world = camera_ray_to_world_ray(ray_camera, frame_camera_state.camera_pose_world)
    plane_point_world, plane_normal_world = lane_plane_from_lock(lane_lock)
    intersection = intersect_ray_plane(ray_origin_world, ray_direction_world, plane_point_world, plane_normal_world)
    if intersection is None:
        raise RuntimeError("Image ray did not intersect the locked lane plane.")

    lane_point = world_point_to_lane_coordinates(intersection.point_world, lane_lock)
    is_plausible = is_lane_point_plausible(lane_point, lane_lock)
    confidence = lane_projection_confidence(lane_point, lane_lock)
    return intersection.point_world, lane_point, is_plausible, confidence


def project_ball_image_point_to_lane_space(
    session_id: str,
    shot_id: str,
    image_point_px: Vector2,
    frame_camera_state: FrameCameraState,
    intrinsics: CameraIntrinsics,
    lane_lock: LaneLockResult,
    point_definition: str = "bottom_contact_proxy",
) -> LaneSpaceBallPoint:
    world_point_np, lane_point, is_plausible, confidence = project_image_point_to_lane(
        image_point_px=image_point_px,
        intrinsics=intrinsics,
        frame_camera_state=frame_camera_state,
        lane_lock=lane_lock,
    )
    world_point = Vector3(
        x=float(world_point_np[0]),
        y=float(world_point_np[1]),
        z=float(world_point_np[2]),
    )
    return LaneSpaceBallPoint(
        schema_version="lane_space_ball_point",
        session_id=str(session_id),
        shot_id=str(shot_id),
        frame_seq=int(frame_camera_state.frame_seq),
        camera_timestamp_us=int(frame_camera_state.camera_timestamp_us),
        pts_us=int(frame_camera_state.pts_us),
        image_point_px=image_point_px,
        point_definition=point_definition,
        world_point=world_point,
        lane_point=lane_point,
        is_on_locked_lane=is_plausible,
        projection_confidence=confidence,
    )


def bottom_center_from_box(box_xyxy: list[float] | tuple[float, float, float, float]) -> Vector2:
    if len(box_xyxy) != 4:
        raise ValueError("Expected [x1, y1, x2, y2] box coordinates.")
    x1, y1, x2, y2 = (float(value) for value in box_xyxy)
    return Vector2(x=(x1 + x2) * 0.5, y=y2)


def frame_camera_state_from_metadata(frame_metadata: dict[str, Any]) -> FrameCameraState:
    return FrameCameraState.from_frame_metadata(frame_metadata)
