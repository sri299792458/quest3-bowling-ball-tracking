from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.interpolate import make_smoothing_spline

from laptop_receiver.lane_geometry import (
    is_lane_point_plausible,
    lane_coordinates_to_world_point,
    project_ball_image_point_to_lane_space,
)
from laptop_receiver.lane_lock_types import (
    CameraIntrinsics,
    FrameCameraState,
    LaneLockResult,
    LanePoint,
    LaneSpaceBallPoint,
    Vector2,
    Vector3,
)


FINAL_TRAJECTORY_POINT_DEFINITION = "camera_sam2_mask_measurement_spline_l14"
METERS_TO_FEET = 3.280839895013123
BOWLING_BOARD_COUNT = 39.0


@dataclass(frozen=True)
class TrajectoryReconstructionConfig:
    spline_lambda: float = 14.0
    spline_min_points: int = 6
    spline_robust_iterations: int = 4
    spline_robust_cutoff_boards: float = 1.15
    spline_near_weight_max_extra: float = 1.50
    spline_near_weight_full_distance_meters: float = 10.668
    spline_near_weight_falloff_meters: float = 9.144
    spline_tail_downweight_start_meters: float = 16.764
    spline_tail_downweight_multiplier: float = 0.65
    spline_tail_heavy_downweight_start_meters: float = 17.6784
    spline_tail_heavy_downweight_multiplier: float = 0.35
    max_terminal_frames: int = 8
    terminal_speed_cap_m_per_frame: float = 0.55
    terminal_confidence_scale: float = 0.55
    pin_deck_completion_margin_meters: float = 5.25
    pin_deck_completion_half_width_fraction: float = 0.92
    pin_deck_completion_edge_guard_fraction: float = 0.96
    pin_deck_completion_max_frames: int = 36
    pin_deck_completion_min_speed_m_per_frame: float = 0.14
    min_projection_confidence: float = 0.20
    min_measurement_confidence: float = 0.05
    measurement_lateral_margin_meters: float = 0.10
    smoothing_lateral_margin_meters: float = 0.12


@dataclass(frozen=True)
class LaneSpaceTrajectoryMeasurement:
    source_point: LaneSpaceBallPoint
    mask_quality: float

    @property
    def frame_seq(self) -> int:
        return int(self.source_point.frame_seq)

    @property
    def pts_us(self) -> int:
        return int(self.source_point.pts_us)

    @property
    def camera_timestamp_us(self) -> int:
        return int(self.source_point.camera_timestamp_us)

    @property
    def x_meters(self) -> float:
        return float(self.source_point.lane_point.x_meters)

    @property
    def s_meters(self) -> float:
        return float(self.source_point.lane_point.s_meters)

    @property
    def confidence(self) -> float:
        return float(self.source_point.projection_confidence) * max(0.0, min(1.0, float(self.mask_quality)))


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _frame_state_for_index(frame_metadata: list[dict[str, Any]], frame_index: int) -> FrameCameraState:
    if frame_index < 0 or frame_index >= len(frame_metadata):
        raise RuntimeError(f"Frame index {frame_index} is outside metadata range 0..{len(frame_metadata) - 1}.")
    return FrameCameraState.from_frame_metadata(frame_metadata[frame_index])


def _source_frame_index_from_row(row: Mapping[str, str], source_frame_idx_start: int) -> int:
    if row.get("source_frame_idx") not in ("", None):
        return int(row["source_frame_idx"])
    return int(row["frame_idx"]) + int(source_frame_idx_start)


def _measurement_image_point(row: Mapping[str, str], config: TrajectoryReconstructionConfig) -> Vector2:
    _ = config
    required = ("mask_measurement_x", "mask_measurement_y")
    missing = [name for name in required if row.get(name) in ("", None)]
    if missing:
        raise RuntimeError(
            "SAM2 track is missing live mask measurement fields "
            f"{missing}; rerun with live SAM mask persistence."
        )
    return Vector2(
        x=float(row["mask_measurement_x"]),
        y=float(row["mask_measurement_y"]),
    )


def _validate_image_geometry(artifact: Any, intrinsics: CameraIntrinsics) -> None:
    video_info = getattr(artifact, "video_info", None)
    if video_info is not None:
        video_width = int(getattr(video_info, "width", 0) or 0)
        video_height = int(getattr(video_info, "height", 0) or 0)
        if video_width > 0 and video_height > 0 and (video_width != intrinsics.width or video_height != intrinsics.height):
            raise RuntimeError(
                "decoded_video_metadata_size_mismatch:"
                f" decoded={video_width}x{video_height} metadata={intrinsics.width}x{intrinsics.height}"
            )

    for index, metadata in enumerate(getattr(artifact, "frame_metadata", []) or []):
        width = _int(metadata.get("width"), intrinsics.width)
        height = _int(metadata.get("height"), intrinsics.height)
        if width != intrinsics.width or height != intrinsics.height:
            frame_seq = _int(metadata.get("frameSeq"), index)
            raise RuntimeError(
                "frame_metadata_size_mismatch:"
                f" frameSeq={frame_seq} frame={width}x{height} metadata={intrinsics.width}x{intrinsics.height}"
            )


def _measurement_lateral_limit(lane_lock: LaneLockResult, config: TrajectoryReconstructionConfig) -> float:
    return max(0.01, float(lane_lock.lane_width_meters) * 0.5 + float(config.measurement_lateral_margin_meters))


def _is_usable_measurement(
    measurement: LaneSpaceTrajectoryMeasurement,
    lane_lock: LaneLockResult,
    config: TrajectoryReconstructionConfig,
) -> bool:
    lane_point = measurement.source_point.lane_point
    if not _finite(float(lane_point.x_meters), float(lane_point.s_meters), float(measurement.confidence)):
        return False
    if not bool(measurement.source_point.is_on_locked_lane):
        return False
    if float(measurement.source_point.projection_confidence) < float(config.min_projection_confidence):
        return False
    if float(measurement.confidence) < float(config.min_measurement_confidence):
        return False
    if abs(float(lane_point.x_meters)) > _measurement_lateral_limit(lane_lock, config):
        return False
    return True


def load_mask_track_measurements(
    *,
    artifact: Any,
    session_id: str,
    shot_id: str,
    lane_lock: LaneLockResult,
    track_csv_path: Path,
    source_frame_idx_start: int,
    config: TrajectoryReconstructionConfig | None = None,
) -> list[LaneSpaceTrajectoryMeasurement]:
    resolved_config = config or TrajectoryReconstructionConfig()
    if not track_csv_path.exists():
        raise RuntimeError(f"SAM2 track CSV does not exist: {track_csv_path}")

    intrinsics = CameraIntrinsics.from_session_metadata(artifact.session_metadata)
    _validate_image_geometry(artifact, intrinsics)
    measurements: list[LaneSpaceTrajectoryMeasurement] = []
    with track_csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row_index, row in enumerate(csv.DictReader(handle)):
            if _int(row.get("present")) != 1:
                continue

            source_frame_idx = _source_frame_index_from_row(row, source_frame_idx_start)
            frame_state = _frame_state_for_index(artifact.frame_metadata, source_frame_idx)
            try:
                image_point = _measurement_image_point(row, resolved_config)
            except Exception as exc:
                raise RuntimeError(f"{track_csv_path}:{row_index + 2}: {exc}") from exc

            source_point = project_ball_image_point_to_lane_space(
                session_id=session_id,
                shot_id=shot_id,
                image_point_px=image_point,
                frame_camera_state=frame_state,
                intrinsics=intrinsics,
                lane_lock=lane_lock,
                point_definition="camera_sam2_mask_top_centroid_measurement",
            )
            measurement = LaneSpaceTrajectoryMeasurement(
                source_point=source_point,
                mask_quality=_float(row.get("mask_quality"), 0.5),
            )
            if _is_usable_measurement(measurement, lane_lock, resolved_config):
                measurements.append(measurement)
    return measurements


def _board_from_x_meters(x_meters: float, lane_lock: LaneLockResult) -> float:
    board_width = max(float(lane_lock.lane_width_meters) / BOWLING_BOARD_COUNT, 1e-6)
    return (float(lane_lock.lane_width_meters) * 0.5 - float(x_meters)) / board_width + 0.5


def _x_meters_from_board(board: float, lane_lock: LaneLockResult) -> float:
    board_width = max(float(lane_lock.lane_width_meters) / BOWLING_BOARD_COUNT, 1e-6)
    return float(lane_lock.lane_width_meters) * 0.5 - (float(board) - 0.5) * board_width


def _spline_lateral_board_limits(lane_lock: LaneLockResult, config: TrajectoryReconstructionConfig) -> tuple[float, float]:
    x_limit = max(0.01, float(lane_lock.lane_width_meters) * 0.5 + float(config.smoothing_lateral_margin_meters))
    left_limit_board = _board_from_x_meters(-x_limit, lane_lock)
    right_limit_board = _board_from_x_meters(x_limit, lane_lock)
    return min(left_limit_board, right_limit_board), max(left_limit_board, right_limit_board)


def _spline_measurement_weight(
    measurement: LaneSpaceTrajectoryMeasurement,
    *,
    s_meters: float,
    config: TrajectoryReconstructionConfig,
) -> float:
    confidence = max(0.05, min(1.0, float(measurement.confidence)))
    near_fraction = (
        float(config.spline_near_weight_full_distance_meters) - float(s_meters)
    ) / max(float(config.spline_near_weight_falloff_meters), 1e-6)
    near_multiplier = 1.0 + float(config.spline_near_weight_max_extra) * max(0.0, min(1.0, near_fraction))

    tail_multiplier = 1.0
    if float(s_meters) >= float(config.spline_tail_downweight_start_meters):
        tail_multiplier *= float(config.spline_tail_downweight_multiplier)
    if float(s_meters) >= float(config.spline_tail_heavy_downweight_start_meters):
        tail_multiplier *= float(config.spline_tail_heavy_downweight_multiplier)

    return max(1e-3, confidence * near_multiplier * tail_multiplier)


def _consolidate_spline_samples(
    s_feet: np.ndarray,
    boards: np.ndarray,
    weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    buckets: dict[float, tuple[float, float]] = {}
    for s_value, board_value, weight_value in zip(s_feet, boards, weights):
        if not _finite(float(s_value), float(board_value), float(weight_value)):
            continue
        key = round(float(s_value), 4)
        total_weight, weighted_board_sum = buckets.get(key, (0.0, 0.0))
        weight = max(float(weight_value), 1e-6)
        buckets[key] = (total_weight + weight, weighted_board_sum + float(board_value) * weight)

    sorted_keys = sorted(buckets)
    consolidated_s: list[float] = []
    consolidated_boards: list[float] = []
    consolidated_weights: list[float] = []
    previous_s: float | None = None
    for key in sorted_keys:
        total_weight, weighted_board_sum = buckets[key]
        if previous_s is not None and key <= previous_s:
            continue
        consolidated_s.append(float(key))
        consolidated_boards.append(float(weighted_board_sum) / max(float(total_weight), 1e-6))
        consolidated_weights.append(max(float(total_weight), 1e-6))
        previous_s = float(key)

    return (
        np.asarray(consolidated_s, dtype=np.float64),
        np.asarray(consolidated_boards, dtype=np.float64),
        np.asarray(consolidated_weights, dtype=np.float64),
    )


def _fit_robust_board_spline(
    s_feet: np.ndarray,
    boards: np.ndarray,
    weights: np.ndarray,
    *,
    config: TrajectoryReconstructionConfig,
) -> Any:
    current_weights = np.asarray(weights, dtype=np.float64).copy()
    spline = None
    iterations = max(int(config.spline_robust_iterations), 1)
    cutoff = max(float(config.spline_robust_cutoff_boards), 1e-3)
    for _ in range(iterations):
        spline = make_smoothing_spline(
            s_feet,
            boards,
            w=np.maximum(current_weights, 1e-6),
            lam=max(float(config.spline_lambda), 0.0),
        )
        residuals = np.asarray(spline(s_feet), dtype=np.float64) - boards
        abs_residuals = np.abs(residuals)
        robust_weights = np.ones_like(current_weights)
        outlier_mask = abs_residuals > cutoff
        robust_weights[outlier_mask] = cutoff / np.maximum(abs_residuals[outlier_mask], 1e-6)
        current_weights = np.maximum(weights * robust_weights, 1e-6)
    return spline


def _spline_smooth_positions(
    measurements: Sequence[LaneSpaceTrajectoryMeasurement],
    lane_lock: LaneLockResult,
    config: TrajectoryReconstructionConfig,
) -> np.ndarray:
    if not measurements:
        return np.empty((0, 2), dtype=np.float64)

    lane_length = max(float(lane_lock.lane_length_meters), 0.0)
    output_s_meters = np.asarray([float(measurement.s_meters) for measurement in measurements], dtype=np.float64)
    output_s_meters = np.clip(output_s_meters, 0.0, lane_length)
    output_s_meters = np.maximum.accumulate(output_s_meters)

    raw_boards = np.asarray(
        [_board_from_x_meters(float(measurement.x_meters), lane_lock) for measurement in measurements],
        dtype=np.float64,
    )
    raw_weights = np.asarray(
        [
            _spline_measurement_weight(measurement, s_meters=float(output_s_meters[index]), config=config)
            for index, measurement in enumerate(measurements)
        ],
        dtype=np.float64,
    )

    board_min, board_max = _spline_lateral_board_limits(lane_lock, config)
    raw_boards = np.clip(raw_boards, board_min, board_max)
    output_x_meters = np.asarray(
        [_x_meters_from_board(float(board), lane_lock) for board in raw_boards],
        dtype=np.float64,
    )
    if len(measurements) < max(int(config.spline_min_points), 2):
        return np.column_stack([output_x_meters, output_s_meters])

    fit_s_feet, fit_boards, fit_weights = _consolidate_spline_samples(
        output_s_meters * METERS_TO_FEET,
        raw_boards,
        raw_weights,
    )
    if len(fit_s_feet) < max(int(config.spline_min_points), 2):
        return np.column_stack([output_x_meters, output_s_meters])

    spline = _fit_robust_board_spline(fit_s_feet, fit_boards, fit_weights, config=config)
    smoothed_boards = np.asarray(spline(output_s_meters * METERS_TO_FEET), dtype=np.float64)
    smoothed_boards = np.clip(smoothed_boards, board_min, board_max)
    smoothed_x_meters = np.asarray(
        [_x_meters_from_board(float(board), lane_lock) for board in smoothed_boards],
        dtype=np.float64,
    )
    lateral_limit = max(0.01, float(lane_lock.lane_width_meters) * 0.5 + float(config.smoothing_lateral_margin_meters))
    smoothed_x_meters = np.clip(smoothed_x_meters, -lateral_limit, lateral_limit)
    return np.column_stack([smoothed_x_meters, output_s_meters])


def _frame_timing_by_seq(frame_metadata: list[dict[str, Any]]) -> dict[int, tuple[int, int]]:
    timing: dict[int, tuple[int, int]] = {}
    for index, metadata in enumerate(frame_metadata):
        frame_seq = int(metadata.get("frameSeq", index))
        timing[frame_seq] = (
            int(metadata.get("cameraTimestampUs") or 0),
            int(metadata.get("ptsUs") or 0),
        )
    return timing


def _median_frame_time_delta_us(frame_metadata: list[dict[str, Any]], field_name: str) -> int:
    values: list[int] = []
    previous: int | None = None
    for metadata in frame_metadata:
        value = _int(metadata.get(field_name))
        if value <= 0:
            continue
        if previous is not None and value > previous:
            values.append(value - previous)
        previous = value
    if not values:
        return 33_333
    return int(round(float(np.median(np.asarray(values, dtype=np.float64)))))


def _median_tail_velocity_per_frame(values: Sequence[float], frame_seqs: Sequence[int], tail_points: int = 8) -> float:
    if len(values) < 2:
        return 0.0
    start = max(0, len(values) - int(tail_points))
    velocities: list[float] = []
    for index in range(start, len(values) - 1):
        frame_delta = int(frame_seqs[index + 1]) - int(frame_seqs[index])
        if frame_delta <= 0:
            continue
        velocity = (float(values[index + 1]) - float(values[index])) / float(frame_delta)
        if math.isfinite(velocity):
            velocities.append(velocity)
    if not velocities:
        return 0.0
    return float(np.median(np.asarray(velocities, dtype=np.float64)))


def _pin_deck_completion_frame_count(
    *,
    last: LaneSpaceBallPoint,
    lane_lock: LaneLockResult,
    s_velocity: float,
    x_velocity: float,
    config: TrajectoryReconstructionConfig,
) -> int:
    lane_length = float(lane_lock.lane_length_meters)
    remaining_s = lane_length - float(last.lane_point.s_meters)
    if remaining_s <= 0.001:
        return 0
    if float(last.lane_point.s_meters) < lane_length - float(config.pin_deck_completion_margin_meters):
        return 0

    half_width = float(lane_lock.lane_width_meters) * 0.5
    center_limit = half_width * float(config.pin_deck_completion_half_width_fraction)
    edge_limit = half_width * float(config.pin_deck_completion_edge_guard_fraction)
    last_x = float(last.lane_point.x_meters)
    if abs(last_x) > center_limit:
        return 0

    completion_speed = max(float(s_velocity), float(config.pin_deck_completion_min_speed_m_per_frame))
    completion_speed = min(float(config.terminal_speed_cap_m_per_frame), completion_speed)
    if completion_speed <= 0.0:
        return 0

    frame_count = int(math.ceil(remaining_s / completion_speed))
    frame_count = min(frame_count, int(config.pin_deck_completion_max_frames))
    projected_x_at_deck = last_x + float(x_velocity) * float(frame_count)
    if abs(projected_x_at_deck) > edge_limit:
        return 0
    if last_x * float(x_velocity) > 0.0 and abs(last_x) > half_width * 0.65:
        return 0

    return frame_count


def _build_lane_space_point(
    *,
    measurement: LaneSpaceTrajectoryMeasurement,
    x_meters: float,
    s_meters: float,
    lane_lock: LaneLockResult,
    confidence_scale: float = 1.0,
) -> LaneSpaceBallPoint:
    lane_point = LanePoint(x_meters=float(x_meters), s_meters=float(s_meters), h_meters=0.0)
    world_point_np = lane_coordinates_to_world_point(lane_point, lane_lock)
    world_point = Vector3(
        x=float(world_point_np[0]),
        y=float(world_point_np[1]),
        z=float(world_point_np[2]),
    )
    return LaneSpaceBallPoint(
        schema_version="lane_space_ball_point",
        session_id=measurement.source_point.session_id,
        shot_id=measurement.source_point.shot_id,
        frame_seq=measurement.frame_seq,
        camera_timestamp_us=measurement.camera_timestamp_us,
        pts_us=measurement.pts_us,
        image_point_px=measurement.source_point.image_point_px,
        point_definition=FINAL_TRAJECTORY_POINT_DEFINITION,
        world_point=world_point,
        lane_point=lane_point,
        is_on_locked_lane=is_lane_point_plausible(lane_point, lane_lock),
        projection_confidence=max(0.0, min(1.0, float(measurement.confidence) * float(confidence_scale))),
    )


def _build_terminal_point(
    *,
    previous: LaneSpaceBallPoint,
    frame_seq: int,
    camera_timestamp_us: int,
    pts_us: int,
    x_meters: float,
    s_meters: float,
    lane_lock: LaneLockResult,
    confidence_scale: float,
) -> LaneSpaceBallPoint:
    lane_point = LanePoint(x_meters=float(x_meters), s_meters=float(s_meters), h_meters=0.0)
    world_point_np = lane_coordinates_to_world_point(lane_point, lane_lock)
    return LaneSpaceBallPoint(
        schema_version="lane_space_ball_point",
        session_id=previous.session_id,
        shot_id=previous.shot_id,
        frame_seq=int(frame_seq),
        camera_timestamp_us=int(camera_timestamp_us),
        pts_us=int(pts_us),
        image_point_px=previous.image_point_px,
        point_definition=FINAL_TRAJECTORY_POINT_DEFINITION,
        world_point=Vector3(x=float(world_point_np[0]), y=float(world_point_np[1]), z=float(world_point_np[2])),
        lane_point=lane_point,
        is_on_locked_lane=is_lane_point_plausible(lane_point, lane_lock),
        projection_confidence=max(0.0, min(1.0, float(previous.projection_confidence) * float(confidence_scale))),
    )


def reconstruct_lane_space_trajectory(
    measurements: Sequence[LaneSpaceTrajectoryMeasurement],
    *,
    lane_lock: LaneLockResult,
    frame_metadata: list[dict[str, Any]],
    window_end_frame_seq: int | None = None,
    config: TrajectoryReconstructionConfig | None = None,
) -> list[LaneSpaceBallPoint]:
    resolved_config = config or TrajectoryReconstructionConfig()
    ordered = sorted(measurements, key=lambda measurement: int(measurement.frame_seq))
    if not ordered:
        return []

    smoothed_positions = _spline_smooth_positions(ordered, lane_lock, resolved_config)
    points = [
        _build_lane_space_point(
            measurement=measurement,
            x_meters=float(smoothed_positions[index, 0]),
            s_meters=float(smoothed_positions[index, 1]),
            lane_lock=lane_lock,
        )
        for index, measurement in enumerate(ordered)
    ]

    if not points or window_end_frame_seq is None:
        return points

    last = points[-1]
    missing_frames = max(0, int(window_end_frame_seq) - int(last.frame_seq))
    s_values = [float(point.lane_point.s_meters) for point in points]
    x_values = [float(point.lane_point.x_meters) for point in points]
    frame_seqs = [int(point.frame_seq) for point in points]
    s_velocity = max(0.0, _median_tail_velocity_per_frame(s_values, frame_seqs))
    s_velocity = min(float(resolved_config.terminal_speed_cap_m_per_frame), s_velocity)
    x_velocity = _median_tail_velocity_per_frame(x_values, frame_seqs)
    completion_count = _pin_deck_completion_frame_count(
        last=last,
        lane_lock=lane_lock,
        s_velocity=s_velocity,
        x_velocity=x_velocity,
        config=resolved_config,
    )
    extrapolate_count = max(min(missing_frames, int(resolved_config.max_terminal_frames)), completion_count)
    if extrapolate_count <= 0:
        return points

    lane_length = float(lane_lock.lane_length_meters)
    if completion_count > 0:
        required_velocity = max(0.0, (lane_length - float(last.lane_point.s_meters)) / float(completion_count))
        s_velocity = max(s_velocity, min(float(resolved_config.terminal_speed_cap_m_per_frame), required_velocity))

    timing_by_seq = _frame_timing_by_seq(frame_metadata)
    camera_timestamp_step_us = _median_frame_time_delta_us(frame_metadata, "cameraTimestampUs")
    pts_step_us = _median_frame_time_delta_us(frame_metadata, "ptsUs")
    previous = last
    for offset in range(1, extrapolate_count + 1):
        frame_seq = int(last.frame_seq) + offset
        camera_timestamp_us, pts_us = timing_by_seq.get(
            frame_seq,
            (
                int(previous.camera_timestamp_us) + camera_timestamp_step_us,
                int(previous.pts_us) + pts_step_us,
            ),
        )
        next_s = min(lane_length, float(previous.lane_point.s_meters) + s_velocity)
        next_x = float(previous.lane_point.x_meters) + x_velocity
        x_limit = max(0.01, float(lane_lock.lane_width_meters) * 0.5 + float(resolved_config.smoothing_lateral_margin_meters))
        next_x = max(-x_limit, min(x_limit, next_x))
        previous = _build_terminal_point(
            previous=previous,
            frame_seq=frame_seq,
            camera_timestamp_us=camera_timestamp_us,
            pts_us=pts_us,
            x_meters=next_x,
            s_meters=next_s,
            lane_lock=lane_lock,
            confidence_scale=float(resolved_config.terminal_confidence_scale),
        )
        points.append(previous)
        if completion_count > 0 and float(previous.lane_point.s_meters) >= lane_length - 0.001:
            break

    return points


def trajectory_from_sam2_mask_track(
    *,
    artifact: Any,
    session_id: str,
    shot_id: str,
    lane_lock: LaneLockResult,
    track_csv_path: Path,
    source_frame_idx_start: int,
    window_end_frame_seq: int,
    config: TrajectoryReconstructionConfig | None = None,
) -> list[LaneSpaceBallPoint]:
    resolved_config = config or TrajectoryReconstructionConfig()
    measurements = load_mask_track_measurements(
        artifact=artifact,
        session_id=session_id,
        shot_id=shot_id,
        lane_lock=lane_lock,
        track_csv_path=track_csv_path,
        source_frame_idx_start=source_frame_idx_start,
        config=resolved_config,
    )
    return reconstruct_lane_space_trajectory(
        measurements,
        lane_lock=lane_lock,
        frame_metadata=artifact.frame_metadata,
        window_end_frame_seq=window_end_frame_seq,
        config=resolved_config,
    )
