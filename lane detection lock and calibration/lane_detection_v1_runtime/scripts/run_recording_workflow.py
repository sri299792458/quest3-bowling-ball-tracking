from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from src.candidate_point_detection import detect_candidate_points, find_nearest_candidate
from src.frame_dataset import load_run
from src.overlay_rendering import draw_candidate_points, draw_click_points, draw_header_lines, draw_lane_polygon
from src.two_click_lane_solver import POINT_ORDER, solve_lane_from_two_clicks
from src.world_projection import CameraIntrinsics, LaneDimensions, project_world_points


TWO_CLICK_LABELS = ["near_left", "near_right"]
SNAP_RADIUS_PX = 28.0


@dataclass(frozen=True)
class AnnotationResult:
    status: str
    payload: dict | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive recording-by-recording workflow for choosing a reference frame, selecting two suggested lane points, and rendering full-run outputs."
    )
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=WORKSPACE_ROOT / "data" / "raw_runs" / "raw_upload_bundle",
        help="Directory containing all raw recording folders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=WORKSPACE_ROOT / "final outputs",
        help="Root directory where recording1, recording2, ... outputs will be written.",
    )
    parser.add_argument(
        "--intrinsics",
        type=Path,
        default=WORKSPACE_ROOT / "config" / "camera_intrinsics_reference_run.json",
        help="Camera intrinsics JSON.",
    )
    parser.add_argument(
        "--lane-config",
        type=Path,
        default=WORKSPACE_ROOT / "config" / "lane_dimensions.json",
        help="Lane dimensions JSON.",
    )
    parser.add_argument(
        "--start-recording",
        type=int,
        default=1,
        help="1-based recording index to start from.",
    )
    parser.add_argument(
        "--end-recording",
        type=int,
        default=None,
        help="1-based recording index to stop at. Defaults to the final recording.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=26,
        help="Maximum number of suggested candidate points to display on the chosen reference frame.",
    )
    parser.add_argument(
        "--video-name",
        type=str,
        default="two_click_continuous_lane_overlay.mp4",
        help="Output filename for the rendered overlay video.",
    )
    parser.add_argument(
        "--video-fps",
        type=float,
        default=30.0,
        help="Output video FPS used when timestamp pacing duplicates frames to preserve real-time playback.",
    )
    parser.add_argument(
        "--auto-reference-frame",
        type=int,
        default=None,
        help="Optional non-interactive reference frame index used for smoke tests.",
    )
    parser.add_argument(
        "--auto-candidate-ids",
        type=int,
        nargs=2,
        default=None,
        metavar=("NEAR_LEFT_ID", "NEAR_RIGHT_ID"),
        help="Optional non-interactive candidate IDs used for smoke tests.",
    )
    return parser.parse_args()


def main() -> None:
    try:
        import cv2  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "OpenCV is required for the workflow UI. Install this workspace's requirements.txt first."
        ) from exc

    args = parse_args()
    run_dirs = list_run_dirs(args.raw_root)
    if not run_dirs:
        raise SystemExit(f"No recording folders were found under {args.raw_root}")

    intrinsics = CameraIntrinsics.from_json(args.intrinsics)
    lane_dimensions = LaneDimensions.from_json(args.lane_config)

    start_index = max(1, int(args.start_recording))
    end_index = len(run_dirs) if args.end_recording is None else min(len(run_dirs), int(args.end_recording))
    if start_index > end_index:
        raise SystemExit("The selected recording range is empty.")

    selected_run_dirs = run_dirs[start_index - 1 : end_index]
    args.output_root.mkdir(parents=True, exist_ok=True)

    for run_offset, run_dir in enumerate(selected_run_dirs, start=start_index):
        status = process_recording(
            recording_number=run_offset,
            recording_count=len(run_dirs),
            run_dir=run_dir,
            output_root=args.output_root,
            intrinsics=intrinsics,
            lane_dimensions=lane_dimensions,
            max_candidates=max(2, int(args.max_candidates)),
            video_name=args.video_name,
            video_fps=max(1.0, float(args.video_fps)),
            auto_reference_frame=args.auto_reference_frame,
            auto_candidate_ids=args.auto_candidate_ids,
        )
        if status == "quit":
            print("Workflow stopped by user.")
            break


def list_run_dirs(raw_root: Path) -> list[Path]:
    if not raw_root.exists():
        raise FileNotFoundError(f"Raw recording root does not exist: {raw_root}")
    return sorted(path for path in raw_root.iterdir() if path.is_dir() and (path / "raw" / "frames.jsonl").exists())


def process_recording(
    recording_number: int,
    recording_count: int,
    run_dir: Path,
    output_root: Path,
    intrinsics: CameraIntrinsics,
    lane_dimensions: LaneDimensions,
    max_candidates: int,
    video_name: str,
    video_fps: float,
    auto_reference_frame: int | None,
    auto_candidate_ids: list[int] | None,
) -> str:
    run = load_run(run_dir)
    recording_dir = output_root / f"recording{recording_number}"
    recording_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = recording_dir / "recording_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "recording_number": recording_number,
                "recording_count": recording_count,
                "source_run_name": run.run_name,
                "source_run_dir": str(run_dir),
                "frame_count": len(run.frame_records),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    while True:
        if auto_reference_frame is None:
            reference_status, reference_frame_idx = select_reference_frame(
                run=run,
                recording_number=recording_number,
                recording_count=recording_count,
            )
        else:
            reference_status = "selected"
            reference_frame_idx = int(auto_reference_frame)

        if reference_status == "skip":
            print(f"Skipped recording{recording_number} ({run.run_name})")
            return "skip"
        if reference_status == "quit":
            return "quit"
        if reference_frame_idx is None:
            raise RuntimeError("Reference frame selection returned no frame index.")

        if auto_candidate_ids is None:
            annotation = annotate_reference_points(
                run=run,
                frame_idx=reference_frame_idx,
                recording_number=recording_number,
                recording_count=recording_count,
                max_candidates=max_candidates,
            )
        else:
            annotation = create_annotation_from_candidate_ids(
                run=run,
                frame_idx=reference_frame_idx,
                candidate_ids=[int(value) for value in auto_candidate_ids],
                max_candidates=max_candidates,
            )

        if annotation.status == "back":
            if auto_reference_frame is not None:
                raise RuntimeError("Auto reference mode cannot go back to frame selection.")
            continue
        if annotation.status == "skip":
            print(f"Skipped recording{recording_number} ({run.run_name})")
            return "skip"
        if annotation.status == "quit":
            return "quit"
        if annotation.payload is None:
            raise RuntimeError("Reference annotation did not return a payload.")

        detection_payload = solve_and_save_outputs(
            run=run,
            annotation=annotation.payload,
            intrinsics=intrinsics,
            lane_dimensions=lane_dimensions,
            recording_dir=recording_dir,
        )
        render_full_run_outputs(
            run=run,
            detection_payload=detection_payload,
            intrinsics=intrinsics,
            recording_dir=recording_dir,
            video_name=video_name,
            video_fps=video_fps,
        )
        print(f"Finished recording{recording_number} ({run.run_name})")
        return "completed"


def select_reference_frame(
    run,
    recording_number: int,
    recording_count: int,
) -> tuple[str, int | None]:
    import cv2

    frame_idx = 0
    frame_count = len(run.frame_records)
    window_name = "Reference Frame Selection"

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        while True:
            record = run.get_frame_record(frame_idx)
            image = run.load_frame_bgr(frame_idx)
            display = image.copy()
            draw_header_lines(
                display,
                [
                    f"Recording {recording_number}/{recording_count} | choose reference frame",
                    f"run: {run.run_name}",
                    f"frame {frame_idx}/{max(0, frame_count - 1)} | source {record.source_frame_id}",
                    "Keys: a/d prev/next | j/l jump 10 | s select | k skip | q quit",
                ],
            )
            cv2.imshow(window_name, display)
            key = cv2.waitKey(20) & 0xFF

            if key in (ord("q"), 27):
                return "quit", None
            if key == ord("k"):
                return "skip", None
            if key == ord("a"):
                frame_idx = max(0, frame_idx - 1)
            if key == ord("d"):
                frame_idx = min(frame_count - 1, frame_idx + 1)
            if key == ord("j"):
                frame_idx = max(0, frame_idx - 10)
            if key == ord("l"):
                frame_idx = min(frame_count - 1, frame_idx + 10)
            if key == ord("s"):
                return "selected", frame_idx
    finally:
        cv2.destroyWindow(window_name)


def annotate_reference_points(
    run,
    frame_idx: int,
    recording_number: int,
    recording_count: int,
    max_candidates: int,
) -> AnnotationResult:
    import cv2

    frame_record = run.get_frame_record(frame_idx)
    image = run.load_frame_bgr(frame_idx)
    candidates = detect_candidate_points(image, max_candidates=max_candidates)
    selections: list[dict] = []
    display = image.copy()
    window_name = "Two-Click Lane Annotation"

    def redraw() -> None:
        nonlocal display
        display = image.copy()
        selected_candidate_ids = {
            int(selection["candidate_id"])
            for selection in selections
            if selection["candidate_id"] is not None
        }
        draw_candidate_points(display, candidates, selected_candidate_ids=selected_candidate_ids)
        draw_header_lines(
            display,
            [
                f"Recording {recording_number}/{recording_count} | frame {frame_idx}",
                f"Detected candidates: {len(candidates)} | snap radius: {int(SNAP_RADIUS_PX)} px",
                "Click near numbered candidate points for near lane corners",
                "1 near_left | 2 near_right | keys: r reset | u undo | s save | b back | k skip | q quit",
            ],
        )
        if selections:
            draw_click_points(
                display,
                [selection["point_xy"] for selection in selections],
                [
                    (
                        f"{index + 1}:{TWO_CLICK_LABELS[index]}"
                        if selection["candidate_id"] is not None
                        else f"{index + 1}:{TWO_CLICK_LABELS[index]} manual"
                    )
                    for index, selection in enumerate(selections)
                ],
            )
            if len(selections) == 2:
                first_point = tuple(int(round(value)) for value in selections[0]["point_xy"])
                second_point = tuple(int(round(value)) for value in selections[1]["point_xy"])
                cv2.line(display, first_point, second_point, (255, 120, 0), 2, cv2.LINE_AA)

    def on_mouse(event: int, x: int, y: int, flags: int, param) -> None:
        del flags, param
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if len(selections) >= 2:
            return
        snapped_candidate, snap_distance_px = find_nearest_candidate((float(x), float(y)), candidates)
        if snapped_candidate is not None and snap_distance_px <= SNAP_RADIUS_PX:
            point_xy = [float(snapped_candidate.point_xy[0]), float(snapped_candidate.point_xy[1])]
            candidate_id = int(snapped_candidate.candidate_id)
            selection_mode = "candidate_snap"
        else:
            point_xy = [float(x), float(y)]
            candidate_id = None
            selection_mode = "manual_fallback"
        selections.append(
            {
                "point_xy": point_xy,
                "candidate_id": candidate_id,
                "selection_mode": selection_mode,
                "click_xy": [float(x), float(y)],
                "snap_distance_px": None if snapped_candidate is None else float(snap_distance_px),
            }
        )
        redraw()

    redraw()
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, on_mouse)

    try:
        while True:
            cv2.imshow(window_name, display)
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                return AnnotationResult("quit", None)
            if key == ord("k"):
                return AnnotationResult("skip", None)
            if key == ord("b"):
                return AnnotationResult("back", None)
            if key == ord("r"):
                selections.clear()
                redraw()
            if key == ord("u"):
                if selections:
                    selections.pop()
                redraw()
            if key == ord("s"):
                if len(selections) != 2:
                    print("Need exactly two selected points before saving.")
                    continue
                return AnnotationResult(
                    "saved",
                    build_annotation_payload(
                        run=run,
                        frame_record=frame_record,
                        frame_idx=frame_idx,
                        image_shape=image.shape,
                        candidates=candidates,
                        selections=selections,
                    ),
                )
    finally:
        cv2.destroyWindow(window_name)


def create_annotation_from_candidate_ids(
    run,
    frame_idx: int,
    candidate_ids: list[int],
    max_candidates: int,
) -> AnnotationResult:
    if len(candidate_ids) != 2:
        raise ValueError("Expected exactly two candidate IDs in near_left, near_right order")

    image = run.load_frame_bgr(frame_idx)
    frame_record = run.get_frame_record(frame_idx)
    candidates = detect_candidate_points(image, max_candidates=max_candidates)
    candidate_by_id = {int(candidate.candidate_id): candidate for candidate in candidates}
    selections: list[dict] = []

    for candidate_id in candidate_ids:
        candidate = candidate_by_id.get(int(candidate_id))
        if candidate is None:
            available_ids = ", ".join(str(candidate.candidate_id) for candidate in candidates)
            raise ValueError(f"Candidate ID {candidate_id} was not found. Available IDs: {available_ids}")
        selections.append(
            {
                "point_xy": [float(candidate.point_xy[0]), float(candidate.point_xy[1])],
                "candidate_id": int(candidate.candidate_id),
                "selection_mode": "candidate_id_cli",
                "click_xy": [float(candidate.point_xy[0]), float(candidate.point_xy[1])],
                "snap_distance_px": 0.0,
            }
        )

    return AnnotationResult(
        "saved",
        build_annotation_payload(
            run=run,
            frame_record=frame_record,
            frame_idx=frame_idx,
            image_shape=image.shape,
            candidates=candidates,
            selections=selections,
        ),
    )


def build_annotation_payload(
    run,
    frame_record,
    frame_idx: int,
    image_shape: tuple[int, int, int],
    candidates,
    selections: list[dict],
) -> dict:
    height, width = image_shape[:2]
    return {
        "run_name": run.run_name,
        "reference_frame_idx": frame_idx,
        "reference_source_frame_id": frame_record.source_frame_id,
        "reference_timestamp_us": frame_record.timestamp_us,
        "image_width": width,
        "image_height": height,
        "point_order": TWO_CLICK_LABELS,
        "image_points": [selection["point_xy"] for selection in selections],
        "selected_candidate_ids": [selection["candidate_id"] for selection in selections],
        "selection_records": selections,
        "snap_radius_px": SNAP_RADIUS_PX,
        "candidate_points": [candidate.as_dict() for candidate in candidates],
        "frame_file_name": frame_record.file_name,
    }


def solve_and_save_outputs(
    run,
    annotation: dict,
    intrinsics: CameraIntrinsics,
    lane_dimensions: LaneDimensions,
    recording_dir: Path,
) -> dict:
    import cv2

    reference_frame_idx = int(annotation["reference_frame_idx"])
    reference_frame = run.get_frame_record(reference_frame_idx)
    image = run.load_frame_bgr(reference_frame_idx)
    near_points_xy = annotation["image_points"]

    result = solve_lane_from_two_clicks(
        reference_frame=reference_frame,
        intrinsics=intrinsics,
        lane_dimensions=lane_dimensions,
        near_points_xy=near_points_xy,
        image_bgr=image,
    )

    overlay_image = image.copy()
    draw_lane_polygon(
        overlay_image,
        result.image_points_xy,
        labels=POINT_ORDER,
        edge_color_bgr=(0, 255, 0),
        point_color_bgr=(0, 0, 255),
        thickness=2,
    )
    draw_click_points(overlay_image, near_points_xy, TWO_CLICK_LABELS, color_bgr=(0, 255, 255))
    draw_header_lines(
        overlay_image,
        [
            f"2-click lane detection | frame {reference_frame_idx}",
            f"confidence: {result.confidence_label} ({result.confidence:.2f})",
            f"yaw refinement: {result.debug['best_yaw_offset_deg']:.2f} deg",
        ],
    )

    base_overlay_image = image.copy()
    draw_lane_polygon(
        base_overlay_image,
        result.debug["base_image_points_xy"],
        labels=POINT_ORDER,
        edge_color_bgr=(255, 160, 0),
        point_color_bgr=(255, 160, 0),
        thickness=2,
    )
    draw_click_points(base_overlay_image, near_points_xy, TWO_CLICK_LABELS, color_bgr=(0, 255, 255))
    draw_header_lines(
        base_overlay_image,
        [
            f"Base geometry solve | frame {reference_frame_idx}",
            "orange = pose-driven solve before edge refinement",
        ],
    )

    annotation_path = recording_dir / "reference_annotation.json"
    annotation_path.write_text(json.dumps(annotation, indent=2), encoding="utf-8")

    payload = {
        "run_name": run.run_name,
        "reference_frame_idx": reference_frame_idx,
        "reference_source_frame_id": reference_frame.source_frame_id,
        "reference_timestamp_us": reference_frame.timestamp_us,
        "frame_file_name": reference_frame.file_name,
        "annotation_path": str(annotation_path),
        "intrinsics_path": str(recording_dir / "intrinsics_used.json"),
        "lane_config_path": str(recording_dir / "lane_dimensions_used.json"),
        "point_order": POINT_ORDER,
        "lane_points_world": result.lane_points_world.tolist(),
        "image_points_xy": result.image_points_xy,
        "confidence": result.confidence,
        "confidence_label": result.confidence_label,
        "debug": result.debug,
    }

    intrinsics_used = {
        "image_width": intrinsics.image_width,
        "image_height": intrinsics.image_height,
        "fx": intrinsics.fx,
        "fy": intrinsics.fy,
        "cx": intrinsics.cx,
        "cy": intrinsics.cy,
        "source": intrinsics.source,
    }
    lane_dimensions_used = {
        "lane_width_m": lane_dimensions.lane_width_m,
        "lane_length_m": lane_dimensions.lane_length_m,
    }

    (recording_dir / "two_click_lane_detection.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (recording_dir / "intrinsics_used.json").write_text(json.dumps(intrinsics_used, indent=2), encoding="utf-8")
    (recording_dir / "lane_dimensions_used.json").write_text(json.dumps(lane_dimensions_used, indent=2), encoding="utf-8")
    cv2.imwrite(str(recording_dir / "reference_detection_overlay.jpg"), overlay_image)
    cv2.imwrite(str(recording_dir / "reference_detection_base_geometry.jpg"), base_overlay_image)
    return payload


def render_full_run_outputs(
    run,
    detection_payload: dict,
    intrinsics: CameraIntrinsics,
    recording_dir: Path,
    video_name: str,
    video_fps: float,
) -> None:
    import cv2

    lane_points_world = np.asarray(detection_payload["lane_points_world"], dtype=np.float64)
    reference_frame_idx = int(detection_payload["reference_frame_idx"])
    reference_frame = run.get_frame_record(reference_frame_idx)

    output_dir = recording_dir / "continuous_reprojection"
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = output_dir / "continuous_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    projections = []
    for record in run.frame_records:
        projected = project_world_points(record, intrinsics, lane_points_world)
        relative_seconds = (record.timestamp_us - reference_frame.timestamp_us) / 1_000_000.0
        projections.append(
            {
                "local_frame_idx": record.local_frame_idx,
                "source_frame_id": record.source_frame_id,
                "timestamp_us": record.timestamp_us,
                "relative_seconds": relative_seconds,
                "image_points_xy": projected["image_points_xy"],
                "visibility": projected["visibility"],
                "depths": projected["depths"],
            }
        )

    frame_width, frame_height = run.infer_image_size()
    video_writer, video_path, video_codec = create_video_writer(
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
                labels=POINT_ORDER,
                edge_color_bgr=(255, 120, 0),
                point_color_bgr=(0, 0, 255),
                thickness=2,
            )
            draw_header_lines(
                image,
                [
                    f"2-click lane reprojection | frame {frame_idx}",
                    f"{projection['relative_seconds']:+.2f}s vs ref",
                ],
            )
            cv2.imwrite(str(frames_dir / f"{frame_idx:04d}.jpg"), image)
            repeat_count = video_repeat_count_for_projection(
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
        "reference_frame_idx": reference_frame_idx,
        "continuous_projection_count": len(projections),
        "forward_only": False,
        "write_video": True,
        "save_all_frame_overlays": True,
        "video_fps_requested": video_fps,
        "video_path": str(video_path),
        "video_codec": video_codec,
        "video_timing": build_video_timing_summary(projections, video_fps),
    }

    (output_dir / "projected_lane_corners_all_frames.json").write_text(
        json.dumps(projections, indent=2),
        encoding="utf-8",
    )
    (output_dir / "projection_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_video_timing_summary(projections: list[dict], output_video_fps: float) -> dict:
    if not projections:
        return {
            "mode": "timestamp_paced_repeats",
            "output_video_fps": output_video_fps,
            "source_frame_count": 0,
            "written_video_frame_count": 0,
            "source_duration_seconds": 0.0,
            "expected_video_duration_seconds": 0.0,
        }

    repeat_counts = [
        video_repeat_count_for_projection(projections=projections, index=index, output_video_fps=output_video_fps)
        for index in range(len(projections))
    ]
    source_duration_seconds = (
        float(projections[-1]["timestamp_us"] - projections[0]["timestamp_us"]) / 1_000_000.0
        if len(projections) >= 2
        else 0.0
    )
    written_video_frame_count = int(sum(repeat_counts))
    expected_video_duration_seconds = written_video_frame_count / output_video_fps
    return {
        "mode": "timestamp_paced_repeats",
        "output_video_fps": output_video_fps,
        "source_frame_count": len(projections),
        "written_video_frame_count": written_video_frame_count,
        "source_duration_seconds": source_duration_seconds,
        "expected_video_duration_seconds": expected_video_duration_seconds,
        "min_repeat_count": int(min(repeat_counts)),
        "max_repeat_count": int(max(repeat_counts)),
    }


def video_repeat_count_for_projection(projections: list[dict], index: int, output_video_fps: float) -> int:
    if len(projections) <= 1:
        return 1

    frame_interval_seconds = 1.0 / output_video_fps
    if index < len(projections) - 1:
        delta_us = int(projections[index + 1]["timestamp_us"]) - int(projections[index]["timestamp_us"])
    else:
        delta_us = int(projections[index]["timestamp_us"]) - int(projections[index - 1]["timestamp_us"])
    delta_seconds = max(0.0, delta_us / 1_000_000.0)
    return max(1, int(round(delta_seconds / frame_interval_seconds)))


def create_video_writer(preferred_video_path: Path, fps: float, frame_size: tuple[int, int]):
    import cv2

    candidates = [
        (preferred_video_path, "mp4v"),
        (preferred_video_path.with_suffix(".avi"), "MJPG"),
    ]
    for video_path, codec_name in candidates:
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*codec_name), fps, frame_size)
        if writer.isOpened():
            return writer, video_path, codec_name
        writer.release()
    raise RuntimeError(f"Failed to open a video writer for {preferred_video_path}")


if __name__ == "__main__":
    main()
