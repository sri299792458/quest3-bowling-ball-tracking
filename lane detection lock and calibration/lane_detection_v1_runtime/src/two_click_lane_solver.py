from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .edge_refinement import build_edge_context, score_lane_projection
from .frame_dataset import FrameRecord
from .world_projection import (
    CameraIntrinsics,
    LaneDimensions,
    project_world_points,
    quaternion_xyzw_to_rotation_matrix,
)


WORLD_UP = np.array([0.0, 1.0, 0.0], dtype=np.float64)
POINT_ORDER = ["near_left", "near_right", "far_right", "far_left"]


@dataclass(frozen=True)
class TwoClickSolveResult:
    lane_points_world: np.ndarray
    image_points_xy: list[list[float] | None]
    confidence: float
    confidence_label: str
    debug: dict


def solve_lane_from_two_clicks(
    reference_frame: FrameRecord,
    intrinsics: CameraIntrinsics,
    lane_dimensions: LaneDimensions,
    near_points_xy: np.ndarray,
    image_bgr: np.ndarray | None = None,
    yaw_search_limit_deg: float = 8.0,
    yaw_step_deg: float = 0.25,
) -> TwoClickSolveResult:
    intrinsics.validate()
    near_points_xy = np.asarray(near_points_xy, dtype=np.float64)
    if near_points_xy.shape != (2, 2):
        raise ValueError("Expected exactly two clicked image points in near_left, near_right order")

    order_fix_applied = False
    if near_points_xy[0, 0] > near_points_xy[1, 0]:
        near_points_xy = near_points_xy[[1, 0]]
        order_fix_applied = True

    near_points_world, plane_details = _solve_near_lane_points_on_horizontal_plane(
        reference_frame=reference_frame,
        intrinsics=intrinsics,
        lane_width_m=lane_dimensions.lane_width_m,
        near_points_xy=near_points_xy,
    )
    base_forward_world = _estimate_lane_forward_from_pose(reference_frame, near_points_world)
    base_lane_points_world = _assemble_lane_world_points(
        near_left_world=near_points_world[0],
        near_right_world=near_points_world[1],
        forward_world=base_forward_world,
        lane_length_m=lane_dimensions.lane_length_m,
    )
    base_projection = project_world_points(reference_frame, intrinsics, base_lane_points_world)

    best_lane_points_world = base_lane_points_world
    best_projection = base_projection
    base_score = None
    best_score = None
    best_yaw_offset_deg = 0.0
    best_score_details = None
    used_edge_refinement = False

    if image_bgr is not None:
        edge_context = build_edge_context(image_bgr)
        base_score_details = score_lane_projection(edge_context, base_projection["image_points_xy"])
        base_score = float(base_score_details["total_score"])
        best_score = base_score
        best_score_details = base_score_details

        for yaw_offset_deg in np.arange(-yaw_search_limit_deg, yaw_search_limit_deg + 0.5 * yaw_step_deg, yaw_step_deg):
            candidate_forward_world = _rotate_vector_about_world_up(base_forward_world, yaw_offset_deg)
            candidate_lane_points_world = _assemble_lane_world_points(
                near_left_world=near_points_world[0],
                near_right_world=near_points_world[1],
                forward_world=candidate_forward_world,
                lane_length_m=lane_dimensions.lane_length_m,
            )
            candidate_projection = project_world_points(reference_frame, intrinsics, candidate_lane_points_world)
            candidate_score_details = score_lane_projection(edge_context, candidate_projection["image_points_xy"])
            candidate_score = float(candidate_score_details["total_score"])
            if best_score is None or candidate_score > best_score:
                best_score = candidate_score
                best_score_details = candidate_score_details
                best_yaw_offset_deg = float(yaw_offset_deg)
                best_lane_points_world = candidate_lane_points_world
                best_projection = candidate_projection

        score_improvement = 0.0 if best_score is None or base_score is None else best_score - base_score
        if score_improvement >= 0.01 and abs(best_yaw_offset_deg) >= 0.125:
            used_edge_refinement = True
        else:
            best_lane_points_world = base_lane_points_world
            best_projection = base_projection
            best_score = base_score
            best_score_details = base_score_details
            best_yaw_offset_deg = 0.0

    confidence = _estimate_confidence(best_score_details)
    confidence_label = _confidence_label(confidence)

    debug = {
        "order_fix_applied": order_fix_applied,
        "near_points_xy": near_points_xy.tolist(),
        "near_points_world": near_points_world.tolist(),
        "lane_plane_y_world_m": plane_details["lane_plane_y_world_m"],
        "lane_plane_scale_alpha": plane_details["alpha"],
        "ray_world_y_components": plane_details["ray_world_y_components"],
        "camera_position_world": reference_frame.camera_position.tolist(),
        "camera_rotation_xyzw": reference_frame.camera_rotation.tolist(),
        "base_forward_world": base_forward_world.tolist(),
        "base_image_points_xy": base_projection["image_points_xy"],
        "base_score": base_score,
        "best_score": best_score,
        "best_yaw_offset_deg": best_yaw_offset_deg,
        "used_edge_refinement": used_edge_refinement,
        "score_details": best_score_details,
    }
    return TwoClickSolveResult(
        lane_points_world=best_lane_points_world,
        image_points_xy=best_projection["image_points_xy"],
        confidence=confidence,
        confidence_label=confidence_label,
        debug=debug,
    )


def _solve_near_lane_points_on_horizontal_plane(
    reference_frame: FrameRecord,
    intrinsics: CameraIntrinsics,
    lane_width_m: float,
    near_points_xy: np.ndarray,
) -> tuple[np.ndarray, dict]:
    camera_rays_local = np.asarray(
        [_pixel_to_camera_ray_local(point_xy, intrinsics) for point_xy in near_points_xy],
        dtype=np.float64,
    )
    rotation_world_from_camera = quaternion_xyzw_to_rotation_matrix(reference_frame.camera_rotation)
    camera_rays_world = (rotation_world_from_camera @ camera_rays_local.T).T
    y_components = camera_rays_world[:, 1]
    if np.any(np.abs(y_components) <= 1e-6):
        raise RuntimeError("One of the clicked rays is nearly parallel to the assumed horizontal lane plane")

    width_scale_vector = camera_rays_world[0] / y_components[0] - camera_rays_world[1] / y_components[1]
    width_scale_norm = float(np.linalg.norm(width_scale_vector))
    if width_scale_norm <= 1e-6:
        raise RuntimeError("The two clicked points do not form a stable width solve on the horizontal lane plane")

    alpha_candidates = [lane_width_m / width_scale_norm, -lane_width_m / width_scale_norm]
    camera_position = reference_frame.camera_position.astype(np.float64)
    viable_candidates: list[tuple[float, np.ndarray, float]] = []
    for alpha in alpha_candidates:
        travel = alpha / y_components
        if np.all(travel > 0.0):
            lane_plane_y = float(camera_position[1] + alpha)
            viable_candidates.append((float(alpha), travel, lane_plane_y))
    if not viable_candidates:
        raise RuntimeError("Failed to intersect both clicked rays in front of the camera on a horizontal lane plane")

    viable_candidates.sort(key=lambda item: (item[2] >= camera_position[1], abs(item[2] - camera_position[1])))
    alpha, travel, lane_plane_y = viable_candidates[0]
    near_points_world = camera_position.reshape(1, 3) + travel.reshape(-1, 1) * camera_rays_world
    near_points_world[:, 1] = lane_plane_y
    return near_points_world, {
        "alpha": float(alpha),
        "lane_plane_y_world_m": float(lane_plane_y),
        "ray_world_y_components": y_components.tolist(),
    }


def _pixel_to_camera_ray_local(point_xy: np.ndarray, intrinsics: CameraIntrinsics) -> np.ndarray:
    x = (float(point_xy[0]) - intrinsics.cx) / intrinsics.fx
    y = -(float(point_xy[1]) - intrinsics.cy) / intrinsics.fy
    ray_local = np.array([x, y, 1.0], dtype=np.float64)
    return _normalize(ray_local)


def _estimate_lane_forward_from_pose(reference_frame: FrameRecord, near_points_world: np.ndarray) -> np.ndarray:
    width_direction = near_points_world[1] - near_points_world[0]
    width_direction = width_direction - WORLD_UP * np.dot(width_direction, WORLD_UP)
    width_direction = _normalize(width_direction)

    rotation_world_from_camera = quaternion_xyzw_to_rotation_matrix(reference_frame.camera_rotation)
    camera_forward_world = rotation_world_from_camera @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    camera_forward_world = camera_forward_world - WORLD_UP * np.dot(camera_forward_world, WORLD_UP)
    camera_forward_world = _normalize(camera_forward_world)

    candidate_forward = _normalize(np.cross(width_direction, WORLD_UP))
    if float(np.dot(candidate_forward, camera_forward_world)) < 0.0:
        candidate_forward *= -1.0
    return candidate_forward


def _assemble_lane_world_points(
    near_left_world: np.ndarray,
    near_right_world: np.ndarray,
    forward_world: np.ndarray,
    lane_length_m: float,
) -> np.ndarray:
    far_left_world = near_left_world + forward_world * lane_length_m
    far_right_world = near_right_world + forward_world * lane_length_m
    return np.vstack([near_left_world, near_right_world, far_right_world, far_left_world])


def _rotate_vector_about_world_up(vector_world: np.ndarray, yaw_offset_deg: float) -> np.ndarray:
    yaw_rad = float(np.radians(yaw_offset_deg))
    cos_yaw = float(np.cos(yaw_rad))
    sin_yaw = float(np.sin(yaw_rad))
    rotation = np.array(
        [
            [cos_yaw, 0.0, sin_yaw],
            [0.0, 1.0, 0.0],
            [-sin_yaw, 0.0, cos_yaw],
        ],
        dtype=np.float64,
    )
    rotated = rotation @ vector_world
    rotated = rotated - WORLD_UP * np.dot(rotated, WORLD_UP)
    return _normalize(rotated)


def _estimate_confidence(score_details: dict | None) -> float:
    if not score_details:
        return 0.5
    edge_score = 0.5 * (float(score_details["left_edge_score"]) + float(score_details["right_edge_score"]))
    hough_score = 0.5 * (float(score_details["left_hough_score"]) + float(score_details["right_hough_score"]))
    confidence = 0.6 * edge_score + 0.4 * hough_score
    return float(max(0.0, min(1.0, confidence)))


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def _normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("Cannot normalize a near-zero vector")
    return vector / norm
