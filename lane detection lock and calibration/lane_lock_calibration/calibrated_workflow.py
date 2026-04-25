from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .geometry import quaternion_distance_deg
from .lane_lock_service import build_lane_lock_from_annotation
from .legacy import load_legacy_lane_modules, load_legacy_recording_workflow_module


@dataclass(frozen=True)
class BoundaryContinuityAssessment:
    status: str
    active_calibration_recording_number: int
    active_calibration_run_name: str
    current_recording_number: int
    current_run_name: str
    anchor_first_source_frame_id: int
    current_first_source_frame_id: int
    anchor_first_timestamp_us: int
    current_first_timestamp_us: int
    rotation_delta_deg: float
    position_delta_m: float
    reason_codes: list[str]
    recommendation: str
    prompt_required: bool
    debug: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "active_calibration_recording_number": self.active_calibration_recording_number,
            "active_calibration_run_name": self.active_calibration_run_name,
            "current_recording_number": self.current_recording_number,
            "current_run_name": self.current_run_name,
            "anchor_first_source_frame_id": self.anchor_first_source_frame_id,
            "current_first_source_frame_id": self.current_first_source_frame_id,
            "anchor_first_timestamp_us": self.anchor_first_timestamp_us,
            "current_first_timestamp_us": self.current_first_timestamp_us,
            "rotation_delta_deg": self.rotation_delta_deg,
            "position_delta_m": self.position_delta_m,
            "reason_codes": self.reason_codes,
            "recommendation": self.recommendation,
            "prompt_required": self.prompt_required,
            "debug": self.debug,
        }


def assess_recording_boundary_continuity(
    *,
    active_calibration_recording_number: int,
    active_calibration_run_name: str,
    anchor_first_record,
    current_recording_number: int,
    current_run_name: str,
    current_first_record,
    rotation_warning_deg: float,
    rotation_fail_deg: float,
) -> BoundaryContinuityAssessment:
    rotation_delta_deg = quaternion_distance_deg(
        np.asarray(anchor_first_record.camera_rotation, dtype=np.float64),
        np.asarray(current_first_record.camera_rotation, dtype=np.float64),
    )
    position_delta_m = float(
        np.linalg.norm(
            np.asarray(current_first_record.camera_position, dtype=np.float64)
            - np.asarray(anchor_first_record.camera_position, dtype=np.float64)
        )
    )

    reason_codes: list[str] = []
    if rotation_delta_deg >= rotation_fail_deg:
        status = "recalibration_required"
        reason_codes.append("rotation_fail")
        recommendation = "Metadata continuity changed enough that a fresh lane calibration is required."
        prompt_required = True
    elif rotation_delta_deg >= rotation_warning_deg:
        status = "continuity_warning"
        reason_codes.append("rotation_warning")
        recommendation = "Metadata continuity drifted noticeably. Recalibration is suggested, but not forced."
        prompt_required = True
    else:
        status = "lane_locked"
        recommendation = "Metadata continuity still matches the current lane calibration."
        prompt_required = False

    return BoundaryContinuityAssessment(
        status=status,
        active_calibration_recording_number=active_calibration_recording_number,
        active_calibration_run_name=active_calibration_run_name,
        current_recording_number=current_recording_number,
        current_run_name=current_run_name,
        anchor_first_source_frame_id=int(anchor_first_record.source_frame_id),
        current_first_source_frame_id=int(current_first_record.source_frame_id),
        anchor_first_timestamp_us=int(anchor_first_record.timestamp_us),
        current_first_timestamp_us=int(current_first_record.timestamp_us),
        rotation_delta_deg=float(rotation_delta_deg),
        position_delta_m=float(position_delta_m),
        reason_codes=reason_codes,
        recommendation=recommendation,
        prompt_required=prompt_required,
        debug={
            "anchor_first_camera_position": np.asarray(anchor_first_record.camera_position, dtype=np.float64).tolist(),
            "anchor_first_camera_rotation": np.asarray(anchor_first_record.camera_rotation, dtype=np.float64).tolist(),
            "current_first_camera_position": np.asarray(current_first_record.camera_position, dtype=np.float64).tolist(),
            "current_first_camera_rotation": np.asarray(current_first_record.camera_rotation, dtype=np.float64).tolist(),
            "rotation_warning_deg": float(rotation_warning_deg),
            "rotation_fail_deg": float(rotation_fail_deg),
        },
    )


def _render_boundary_prompt(
    *,
    prompt_image_bgr: np.ndarray,
    recording_number: int,
    recording_count: int,
    assessment: BoundaryContinuityAssessment,
) -> str:
    window_name = "Calibration Prompt"

    import cv2

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        while True:
            display = prompt_image_bgr.copy()
            cv2.imshow(window_name, display)
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                return "quit"
            if key == ord("k"):
                return "skip"
            if key == ord("c"):
                return "recalibrate"
            if assessment.status == "continuity_warning" and key in (ord("s"), 13, 32):
                return "continue"
    finally:
        cv2.destroyWindow(window_name)


def build_boundary_prompt_image(
    *,
    first_frame_bgr: np.ndarray,
    recording_number: int,
    recording_count: int,
    assessment: BoundaryContinuityAssessment,
    active_lane_lock,
    current_first_record,
    intrinsics,
) -> np.ndarray:
    legacy = load_legacy_lane_modules()
    draw_header_lines = legacy["draw_header_lines"]
    draw_lane_polygon = legacy["draw_lane_polygon"]
    project_world_points = legacy["project_world_points"]

    display = first_frame_bgr.copy()
    projected_image_points_xy = None
    try:
        projected = project_world_points(
            current_first_record,
            intrinsics,
            np.asarray(active_lane_lock.lane_points_world, dtype=np.float64),
        )
        projected_image_points_xy = projected["image_points_xy"]
    except Exception:
        projected_image_points_xy = None

    if projected_image_points_xy is not None:
        edge_color_bgr = (0, 165, 255) if assessment.status == "continuity_warning" else (0, 0, 255)
        draw_lane_polygon(
            display,
            projected_image_points_xy,
            labels=active_lane_lock.point_order,
            edge_color_bgr=edge_color_bgr,
            point_color_bgr=edge_color_bgr,
            thickness=2,
        )

    prompt_line = (
        "Keys: c recalibrate | k skip recording | q quit"
        if assessment.status == "recalibration_required"
        else "Keys: c recalibrate | s continue current lock | k skip recording | q quit"
    )
    draw_header_lines(
        display,
        [
            f"Recording {recording_number}/{recording_count} | {assessment.status}",
            f"current run: {assessment.current_run_name}",
            (
                f"active calibration: recording{assessment.active_calibration_recording_number}"
                f" | rot delta {assessment.rotation_delta_deg:.2f} deg"
            ),
            assessment.recommendation,
            prompt_line,
        ],
        color_bgr=(0, 220, 255) if assessment.status == "continuity_warning" else (0, 0, 255),
    )
    return display


def choose_or_create_annotation(
    *,
    run,
    recording_number: int,
    recording_count: int,
    max_candidates: int,
    existing_annotation_path: Path | None,
    auto_use_existing_annotation: bool,
):
    workflow_utils = load_legacy_recording_workflow_module()

    if existing_annotation_path is not None and auto_use_existing_annotation:
        if not existing_annotation_path.exists():
            raise FileNotFoundError(f"Existing annotation was requested but not found: {existing_annotation_path}")
        return "saved", json.loads(existing_annotation_path.read_text(encoding="utf-8"))

    while True:
        reference_status, reference_frame_idx = workflow_utils.select_reference_frame(
            run=run,
            recording_number=recording_number,
            recording_count=recording_count,
        )
        if reference_status == "quit":
            return "quit", None
        if reference_status == "skip":
            return "skip", None
        if reference_frame_idx is None:
            raise RuntimeError("Reference frame selection returned no frame index.")

        annotation_result = workflow_utils.annotate_reference_points(
            run=run,
            frame_idx=reference_frame_idx,
            recording_number=recording_number,
            recording_count=recording_count,
            max_candidates=max_candidates,
        )
        if annotation_result.status == "quit":
            return "quit", None
        if annotation_result.status == "skip":
            return "skip", None
        if annotation_result.status == "back":
            continue
        if annotation_result.payload is None:
            raise RuntimeError("Annotation UI returned no payload.")
        return "saved", annotation_result.payload


def render_recording_with_active_lane_lock(
    *,
    run,
    recording_number: int,
    recording_count: int,
    recording_dir: Path,
    active_lane_lock,
    active_calibration_recording_number: int,
    intrinsics,
    video_name: str,
    video_fps: float,
) -> None:
    legacy = load_legacy_lane_modules()
    draw_header_lines = legacy["draw_header_lines"]
    draw_lane_polygon = legacy["draw_lane_polygon"]
    project_world_points = legacy["project_world_points"]

    lane_points_world = np.asarray(active_lane_lock.lane_points_world, dtype=np.float64)
    time_origin_us = int(run.frame_records[0].timestamp_us) if run.frame_records else 0

    output_dir = recording_dir / "continuous_reprojection"
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "continuous_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    projections = []
    for record in run.frame_records:
        projected = project_world_points(record, intrinsics, lane_points_world)
        relative_seconds = (int(record.timestamp_us) - time_origin_us) / 1_000_000.0
        projections.append(
            {
                "local_frame_idx": int(record.local_frame_idx),
                "source_frame_id": int(record.source_frame_id),
                "timestamp_us": int(record.timestamp_us),
                "relative_seconds": float(relative_seconds),
                "image_points_xy": projected["image_points_xy"],
                "visibility": projected["visibility"],
                "depths": projected["depths"],
            }
        )

    workflow_utils = load_legacy_recording_workflow_module()
    frame_width, frame_height = run.infer_image_size()
    video_writer, video_path, video_codec = workflow_utils.create_video_writer(
        preferred_video_path=output_dir / video_name,
        fps=video_fps,
        frame_size=(frame_width, frame_height),
    )

    try:
        for index, projection in enumerate(projections):
            frame_idx = int(projection["local_frame_idx"])
            image = run.load_frame_bgr(frame_idx)
            draw_lane_polygon(
                image,
                projection["image_points_xy"],
                labels=active_lane_lock.point_order,
                edge_color_bgr=(255, 120, 0),
                point_color_bgr=(0, 0, 255),
                thickness=2,
            )
            draw_header_lines(
                image,
                [
                    f"Calibration workflow | recording {recording_number}/{recording_count}",
                    (
                        f"active calibration: recording{active_calibration_recording_number}"
                        f" frame {active_lane_lock.reference_frame_idx}"
                    ),
                    f"frame {frame_idx} | {projection['relative_seconds']:+.2f}s in run",
                ],
            )
            frame_path = frames_dir / f"{frame_idx:04d}.jpg"
            import cv2

            cv2.imwrite(str(frame_path), image)
            repeat_count = workflow_utils.video_repeat_count_for_projection(
                projections=projections,
                index=index,
                output_video_fps=video_fps,
            )
            for _ in range(repeat_count):
                video_writer.write(image)
    finally:
        video_writer.release()

    summary = {
        "run_name": run.run_name,
        "recording_number": int(recording_number),
        "recording_count": int(recording_count),
        "active_calibration_recording_number": int(active_calibration_recording_number),
        "active_calibration_run_name": active_lane_lock.run_name,
        "active_calibration_reference_frame_idx": int(active_lane_lock.reference_frame_idx),
        "continuous_projection_count": len(projections),
        "write_video": True,
        "save_all_frame_overlays": True,
        "video_fps_requested": float(video_fps),
        "video_path": str(video_path),
        "video_codec": video_codec,
        "video_timing": workflow_utils.build_video_timing_summary(projections, video_fps),
    }

    (recording_dir / "applied_lane_lock.json").write_text(
        json.dumps(active_lane_lock.to_dict(), indent=2),
        encoding="utf-8",
    )
    (recording_dir / "recording_metadata.json").write_text(
        json.dumps(
            {
                "recording_number": int(recording_number),
                "recording_count": int(recording_count),
                "source_run_name": run.run_name,
                "source_run_dir": str(run.run_dir),
                "frame_count": len(run.frame_records),
                "active_calibration_recording_number": int(active_calibration_recording_number),
                "active_calibration_run_name": active_lane_lock.run_name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "projected_lane_corners_all_frames.json").write_text(
        json.dumps(projections, indent=2),
        encoding="utf-8",
    )
    (output_dir / "projection_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _write_session_summary_markdown(summary: dict, output_path: Path) -> None:
    lines = [
        "# Calibration Session Summary",
        "",
        f"- Session: `{summary['session_name']}`",
        f"- Recording range: `recording{summary['start_recording']} -> recording{summary['end_recording']}`",
        f"- Calibration recordings: `{', '.join(f'recording{value}' for value in summary['calibration_recordings'])}`",
        "",
        "## Recording Results",
        "",
        "| Recording | Boundary Status | Decision | Active Calibration |",
        "| --- | --- | --- | --- |",
    ]
    for result in summary["recording_results"]:
        lines.append(
            f"| recording{result['recording_number']} | {result['boundary_status']} | "
            f"{result['decision']} | recording{result['active_calibration_recording_number_after_recording']} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_calibrated_session_workflow(
    *,
    raw_root: Path,
    output_root: Path,
    intrinsics_path: Path,
    lane_config_path: Path,
    start_recording: int,
    end_recording: int | None,
    max_candidates: int,
    video_name: str,
    video_fps: float,
    rotation_warning_deg: float,
    rotation_fail_deg: float,
    annotation_root: Path | None,
    auto_use_existing_annotations: bool,
    auto_continue_warnings: bool,
    auto_recalibrate_required: bool,
    session_name: str | None = None,
) -> dict:
    legacy = load_legacy_lane_modules()
    list_run_dirs = legacy["list_run_dirs"]
    load_run = legacy["load_run"]
    CameraIntrinsics = legacy["CameraIntrinsics"]

    run_dirs = list_run_dirs(raw_root)
    if not run_dirs:
        raise FileNotFoundError(f"No raw runs found under {raw_root}")

    start_index = max(1, int(start_recording))
    end_index = len(run_dirs) if end_recording is None else min(len(run_dirs), int(end_recording))
    if start_index > end_index:
        raise ValueError("The selected recording range is empty.")

    session_name = session_name or datetime.now().strftime("session_%Y%m%d_%H%M%S")
    session_output_dir = output_root / session_name
    session_output_dir.mkdir(parents=True, exist_ok=True)

    intrinsics = CameraIntrinsics.from_json(intrinsics_path)
    recording_results: list[dict] = []
    calibration_recordings: list[int] = []
    active_lane_lock = None
    active_calibration_recording_number = None
    active_anchor_first_record = None

    selected_run_dirs = run_dirs[start_index - 1 : end_index]
    recording_count = len(run_dirs)

    for recording_number, run_dir in enumerate(selected_run_dirs, start=start_index):
        run = load_run(run_dir)
        recording_dir = session_output_dir / f"recording{recording_number}"
        recording_dir.mkdir(parents=True, exist_ok=True)
        existing_annotation_path = (
            None
            if annotation_root is None
            else annotation_root / f"recording{recording_number}" / "reference_annotation.json"
        )

        if active_lane_lock is None:
            annotation_status, annotation_payload = choose_or_create_annotation(
                run=run,
                recording_number=recording_number,
                recording_count=recording_count,
                max_candidates=max_candidates,
                existing_annotation_path=existing_annotation_path,
                auto_use_existing_annotation=auto_use_existing_annotations,
            )
            if annotation_status == "quit":
                break
            if annotation_status == "skip":
                recording_results.append(
                    {
                        "recording_number": int(recording_number),
                        "run_name": run.run_name,
                        "boundary_status": "initial_calibration_required",
                        "decision": "skip",
                        "active_calibration_recording_number_after_recording": None,
                    }
                )
                continue
            annotation_path = recording_dir / "reference_annotation.json"
            annotation_path.write_text(json.dumps(annotation_payload, indent=2), encoding="utf-8")
            active_lane_lock = build_lane_lock_from_annotation(
                run_dir=run_dir,
                annotation_path=annotation_path,
                intrinsics_path=intrinsics_path,
                lane_config_path=lane_config_path,
                output_dir=recording_dir,
            )
            active_calibration_recording_number = int(recording_number)
            active_anchor_first_record = run.frame_records[0]
            calibration_recordings.append(int(recording_number))
            render_recording_with_active_lane_lock(
                run=run,
                recording_number=recording_number,
                recording_count=recording_count,
                recording_dir=recording_dir,
                active_lane_lock=active_lane_lock,
                active_calibration_recording_number=active_calibration_recording_number,
                intrinsics=intrinsics,
                video_name=video_name,
                video_fps=video_fps,
            )
            (recording_dir / "boundary_continuity.json").write_text(
                json.dumps(
                    {
                        "status": "initial_calibration_required",
                        "decision": "calibrate",
                        "recommendation": "No active lane lock existed yet.",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            recording_results.append(
                {
                    "recording_number": int(recording_number),
                    "run_name": run.run_name,
                    "boundary_status": "initial_calibration_required",
                    "decision": "calibrate",
                    "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
                }
            )
            continue

        current_first_record = run.frame_records[0]
        boundary_assessment = assess_recording_boundary_continuity(
            active_calibration_recording_number=int(active_calibration_recording_number),
            active_calibration_run_name=active_lane_lock.run_name,
            anchor_first_record=active_anchor_first_record,
            current_recording_number=int(recording_number),
            current_run_name=run.run_name,
            current_first_record=current_first_record,
            rotation_warning_deg=rotation_warning_deg,
            rotation_fail_deg=rotation_fail_deg,
        )
        boundary_path = recording_dir / "boundary_continuity.json"
        boundary_path.write_text(json.dumps(boundary_assessment.to_dict(), indent=2), encoding="utf-8")
        prompt_image = build_boundary_prompt_image(
            first_frame_bgr=run.load_frame_bgr(0),
            recording_number=recording_number,
            recording_count=recording_count,
            assessment=boundary_assessment,
            active_lane_lock=active_lane_lock,
            current_first_record=current_first_record,
            intrinsics=intrinsics,
        )

        import cv2

        cv2.imwrite(str(recording_dir / "boundary_prompt_preview.jpg"), prompt_image)

        if boundary_assessment.status == "lane_locked":
            decision = "continue"
        elif boundary_assessment.status == "continuity_warning" and auto_continue_warnings:
            decision = "continue"
        elif boundary_assessment.status == "recalibration_required" and auto_recalibrate_required:
            decision = "recalibrate"
        else:
            decision = _render_boundary_prompt(
                prompt_image_bgr=prompt_image,
                recording_number=recording_number,
                recording_count=recording_count,
                assessment=boundary_assessment,
            )

        if decision == "quit":
            recording_results.append(
                {
                    "recording_number": int(recording_number),
                    "run_name": run.run_name,
                    "boundary_status": boundary_assessment.status,
                    "decision": "quit",
                    "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
                }
            )
            break
        if decision == "skip":
            recording_results.append(
                {
                    "recording_number": int(recording_number),
                    "run_name": run.run_name,
                    "boundary_status": boundary_assessment.status,
                    "decision": "skip",
                    "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
                }
            )
            continue
        if decision == "recalibrate":
            annotation_status, annotation_payload = choose_or_create_annotation(
                run=run,
                recording_number=recording_number,
                recording_count=recording_count,
                max_candidates=max_candidates,
                existing_annotation_path=existing_annotation_path,
                auto_use_existing_annotation=auto_use_existing_annotations,
            )
            if annotation_status == "quit":
                recording_results.append(
                    {
                        "recording_number": int(recording_number),
                        "run_name": run.run_name,
                        "boundary_status": boundary_assessment.status,
                        "decision": "quit",
                        "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
                    }
                )
                break
            if annotation_status == "skip":
                recording_results.append(
                    {
                        "recording_number": int(recording_number),
                        "run_name": run.run_name,
                        "boundary_status": boundary_assessment.status,
                        "decision": "skip",
                        "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
                    }
                )
                continue
            annotation_path = recording_dir / "reference_annotation.json"
            annotation_path.write_text(json.dumps(annotation_payload, indent=2), encoding="utf-8")
            active_lane_lock = build_lane_lock_from_annotation(
                run_dir=run_dir,
                annotation_path=annotation_path,
                intrinsics_path=intrinsics_path,
                lane_config_path=lane_config_path,
                output_dir=recording_dir,
            )
            active_calibration_recording_number = int(recording_number)
            active_anchor_first_record = run.frame_records[0]
            calibration_recordings.append(int(recording_number))

        render_recording_with_active_lane_lock(
            run=run,
            recording_number=recording_number,
            recording_count=recording_count,
            recording_dir=recording_dir,
            active_lane_lock=active_lane_lock,
            active_calibration_recording_number=int(active_calibration_recording_number),
            intrinsics=intrinsics,
            video_name=video_name,
            video_fps=video_fps,
        )
        recording_results.append(
            {
                "recording_number": int(recording_number),
                "run_name": run.run_name,
                "boundary_status": boundary_assessment.status,
                "decision": decision,
                "active_calibration_recording_number_after_recording": int(active_calibration_recording_number),
            }
        )

    summary = {
        "session_name": session_name,
        "raw_root": str(raw_root),
        "output_root": str(session_output_dir),
        "intrinsics_path": str(intrinsics_path),
        "lane_config_path": str(lane_config_path),
        "start_recording": int(start_index),
        "end_recording": int(end_index),
        "rotation_warning_deg": float(rotation_warning_deg),
        "rotation_fail_deg": float(rotation_fail_deg),
        "calibration_recordings": calibration_recordings,
        "recording_results": recording_results,
    }
    (session_output_dir / "session_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_session_summary_markdown(summary, session_output_dir / "session_summary.md")
    return summary
