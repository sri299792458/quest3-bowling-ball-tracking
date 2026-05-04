from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

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


FINAL_TRAJECTORY_POINT_DEFINITION = "camera_sam2_mask_measurement_kalman_rts"


@dataclass(frozen=True)
class TrajectoryReconstructionConfig:
    base_sigma_x_meters: float = 0.035
    base_sigma_s_meters: float = 0.090
    far_sigma_s_meters: float = 0.85
    low_quality_sigma_x_meters: float = 0.070
    low_quality_sigma_s_meters: float = 0.450
    accel_sigma_x_mps2: float = 0.75
    accel_sigma_s_mps2: float = 1.35
    velocity_sigma_x_mps: float = 0.65
    velocity_sigma_s_mps: float = 4.50
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


def _time_seconds(measurements: Sequence[LaneSpaceTrajectoryMeasurement]) -> np.ndarray:
    if not measurements:
        return np.empty(0, dtype=np.float64)
    pts_values = np.asarray([float(measurement.pts_us) for measurement in measurements], dtype=np.float64)
    if np.all(np.isfinite(pts_values)) and np.max(pts_values) > np.min(pts_values):
        return (pts_values - pts_values[0]) / 1_000_000.0
    frame_values = np.asarray([float(measurement.frame_seq) for measurement in measurements], dtype=np.float64)
    return (frame_values - frame_values[0]) / 30.0


def _initial_velocity(values: np.ndarray, times: np.ndarray, *, default: float) -> float:
    if len(values) < 2:
        return float(default)
    count = min(len(values), 8)
    velocities: list[float] = []
    for index in range(count - 1):
        dt = max(float(times[index + 1] - times[index]), 1e-3)
        velocity = float(values[index + 1] - values[index]) / dt
        if math.isfinite(velocity):
            velocities.append(velocity)
    if not velocities:
        return float(default)
    return float(np.median(np.asarray(velocities, dtype=np.float64)))


def _process_noise(dt: float, config: TrajectoryReconstructionConfig) -> np.ndarray:
    dt = max(float(dt), 1e-3)
    qx = float(config.accel_sigma_x_mps2) ** 2
    qs = float(config.accel_sigma_s_mps2) ** 2
    return np.asarray(
        [
            [0.25 * dt**4 * qx, 0.0, 0.5 * dt**3 * qx, 0.0],
            [0.0, 0.25 * dt**4 * qs, 0.0, 0.5 * dt**3 * qs],
            [0.5 * dt**3 * qx, 0.0, dt**2 * qx, 0.0],
            [0.0, 0.5 * dt**3 * qs, 0.0, dt**2 * qs],
        ],
        dtype=np.float64,
    )


def _measurement_noise(
    measurement: LaneSpaceTrajectoryMeasurement,
    lane_lock: LaneLockResult,
    config: TrajectoryReconstructionConfig,
) -> np.ndarray:
    lane_length = max(float(lane_lock.lane_length_meters), 1.0)
    s_norm = max(0.0, min(1.25, float(measurement.s_meters) / lane_length))
    mask_quality = max(0.05, min(1.0, float(measurement.mask_quality)))
    confidence = max(0.05, min(1.0, float(measurement.confidence)))
    sigma_x = (
        float(config.base_sigma_x_meters)
        + 0.03 * s_norm
        + float(config.low_quality_sigma_x_meters) * (1.0 - mask_quality)
    )
    sigma_s = (
        float(config.base_sigma_s_meters)
        + float(config.far_sigma_s_meters) * (s_norm**2)
        + float(config.low_quality_sigma_s_meters) * (1.0 - mask_quality)
    )
    confidence_scale = 1.0 / math.sqrt(confidence)
    sigma_x *= confidence_scale
    sigma_s *= confidence_scale
    return np.diag([sigma_x**2, sigma_s**2])


def _kalman_rts_smooth(
    measurements: Sequence[LaneSpaceTrajectoryMeasurement],
    lane_lock: LaneLockResult,
    config: TrajectoryReconstructionConfig,
) -> np.ndarray:
    if not measurements:
        return np.empty((0, 4), dtype=np.float64)

    x_values = np.asarray([measurement.x_meters for measurement in measurements], dtype=np.float64)
    s_values = np.asarray([measurement.s_meters for measurement in measurements], dtype=np.float64)
    times = _time_seconds(measurements)
    n = len(measurements)

    states_filter = np.zeros((n, 4), dtype=np.float64)
    states_predict = np.zeros((n, 4), dtype=np.float64)
    cov_filter = np.zeros((n, 4, 4), dtype=np.float64)
    cov_predict = np.zeros((n, 4, 4), dtype=np.float64)
    transitions = np.zeros((n, 4, 4), dtype=np.float64)

    state = np.asarray(
        [
            float(x_values[0]),
            float(s_values[0]),
            _initial_velocity(x_values, times, default=0.0),
            max(0.0, _initial_velocity(s_values, times, default=5.0)),
        ],
        dtype=np.float64,
    )
    cov = np.diag(
        [
            float(config.base_sigma_x_meters) ** 2,
            float(config.base_sigma_s_meters) ** 2,
            float(config.velocity_sigma_x_mps) ** 2,
            float(config.velocity_sigma_s_mps) ** 2,
        ]
    )
    h_matrix = np.asarray([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    identity = np.eye(4, dtype=np.float64)

    for index, measurement in enumerate(measurements):
        if index == 0:
            transition = identity.copy()
            predicted_state = state.copy()
            predicted_cov = cov.copy()
        else:
            dt = max(float(times[index] - times[index - 1]), 1e-3)
            transition = np.asarray(
                [
                    [1.0, 0.0, dt, 0.0],
                    [0.0, 1.0, 0.0, dt],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )
            predicted_state = transition @ state
            predicted_state[3] = max(0.0, float(predicted_state[3]))
            predicted_cov = transition @ cov @ transition.T + _process_noise(dt, config)

        z_value = np.asarray([measurement.x_meters, measurement.s_meters], dtype=np.float64)
        r_matrix = _measurement_noise(measurement, lane_lock, config)
        innovation = z_value - h_matrix @ predicted_state
        if abs(float(innovation[0])) > 0.60 or abs(float(innovation[1])) > 2.50:
            r_matrix = r_matrix * 8.0

        residual_cov = h_matrix @ predicted_cov @ h_matrix.T + r_matrix
        kalman_gain = predicted_cov @ h_matrix.T @ np.linalg.inv(residual_cov)
        state = predicted_state + kalman_gain @ innovation
        state[3] = max(0.0, float(state[3]))
        cov = (identity - kalman_gain @ h_matrix) @ predicted_cov

        transitions[index] = transition
        states_predict[index] = predicted_state
        cov_predict[index] = predicted_cov
        states_filter[index] = state
        cov_filter[index] = cov

    states_smooth = states_filter.copy()
    cov_smooth = cov_filter.copy()
    for index in range(n - 2, -1, -1):
        transition = transitions[index + 1]
        smoother_gain = cov_filter[index] @ transition.T @ np.linalg.inv(cov_predict[index + 1])
        states_smooth[index] = states_filter[index] + smoother_gain @ (
            states_smooth[index + 1] - states_predict[index + 1]
        )
        cov_smooth[index] = cov_filter[index] + smoother_gain @ (
            cov_smooth[index + 1] - cov_predict[index + 1]
        ) @ smoother_gain.T

    lane_length = float(lane_lock.lane_length_meters)
    lateral_limit = max(0.01, float(lane_lock.lane_width_meters) * 0.5 + float(config.smoothing_lateral_margin_meters))
    states_smooth[:, 0] = np.clip(states_smooth[:, 0], -lateral_limit, lateral_limit)
    states_smooth[:, 1] = np.clip(states_smooth[:, 1], 0.0, lane_length)
    states_smooth[:, 1] = np.maximum.accumulate(states_smooth[:, 1])
    states_smooth[:, 3] = np.maximum(states_smooth[:, 3], 0.0)
    return states_smooth


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

    states = _kalman_rts_smooth(ordered, lane_lock, resolved_config)
    points = [
        _build_lane_space_point(
            measurement=measurement,
            x_meters=float(states[index, 0]),
            s_meters=float(states[index, 1]),
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
