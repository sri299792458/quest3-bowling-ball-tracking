from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _json_safe(value):
    try:
        import numpy as np
    except ModuleNotFoundError:
        np = None

    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class ContinuityThresholds:
    rotation_warning_deg: float = 8.0
    rotation_fail_deg: float = 15.0
    position_warning_m: float = 0.35
    position_fail_m: float = 0.65
    min_visible_corners: int = 4
    min_in_bounds_corners: int = 4
    min_edge_score_warning: float = 0.7
    min_edge_score_fail: float = 0.55

    @classmethod
    def from_json(cls, path: Path) -> "ContinuityThresholds":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            rotation_warning_deg=float(payload["rotation_warning_deg"]),
            rotation_fail_deg=float(payload["rotation_fail_deg"]),
            position_warning_m=float(payload["position_warning_m"]),
            position_fail_m=float(payload["position_fail_m"]),
            min_visible_corners=int(payload["min_visible_corners"]),
            min_in_bounds_corners=int(payload["min_in_bounds_corners"]),
            min_edge_score_warning=float(payload["min_edge_score_warning"]),
            min_edge_score_fail=float(payload["min_edge_score_fail"]),
        )

    def to_dict(self) -> dict:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class LaneLock:
    run_name: str
    reference_frame_idx: int
    reference_source_frame_id: int
    reference_timestamp_us: int
    frame_file_name: str
    annotation_path: str
    intrinsics_path: str
    lane_config_path: str
    point_order: list[str]
    selected_candidate_ids: list[int]
    reference_near_points_xy: list[list[float]]
    lane_points_world: list[list[float]]
    image_points_xy: list[list[float] | None]
    confidence: float
    confidence_label: str
    reference_camera_position_world: list[float]
    reference_camera_rotation_xyzw: list[float]
    lane_width_m: float
    lane_length_m: float
    plane_normal_world: list[float]
    lane_axes_world: dict[str, list[float]]
    world_to_lane_matrix: list[list[float]]
    lane_to_world_matrix: list[list[float]]
    corner_residuals_m: list[float]
    max_corner_residual_m: float
    reference_edge_score: float | None
    debug: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict) -> "LaneLock":
        return cls(**payload)

    @classmethod
    def from_json(cls, path: Path) -> "LaneLock":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ContinuityAssessment:
    status: str
    reference_run_name: str
    reference_frame_idx: int
    check_run_name: str
    check_frame_idx: int
    check_source_frame_id: int
    check_timestamp_us: int
    rotation_delta_deg: float
    position_delta_m: float
    visible_corners: int
    in_bounds_corners: int
    edge_score: float | None
    projection_area_px2: float | None
    reason_codes: list[str]
    recommendation: str
    projected_image_points_xy: list[list[float] | None]
    debug: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict) -> "ContinuityAssessment":
        return cls(**payload)

    @classmethod
    def from_json(cls, path: Path) -> "ContinuityAssessment":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class SimulationSummary:
    scenario_name: str
    raw_root: str
    initial_recording_number: int
    initial_annotation_path: str
    intrinsics_path: str
    lane_config_path: str
    check_mode: str
    thresholds: dict
    relock_annotation_root: str | None
    relock_count: int
    recording_results: list[dict]

    def to_dict(self) -> dict:
        return _json_safe(asdict(self))
