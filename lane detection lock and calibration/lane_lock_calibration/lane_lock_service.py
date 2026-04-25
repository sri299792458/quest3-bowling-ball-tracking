from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .geometry import build_lane_frame
from .legacy import load_legacy_lane_modules
from .models import LaneLock


def build_lane_lock_from_annotation(
    run_dir: Path,
    annotation_path: Path,
    intrinsics_path: Path,
    lane_config_path: Path,
    output_dir: Path | None = None,
) -> LaneLock:
    legacy = load_legacy_lane_modules()
    load_run = legacy["load_run"]
    CameraIntrinsics = legacy["CameraIntrinsics"]
    LaneDimensions = legacy["LaneDimensions"]
    solve_lane_from_two_clicks = legacy["solve_lane_from_two_clicks"]

    run = load_run(run_dir)
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    reference_frame_idx = int(annotation["reference_frame_idx"])
    reference_frame = run.get_frame_record(reference_frame_idx)
    image_bgr = run.load_frame_bgr(reference_frame_idx)

    intrinsics = CameraIntrinsics.from_json(intrinsics_path)
    lane_dimensions = LaneDimensions.from_json(lane_config_path)
    near_points_xy = annotation["image_points"]

    result = solve_lane_from_two_clicks(
        reference_frame=reference_frame,
        intrinsics=intrinsics,
        lane_dimensions=lane_dimensions,
        near_points_xy=near_points_xy,
        image_bgr=image_bgr,
    )

    frame_details = build_lane_frame(np.asarray(result.lane_points_world, dtype=np.float64))
    lane_lock = LaneLock(
        run_name=run.run_name,
        reference_frame_idx=reference_frame_idx,
        reference_source_frame_id=int(reference_frame.source_frame_id),
        reference_timestamp_us=int(reference_frame.timestamp_us),
        frame_file_name=str(reference_frame.file_name),
        annotation_path=str(annotation_path.resolve()),
        intrinsics_path=str(intrinsics_path.resolve()),
        lane_config_path=str(lane_config_path.resolve()),
        point_order=list(legacy["POINT_ORDER"]),
        selected_candidate_ids=[int(value) for value in annotation.get("selected_candidate_ids", [])],
        reference_near_points_xy=[[float(value) for value in point_xy] for point_xy in near_points_xy],
        lane_points_world=np.asarray(result.lane_points_world, dtype=np.float64).tolist(),
        image_points_xy=result.image_points_xy,
        confidence=float(result.confidence),
        confidence_label=str(result.confidence_label),
        reference_camera_position_world=np.asarray(reference_frame.camera_position, dtype=np.float64).tolist(),
        reference_camera_rotation_xyzw=np.asarray(reference_frame.camera_rotation, dtype=np.float64).tolist(),
        lane_width_m=float(lane_dimensions.lane_width_m),
        lane_length_m=float(lane_dimensions.lane_length_m),
        plane_normal_world=np.asarray(frame_details["plane_normal_world"], dtype=np.float64).tolist(),
        lane_axes_world={
            "x_axis_world": np.asarray(frame_details["x_axis_world"], dtype=np.float64).tolist(),
            "y_axis_world": np.asarray(frame_details["y_axis_world"], dtype=np.float64).tolist(),
            "z_axis_world": np.asarray(frame_details["z_axis_world"], dtype=np.float64).tolist(),
            "origin_world": np.asarray(frame_details["origin_world"], dtype=np.float64).tolist(),
        },
        world_to_lane_matrix=np.asarray(frame_details["world_to_lane_matrix"], dtype=np.float64).tolist(),
        lane_to_world_matrix=np.asarray(frame_details["lane_to_world_matrix"], dtype=np.float64).tolist(),
        corner_residuals_m=np.asarray(frame_details["corner_residuals_m"], dtype=np.float64).tolist(),
        max_corner_residual_m=float(frame_details["max_corner_residual_m"]),
        reference_edge_score=(
            None if result.debug.get("best_score") is None else float(result.debug.get("best_score"))
        ),
        debug=result.debug,
    )

    if output_dir is not None:
        save_lane_lock_artifacts(
            lane_lock=lane_lock,
            annotation=annotation,
            intrinsics_path=intrinsics_path,
            lane_config_path=lane_config_path,
            output_dir=output_dir,
            image_bgr=image_bgr,
        )

    return lane_lock


def save_lane_lock_artifacts(
    lane_lock: LaneLock,
    annotation: dict,
    intrinsics_path: Path,
    lane_config_path: Path,
    output_dir: Path,
    image_bgr: np.ndarray,
) -> None:
    legacy = load_legacy_lane_modules()
    draw_click_points = legacy["draw_click_points"]
    draw_header_lines = legacy["draw_header_lines"]
    draw_lane_polygon = legacy["draw_lane_polygon"]

    output_dir.mkdir(parents=True, exist_ok=True)

    lane_lock_path = output_dir / "lane_lock.json"
    lane_lock_path.write_text(json.dumps(lane_lock.to_dict(), indent=2), encoding="utf-8")

    (output_dir / "reference_annotation.json").write_text(json.dumps(annotation, indent=2), encoding="utf-8")
    (output_dir / "intrinsics_used.json").write_text(intrinsics_path.read_text(encoding="utf-8"), encoding="utf-8")
    (output_dir / "lane_dimensions_used.json").write_text(
        lane_config_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    overlay_image = image_bgr.copy()
    draw_lane_polygon(
        overlay_image,
        lane_lock.image_points_xy,
        labels=lane_lock.point_order,
        edge_color_bgr=(0, 255, 0),
        point_color_bgr=(0, 0, 255),
        thickness=2,
    )
    draw_click_points(
        overlay_image,
        lane_lock.reference_near_points_xy,
        labels=["near_left", "near_right"],
        color_bgr=(0, 255, 255),
    )
    draw_header_lines(
        overlay_image,
        [
            f"lane lock | {lane_lock.run_name}",
            f"frame {lane_lock.reference_frame_idx} | confidence {lane_lock.confidence_label} ({lane_lock.confidence:.2f})",
            f"corner residual max {lane_lock.max_corner_residual_m:.4f} m",
        ],
    )

    base_overlay_image = image_bgr.copy()
    draw_lane_polygon(
        base_overlay_image,
        lane_lock.debug.get("base_image_points_xy", lane_lock.image_points_xy),
        labels=lane_lock.point_order,
        edge_color_bgr=(255, 160, 0),
        point_color_bgr=(255, 160, 0),
        thickness=2,
    )
    draw_click_points(
        base_overlay_image,
        lane_lock.reference_near_points_xy,
        labels=["near_left", "near_right"],
        color_bgr=(0, 255, 255),
    )
    draw_header_lines(
        base_overlay_image,
        [
            f"base geometry | {lane_lock.run_name}",
            f"frame {lane_lock.reference_frame_idx}",
        ],
    )

    import cv2

    cv2.imwrite(str(output_dir / "lane_lock_reference_overlay.jpg"), overlay_image)
    cv2.imwrite(str(output_dir / "lane_lock_base_geometry.jpg"), base_overlay_image)


def load_lane_lock(path: Path) -> LaneLock:
    return LaneLock.from_json(path)
