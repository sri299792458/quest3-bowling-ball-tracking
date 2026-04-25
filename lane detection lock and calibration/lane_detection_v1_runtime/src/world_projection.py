from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .frame_dataset import FrameRecord


@dataclass(frozen=True)
class CameraIntrinsics:
    image_width: int
    image_height: int
    fx: float
    fy: float
    cx: float
    cy: float
    source: str = "unknown"

    @classmethod
    def from_json(cls, path: Path) -> "CameraIntrinsics":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            image_width=int(payload["image_width"]),
            image_height=int(payload["image_height"]),
            fx=float(payload["fx"]),
            fy=float(payload["fy"]),
            cx=float(payload["cx"]),
            cy=float(payload["cy"]),
            source=str(payload.get("source", "unknown")),
        )

    def validate(self) -> None:
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError(
                "Camera intrinsics are incomplete. Fill fx/fy in the intrinsics JSON before running reprojection."
            )

    def camera_matrix(self) -> np.ndarray:
        return np.array(
            [
                [self.fx, 0.0, self.cx],
                [0.0, self.fy, self.cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )


@dataclass(frozen=True)
class LaneDimensions:
    lane_width_m: float
    lane_length_m: float

    @classmethod
    def from_json(cls, path: Path) -> "LaneDimensions":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            lane_width_m=float(payload["lane_width_m"]),
            lane_length_m=float(payload["lane_length_m"]),
        )

    def object_points(self) -> np.ndarray:
        return np.array(
            [
                [0.0, 0.0, 0.0],
                [self.lane_width_m, 0.0, 0.0],
                [self.lane_width_m, 0.0, self.lane_length_m],
                [0.0, 0.0, self.lane_length_m],
            ],
            dtype=np.float64,
        )


@dataclass(frozen=True)
class IntrinsicsEstimateResult:
    intrinsics: CameraIntrinsics
    best_score: float
    best_plane_normal_world: np.ndarray
    best_lane_points_world: np.ndarray
    debug: dict


def normalize_quaternion_xyzw(quaternion_xyzw: np.ndarray) -> np.ndarray:
    quaternion_xyzw = np.asarray(quaternion_xyzw, dtype=np.float64)
    norm = np.linalg.norm(quaternion_xyzw)
    if norm <= 1e-12:
        raise ValueError("Quaternion has near-zero norm")
    return quaternion_xyzw / norm


def quaternion_xyzw_to_rotation_matrix(quaternion_xyzw: np.ndarray) -> np.ndarray:
    x, y, z, w = normalize_quaternion_xyzw(quaternion_xyzw)
    xx = x * x
    yy = y * y
    zz = z * z
    xy = x * y
    xz = x * z
    yz = y * z
    wx = w * x
    wy = w * y
    wz = w * z
    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=np.float64,
    )


def camera_cv_to_unity(points_cv: np.ndarray) -> np.ndarray:
    points_unity = np.asarray(points_cv, dtype=np.float64).copy()
    points_unity[..., 1] *= -1.0
    return points_unity


def world_from_camera_local(frame: FrameRecord, camera_local_points: np.ndarray) -> np.ndarray:
    rotation_world_from_camera = quaternion_xyzw_to_rotation_matrix(frame.camera_rotation)
    translation_world_from_camera = frame.camera_position.reshape(1, 3)
    return (rotation_world_from_camera @ camera_local_points.T).T + translation_world_from_camera


def camera_local_from_world(frame: FrameRecord, world_points: np.ndarray) -> np.ndarray:
    rotation_world_from_camera = quaternion_xyzw_to_rotation_matrix(frame.camera_rotation)
    rotation_camera_from_world = rotation_world_from_camera.T
    centered = world_points - frame.camera_position.reshape(1, 3)
    return (rotation_camera_from_world @ centered.T).T


def estimate_lane_world_points(
    reference_frame: FrameRecord,
    intrinsics: CameraIntrinsics,
    lane_dimensions: LaneDimensions,
    image_points_xy: np.ndarray,
) -> dict:
    import cv2

    intrinsics.validate()
    object_points = lane_dimensions.object_points()
    image_points = np.asarray(image_points_xy, dtype=np.float64)

    if image_points.shape != (4, 2):
        raise ValueError("Expected four image points in near_left, near_right, far_right, far_left order")

    camera_matrix = intrinsics.camera_matrix()
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    solve_flags = []
    if hasattr(cv2, "SOLVEPNP_IPPE"):
        solve_flags.append(cv2.SOLVEPNP_IPPE)
    solve_flags.append(cv2.SOLVEPNP_ITERATIVE)

    solved = None
    for flag in solve_flags:
        success, rvec, tvec = cv2.solvePnP(
            object_points,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=flag,
        )
        if success:
            solved = (rvec, tvec, flag)
            break

    if solved is None:
        raise RuntimeError("Failed to estimate lane pose from the reference frame")

    rvec, tvec, flag_used = solved
    rotation_cv_from_lane, _ = cv2.Rodrigues(rvec)
    lane_points_camera_cv = (rotation_cv_from_lane @ object_points.T).T + tvec.reshape(1, 3)
    lane_points_camera_unity = camera_cv_to_unity(lane_points_camera_cv)
    lane_points_world = world_from_camera_local(reference_frame, lane_points_camera_unity)

    return {
        "solvepnp_flag": int(flag_used),
        "object_points_lane": object_points,
        "lane_points_camera_cv": lane_points_camera_cv,
        "lane_points_camera_unity": lane_points_camera_unity,
        "lane_points_world": lane_points_world,
        "rvec": rvec.reshape(3),
        "tvec": tvec.reshape(3),
    }


def estimate_single_focal_intrinsics(
    reference_frame: FrameRecord,
    image_width: int,
    image_height: int,
    lane_dimensions: LaneDimensions,
    image_points_xy: np.ndarray,
    principal_point_xy: tuple[float, float] | None = None,
) -> IntrinsicsEstimateResult:
    center_x = float(image_width) * 0.5
    center_y = float(image_height) * 0.5
    cx, cy = principal_point_xy if principal_point_xy is not None else (center_x, center_y)

    coarse_candidates = np.arange(250.0, 2200.0 + 1.0, 25.0, dtype=np.float64)
    coarse_result = _search_single_focal_candidates(
        reference_frame=reference_frame,
        image_width=image_width,
        image_height=image_height,
        lane_dimensions=lane_dimensions,
        image_points_xy=image_points_xy,
        cx=cx,
        cy=cy,
        focal_candidates=coarse_candidates,
    )

    refine_center = coarse_result["focal"]
    refine_start = max(150.0, refine_center - 50.0)
    refine_end = refine_center + 50.0
    refine_candidates = np.arange(refine_start, refine_end + 1.0, 1.0, dtype=np.float64)
    refine_result = _search_single_focal_candidates(
        reference_frame=reference_frame,
        image_width=image_width,
        image_height=image_height,
        lane_dimensions=lane_dimensions,
        image_points_xy=image_points_xy,
        cx=cx,
        cy=cy,
        focal_candidates=refine_candidates,
    )

    best_intrinsics = CameraIntrinsics(
        image_width=image_width,
        image_height=image_height,
        fx=float(refine_result["focal"]),
        fy=float(refine_result["focal"]),
        cx=float(cx),
        cy=float(cy),
        source="auto_estimated_single_focal_from_reference_lane",
    )
    return IntrinsicsEstimateResult(
        intrinsics=best_intrinsics,
        best_score=float(refine_result["score"]),
        best_plane_normal_world=refine_result["plane_normal_world"],
        best_lane_points_world=refine_result["lane_points_world"],
        debug={
            "coarse_focal_px": float(coarse_result["focal"]),
            "coarse_score": float(coarse_result["score"]),
            "refined_focal_px": float(refine_result["focal"]),
            "refined_score": float(refine_result["score"]),
            "mean_lane_y_world_m": float(refine_result["mean_lane_y"]),
            "lane_y_std_world_m": float(refine_result["lane_y_std"]),
            "plane_normal_alignment_up": float(refine_result["normal_alignment"]),
            "forward_vertical_component": float(refine_result["forward_vertical_component"]),
            "width_vertical_component": float(refine_result["width_vertical_component"]),
        },
    )


def _search_single_focal_candidates(
    reference_frame: FrameRecord,
    image_width: int,
    image_height: int,
    lane_dimensions: LaneDimensions,
    image_points_xy: np.ndarray,
    cx: float,
    cy: float,
    focal_candidates: np.ndarray,
) -> dict:
    best_result: dict | None = None

    for focal in focal_candidates.tolist():
        intrinsics = CameraIntrinsics(
            image_width=image_width,
            image_height=image_height,
            fx=float(focal),
            fy=float(focal),
            cx=float(cx),
            cy=float(cy),
            source="single_focal_candidate",
        )
        try:
            solved = estimate_lane_world_points(
                reference_frame=reference_frame,
                intrinsics=intrinsics,
                lane_dimensions=lane_dimensions,
                image_points_xy=image_points_xy,
            )
        except Exception:
            continue

        lane_points_world = solved["lane_points_world"]
        score_terms = _lane_world_plausibility_terms(lane_points_world)
        score = (
            14.0 * score_terms["lane_y_std"]
            + 5.0 * score_terms["mean_lane_y_abs"]
            + 12.0 * (1.0 - score_terms["normal_alignment"])
            + 8.0 * score_terms["forward_vertical_component"]
            + 4.0 * score_terms["width_vertical_component"]
        )

        result = {
            "focal": float(focal),
            "score": float(score),
            "lane_points_world": lane_points_world,
            "plane_normal_world": score_terms["plane_normal_world"],
            "mean_lane_y": score_terms["mean_lane_y"],
            "lane_y_std": score_terms["lane_y_std"],
            "normal_alignment": score_terms["normal_alignment"],
            "forward_vertical_component": score_terms["forward_vertical_component"],
            "width_vertical_component": score_terms["width_vertical_component"],
        }
        if best_result is None or result["score"] < best_result["score"]:
            best_result = result

    if best_result is None:
        raise RuntimeError("Failed to estimate a plausible focal length from the reference frame")
    return best_result


def _lane_world_plausibility_terms(lane_points_world: np.ndarray) -> dict:
    lane_points_world = np.asarray(lane_points_world, dtype=np.float64)
    world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)

    width_vector = lane_points_world[1] - lane_points_world[0]
    forward_vector = (lane_points_world[2] + lane_points_world[3]) * 0.5 - (lane_points_world[0] + lane_points_world[1]) * 0.5
    plane_normal = np.cross(width_vector, lane_points_world[3] - lane_points_world[0])

    plane_normal_norm = np.linalg.norm(plane_normal)
    if plane_normal_norm <= 1e-12:
        raise RuntimeError("Estimated lane plane normal has near-zero norm")
    plane_normal_world = plane_normal / plane_normal_norm

    width_norm = np.linalg.norm(width_vector)
    forward_norm = np.linalg.norm(forward_vector)
    width_vertical_component = abs(width_vector[1] / max(width_norm, 1e-12))
    forward_vertical_component = abs(forward_vector[1] / max(forward_norm, 1e-12))
    normal_alignment = abs(float(np.dot(plane_normal_world, world_up)))

    y_values = lane_points_world[:, 1]
    mean_lane_y = float(np.mean(y_values))
    lane_y_std = float(np.std(y_values))

    return {
        "plane_normal_world": plane_normal_world,
        "normal_alignment": normal_alignment,
        "forward_vertical_component": float(forward_vertical_component),
        "width_vertical_component": float(width_vertical_component),
        "mean_lane_y": mean_lane_y,
        "mean_lane_y_abs": abs(mean_lane_y),
        "lane_y_std": lane_y_std,
    }


def project_world_points(
    frame: FrameRecord,
    intrinsics: CameraIntrinsics,
    world_points: np.ndarray,
) -> dict:
    intrinsics.validate()
    world_points = np.asarray(world_points, dtype=np.float64)
    camera_points = camera_local_from_world(frame, world_points)

    projections: list[list[float] | None] = []
    visibility: list[bool] = []
    depths: list[float] = []

    for point in camera_points:
        x_cam, y_cam, z_cam = point.tolist()
        depths.append(float(z_cam))
        if z_cam <= 1e-6:
            projections.append(None)
            visibility.append(False)
            continue
        u = intrinsics.fx * (x_cam / z_cam) + intrinsics.cx
        v = intrinsics.fy * (-y_cam / z_cam) + intrinsics.cy
        projections.append([float(u), float(v)])
        visibility.append(True)

    return {
        "camera_points_unity": camera_points,
        "image_points_xy": projections,
        "visibility": visibility,
        "depths": depths,
    }
