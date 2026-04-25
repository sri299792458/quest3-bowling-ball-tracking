from __future__ import annotations

from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_LANE_ROOT = WORKSPACE_ROOT / "lane_detection_v1_runtime"
DEFAULT_RAW_ROOT = WORKSPACE_ROOT / "data" / "raw_runs" / "raw_upload_bundle"
DEFAULT_INTRINSICS_PATH = WORKSPACE_ROOT / "config" / "camera_intrinsics_reference_run.json"
DEFAULT_LANE_CONFIG_PATH = WORKSPACE_ROOT / "config" / "lane_dimensions.json"
DEFAULT_RECORDING_ANNOTATION_ROOT = WORKSPACE_ROOT / "annotations"
DEFAULT_OUTPUT_ROOT = WORKSPACE_ROOT / "outputs"
DEFAULT_CALIBRATION_OUTPUT_ROOT = WORKSPACE_ROOT / "calibration output"
