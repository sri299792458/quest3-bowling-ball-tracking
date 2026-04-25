from __future__ import annotations

import math

import numpy as np


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("Cannot normalize a near-zero vector")
    return vector / norm


def quaternion_distance_deg(first_xyzw: np.ndarray, second_xyzw: np.ndarray) -> float:
    first = normalize_vector(np.asarray(first_xyzw, dtype=np.float64))
    second = normalize_vector(np.asarray(second_xyzw, dtype=np.float64))
    dot = abs(float(np.clip(np.dot(first, second), -1.0, 1.0)))
    return math.degrees(2.0 * math.acos(dot))


def world_to_lane_points(world_points: np.ndarray, world_to_lane_matrix: np.ndarray) -> np.ndarray:
    world_points = np.asarray(world_points, dtype=np.float64)
    homogenous = np.concatenate([world_points, np.ones((world_points.shape[0], 1), dtype=np.float64)], axis=1)
    lane_points = (world_to_lane_matrix @ homogenous.T).T
    return lane_points[:, :3]


def lane_to_world_points(lane_points: np.ndarray, lane_to_world_matrix: np.ndarray) -> np.ndarray:
    lane_points = np.asarray(lane_points, dtype=np.float64)
    homogenous = np.concatenate([lane_points, np.ones((lane_points.shape[0], 1), dtype=np.float64)], axis=1)
    world_points = (lane_to_world_matrix @ homogenous.T).T
    return world_points[:, :3]


def polygon_area_px2(image_points_xy: list[list[float] | None]) -> float | None:
    if any(point is None for point in image_points_xy):
        return None
    points = np.asarray(image_points_xy, dtype=np.float64)
    x_values = points[:, 0]
    y_values = points[:, 1]
    return float(0.5 * abs(np.dot(x_values, np.roll(y_values, -1)) - np.dot(y_values, np.roll(x_values, -1))))


def build_lane_frame(lane_points_world: np.ndarray) -> dict:
    lane_points_world = np.asarray(lane_points_world, dtype=np.float64)
    if lane_points_world.shape != (4, 3):
        raise ValueError("Expected lane points in near_left, near_right, far_right, far_left order")

    near_left = lane_points_world[0]
    near_right = lane_points_world[1]
    far_right = lane_points_world[2]
    far_left = lane_points_world[3]

    origin_world = near_left
    x_axis_world = normalize_vector(near_right - near_left)
    forward_hint_world = 0.5 * (far_right + far_left) - 0.5 * (near_left + near_right)
    forward_hint_world = forward_hint_world - np.dot(forward_hint_world, x_axis_world) * x_axis_world
    z_axis_world = normalize_vector(forward_hint_world)
    y_axis_world = normalize_vector(np.cross(z_axis_world, x_axis_world))
    z_axis_world = normalize_vector(np.cross(x_axis_world, y_axis_world))

    world_to_lane_rotation = np.vstack([x_axis_world, y_axis_world, z_axis_world])
    lane_to_world_rotation = world_to_lane_rotation.T

    world_to_lane_matrix = np.eye(4, dtype=np.float64)
    world_to_lane_matrix[:3, :3] = world_to_lane_rotation
    world_to_lane_matrix[:3, 3] = -world_to_lane_rotation @ origin_world

    lane_to_world_matrix = np.eye(4, dtype=np.float64)
    lane_to_world_matrix[:3, :3] = lane_to_world_rotation
    lane_to_world_matrix[:3, 3] = origin_world

    width_m = float(np.linalg.norm(near_right - near_left))
    length_m = float(np.linalg.norm(0.5 * (far_right + far_left) - 0.5 * (near_left + near_right)))

    lane_points_local = world_to_lane_points(lane_points_world, world_to_lane_matrix)
    expected_local = np.array(
        [
            [0.0, 0.0, 0.0],
            [width_m, 0.0, 0.0],
            [width_m, 0.0, length_m],
            [0.0, 0.0, length_m],
        ],
        dtype=np.float64,
    )
    corner_residuals_m = np.linalg.norm(lane_points_local - expected_local, axis=1)

    return {
        "origin_world": origin_world,
        "x_axis_world": x_axis_world,
        "y_axis_world": y_axis_world,
        "z_axis_world": z_axis_world,
        "plane_normal_world": y_axis_world,
        "world_to_lane_matrix": world_to_lane_matrix,
        "lane_to_world_matrix": lane_to_world_matrix,
        "lane_points_local": lane_points_local,
        "expected_lane_points_local": expected_local,
        "corner_residuals_m": corner_residuals_m,
        "max_corner_residual_m": float(np.max(corner_residuals_m)),
        "lane_width_m": width_m,
        "lane_length_m": length_m,
    }
