from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


@dataclass
class SeedConfig:
    init_consecutive_frames: int = 5
    max_lost_frames: int = 2
    position_tolerance_px: float = 35.0
    radius_tolerance_px: float = 10.0
    roi_scale_factor: float = 0.6
    min_roi_margin_px: int = 10
    global_dp: float = 1.2
    global_min_dist_px: float = 40.0
    global_param1: float = 100.0
    global_param2: float = 32.0
    roi_dp: float = 1.2
    roi_min_dist_px: float = 500.0
    roi_param1: float = 180.0
    roi_param2: float = 8.0
    lane_polygon_normalized: tuple[tuple[float, float], ...] = (
        (0.08, 1.0),
        (0.92, 1.0),
        (0.64, 0.28),
        (0.36, 0.28),
    )


@dataclass
class CircleDetection:
    frame_index: int
    x: int
    y: int
    radius: int
    mode: str
    stable: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed a bowling-ball track from a clip using classical CV."
    )
    parser.add_argument("--input", required=True, help="Path to input video clip.")
    parser.add_argument(
        "--detections",
        required=True,
        help="Path to write per-frame detections CSV.",
    )
    parser.add_argument(
        "--seed",
        required=True,
        help="Path to write seed JSON for downstream promptable tracking.",
    )
    parser.add_argument(
        "--overlay",
        default="",
        help="Optional path to write an overlay video.",
    )
    return parser.parse_args()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def preprocess_bgr(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.medianBlur(gray, 5)


def normalized_polygon_to_pixels(
    polygon: Iterable[tuple[float, float]], width: int, height: int
) -> np.ndarray:
    return np.array(
        [[int(x * width), int(y * height)] for x, y in polygon], dtype=np.int32
    )


def make_lane_mask(frame: np.ndarray, config: SeedConfig) -> np.ndarray:
    height, width = frame.shape[:2]
    polygon = normalized_polygon_to_pixels(
        config.lane_polygon_normalized, width, height
    )
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def detect_circles(
    gray: np.ndarray,
    min_radius: int,
    max_radius: int,
    dp: float,
    min_dist: float,
    param1: float,
    param2: float,
) -> np.ndarray:
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=dp,
        minDist=min_dist,
        param1=param1,
        param2=param2,
        minRadius=max(0, min_radius),
        maxRadius=max_radius,
    )
    if circles is None:
        return np.empty((0, 3), dtype=np.float32)
    return np.round(circles[0]).astype(np.float32)


def score_circle(circle: np.ndarray, frame_shape: tuple[int, int, int]) -> float:
    x, y, r = circle
    height, width = frame_shape[:2]
    center_bias = abs(x - (width / 2.0)) / max(width / 2.0, 1.0)
    lower_bias = 1.0 - (y / max(height, 1.0))
    radius_term = r / max(min(height, width), 1.0)
    return (radius_term * 4.0) - (center_bias * 0.75) - (lower_bias * 0.4)


def choose_best_global_circle(
    circles: np.ndarray, frame_shape: tuple[int, int, int]
) -> np.ndarray | None:
    if len(circles) == 0:
        return None
    best = max(circles, key=lambda c: score_circle(c, frame_shape))
    return best


def choose_best_roi_circle(
    circles: np.ndarray, last_detection: CircleDetection
) -> np.ndarray | None:
    if len(circles) == 0:
        return None

    last_center = np.array([last_detection.x, last_detection.y], dtype=np.float32)

    def roi_score(circle: np.ndarray) -> float:
        x, y, r = circle
        distance = np.linalg.norm(np.array([x, y], dtype=np.float32) - last_center)
        radius_delta = abs(r - last_detection.radius)
        return distance + (radius_delta * 2.0)

    return min(circles, key=roi_score)


def is_consistent(
    candidate: np.ndarray, previous: CircleDetection | None, config: SeedConfig
) -> bool:
    if previous is None:
        return True

    position_delta = np.linalg.norm(
        np.array([candidate[0] - previous.x, candidate[1] - previous.y], dtype=float)
    )
    radius_delta = abs(candidate[2] - previous.radius)
    return (
        position_delta <= config.position_tolerance_px
        and radius_delta <= config.radius_tolerance_px
    )


def make_roi(
    detection: CircleDetection, frame_shape: tuple[int, int, int], config: SeedConfig
) -> tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    dynamic_margin = max(
        int(detection.radius * config.roi_scale_factor), config.min_roi_margin_px
    )
    x_min = max(0, detection.x - detection.radius - dynamic_margin)
    y_min = max(0, detection.y - detection.radius - dynamic_margin)
    x_max = min(width, detection.x + detection.radius + dynamic_margin)
    y_max = min(height, detection.y + detection.radius + dynamic_margin)
    return x_min, y_min, x_max, y_max


def draw_detection(
    frame: np.ndarray,
    detection: CircleDetection | None,
    roi: tuple[int, int, int, int] | None,
    mode: str,
) -> np.ndarray:
    output = frame.copy()
    if roi is not None:
        x_min, y_min, x_max, y_max = roi
        cv2.rectangle(output, (x_min, y_min), (x_max, y_max), (255, 255, 0), 2)
    if detection is not None:
        cv2.circle(output, (detection.x, detection.y), detection.radius, (0, 255, 0), 2)
        cv2.circle(output, (detection.x, detection.y), 3, (0, 0, 255), -1)
        cv2.putText(
            output,
            f"{mode} r={detection.radius}",
            (detection.x + 8, max(20, detection.y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return output


def write_detections_csv(path: Path, detections: list[CircleDetection]) -> None:
    ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["frame_index", "x", "y", "radius", "mode", "stable"],
        )
        writer.writeheader()
        for detection in detections:
            writer.writerow(asdict(detection))


def write_seed_json(path: Path, seed_detection: CircleDetection | None) -> None:
    ensure_parent(path)
    if seed_detection is None:
        payload = {
            "status": "no_seed",
            "message": "No stable bowling-ball seed was found in the clip.",
        }
    else:
        payload = {
            "status": "ok",
            "seed_frame_index": seed_detection.frame_index,
            "seed_point": [seed_detection.x, seed_detection.y],
            "seed_radius": seed_detection.radius,
            "seed_box": [
                seed_detection.x - seed_detection.radius,
                seed_detection.y - seed_detection.radius,
                seed_detection.x + seed_detection.radius,
                seed_detection.y + seed_detection.radius,
            ],
        }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def process_clip(
    video_path: Path,
    detections_path: Path,
    seed_path: Path,
    overlay_path: Path | None,
    config: SeedConfig,
) -> dict[str, object]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = None
    if overlay_path is not None:
        ensure_parent(overlay_path)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(overlay_path), fourcc, fps, (width, height))

    detections: list[CircleDetection] = []
    stable_seed: CircleDetection | None = None
    warmup_detection: CircleDetection | None = None
    warmup_count = 0
    last_detection: CircleDetection | None = None
    lost_count = 0

    lane_mask = None
    frame_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if lane_mask is None:
            lane_mask = make_lane_mask(frame, config)

        mode = "global"
        roi = None
        candidate_circle = None

        if last_detection is None or lost_count > config.max_lost_frames:
            masked = cv2.bitwise_and(frame, frame, mask=lane_mask)
            gray = preprocess_bgr(masked)
            min_radius = max(8, int(min(width, height) * 0.01))
            max_radius = max(min_radius + 2, int(min(width, height) * 0.08))
            circles = detect_circles(
                gray,
                min_radius=min_radius,
                max_radius=max_radius,
                dp=config.global_dp,
                min_dist=config.global_min_dist_px,
                param1=config.global_param1,
                param2=config.global_param2,
            )
            candidate_circle = choose_best_global_circle(circles, frame.shape)
        else:
            roi = make_roi(last_detection, frame.shape, config)
            x_min, y_min, x_max, y_max = roi
            roi_frame = frame[y_min:y_max, x_min:x_max]
            gray = preprocess_bgr(roi_frame)
            circles = detect_circles(
                gray,
                min_radius=max(0, int(last_detection.radius * 0.85)),
                max_radius=int(last_detection.radius * 1.15),
                dp=config.roi_dp,
                min_dist=config.roi_min_dist_px,
                param1=config.roi_param1,
                param2=config.roi_param2,
            )
            if len(circles) > 0:
                circles[:, 0] += x_min
                circles[:, 1] += y_min
            candidate_circle = choose_best_roi_circle(circles, last_detection)
            mode = "roi"

        detection = None
        if candidate_circle is not None:
            detection = CircleDetection(
                frame_index=frame_index,
                x=int(candidate_circle[0]),
                y=int(candidate_circle[1]),
                radius=int(candidate_circle[2]),
                mode=mode,
                stable=False,
            )

            if stable_seed is None:
                if is_consistent(candidate_circle, warmup_detection, config):
                    warmup_detection = detection
                    warmup_count += 1
                else:
                    warmup_detection = detection
                    warmup_count = 1

                if warmup_count >= config.init_consecutive_frames and stable_seed is None:
                    detection.stable = True
                    stable_seed = detection
                    last_detection = detection
                    lost_count = 0
                elif warmup_count > 0:
                    lost_count = 0
            else:
                detection.stable = True
                last_detection = detection
                lost_count = 0
        else:
            lost_count += 1

        if detection is not None:
            detections.append(detection)

        if writer is not None:
            writer.write(draw_detection(frame, detection, roi, mode))

        frame_index += 1

    cap.release()
    if writer is not None:
        writer.release()

    write_detections_csv(detections_path, detections)
    write_seed_json(seed_path, stable_seed)

    return {
        "video_path": str(video_path),
        "detections_path": str(detections_path),
        "seed_path": str(seed_path),
        "overlay_path": str(overlay_path) if overlay_path is not None else "",
        "seed_found": stable_seed is not None,
        "seed_frame_index": stable_seed.frame_index if stable_seed else -1,
        "num_detections": len(detections),
        "num_frames": frame_index,
    }


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    detections_path = Path(args.detections)
    seed_path = Path(args.seed)
    overlay_path = Path(args.overlay) if args.overlay else None

    summary = process_clip(
        video_path=input_path,
        detections_path=detections_path,
        seed_path=seed_path,
        overlay_path=overlay_path,
        config=SeedConfig(),
    )

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
