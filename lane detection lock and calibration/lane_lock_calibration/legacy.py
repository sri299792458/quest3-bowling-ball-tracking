from __future__ import annotations

import importlib.util
import sys

from .paths import LEGACY_LANE_ROOT


def ensure_legacy_lane_detection_path():
    if not LEGACY_LANE_ROOT.exists():
        raise FileNotFoundError(f"Bundled lane-detection runtime not found: {LEGACY_LANE_ROOT}")
    path_text = str(LEGACY_LANE_ROOT)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
    return LEGACY_LANE_ROOT


def load_legacy_lane_modules() -> dict:
    ensure_legacy_lane_detection_path()
    from src.edge_refinement import build_edge_context, score_lane_projection
    from src.frame_dataset import list_run_dirs, load_run
    from src.overlay_rendering import draw_click_points, draw_header_lines, draw_lane_polygon
    from src.two_click_lane_solver import POINT_ORDER, solve_lane_from_two_clicks
    from src.world_projection import CameraIntrinsics, LaneDimensions, project_world_points

    return {
        "CameraIntrinsics": CameraIntrinsics,
        "LaneDimensions": LaneDimensions,
        "POINT_ORDER": POINT_ORDER,
        "build_edge_context": build_edge_context,
        "draw_click_points": draw_click_points,
        "draw_header_lines": draw_header_lines,
        "draw_lane_polygon": draw_lane_polygon,
        "list_run_dirs": list_run_dirs,
        "load_run": load_run,
        "project_world_points": project_world_points,
        "score_lane_projection": score_lane_projection,
        "solve_lane_from_two_clicks": solve_lane_from_two_clicks,
    }


def load_legacy_recording_workflow_module():
    ensure_legacy_lane_detection_path()
    workflow_path = LEGACY_LANE_ROOT / "scripts" / "run_recording_workflow.py"
    if not workflow_path.exists():
        raise FileNotFoundError(f"Legacy workflow script not found: {workflow_path}")

    module_name = "legacy_run_recording_workflow"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(module_name, workflow_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load import spec for {workflow_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
