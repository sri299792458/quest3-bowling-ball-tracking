import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

try:
    from .path_config import DEFAULT_CHECKPOINTS_ROOT, LAPTOP_PIPELINE_ROOT, PROJECT_ROOT
except ImportError:
    from path_config import DEFAULT_CHECKPOINTS_ROOT, LAPTOP_PIPELINE_ROOT, PROJECT_ROOT

ROOT = PROJECT_ROOT
DEFAULT_VIDEO = ""
DEFAULT_OUTPUT_ROOT = LAPTOP_PIPELINE_ROOT / "runs"
DEFAULT_SAM_SCRIPT = LAPTOP_PIPELINE_ROOT / "warm_sam2_tracker.py"
DEFAULT_SAM_CHECKPOINT = DEFAULT_CHECKPOINTS_ROOT / "sam2.1_hiera_tiny.pt"
DEFAULT_SAM_CFG = "configs/sam2.1/sam2.1_hiera_t.yaml"


@dataclass
class Candidate:
    frame_idx: int
    x1: float
    y1: float
    x2: float
    y2: float
    cx: float
    cy: float
    width: float
    height: float
    lane_overlap: float
    lane_width_ratio: float
    motion_ratio: float
    darkness: float
    contrast: float
    circularity: float
    fill_ratio: float
    score: float


@dataclass
class PathTrack:
    candidates: list[Candidate]
    total_score: float

    @property
    def first(self):
        return self.candidates[0]

    @property
    def last(self):
        return self.candidates[-1]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Classical bowling-ball initializer based on darkening motion and compact-object tracking."
    )
    parser.add_argument("--video", default=DEFAULT_VIDEO)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--scan-start", type=int, default=0)
    parser.add_argument("--scan-end", type=int, default=-1)
    parser.add_argument("--scan-step", type=int, default=2)
    parser.add_argument("--motion-threshold", type=float, default=18.0)
    parser.add_argument("--min-area", type=float, default=80.0)
    parser.add_argument("--min-motion-ratio", type=float, default=0.15)
    parser.add_argument("--min-darkness", type=float, default=0.32)
    parser.add_argument("--min-contrast", type=float, default=0.04)
    parser.add_argument("--min-circularity", type=float, default=0.35)
    parser.add_argument("--min-fill-ratio", type=float, default=0.25)
    parser.add_argument("--min-lane-overlap", type=float, default=0.85)
    parser.add_argument("--lane-width-ratio-min", type=float, default=0.045)
    parser.add_argument("--lane-width-ratio-max", type=float, default=0.18)
    parser.add_argument("--max-candidates-per-frame", type=int, default=6)
    parser.add_argument("--max-track-gap", type=int, default=6)
    parser.add_argument("--max-center-distance", type=float, default=180.0)
    parser.add_argument("--size-ratio-threshold", type=float, default=0.45)
    parser.add_argument("--max-y-increase", type=float, default=20.0)
    parser.add_argument("--min-track-length", type=int, default=4)
    parser.add_argument("--min-track-travel", type=float, default=180.0)
    parser.add_argument("--min-start-center-y-ratio", type=float, default=0.55)
    parser.add_argument("--min-mean-score", type=float, default=0.62)
    parser.add_argument("--sam-script", default=str(DEFAULT_SAM_SCRIPT))
    parser.add_argument("--sam-checkpoint", default=str(DEFAULT_SAM_CHECKPOINT))
    parser.add_argument("--sam-model-cfg", default=DEFAULT_SAM_CFG)
    parser.add_argument("--sam-vos-optimized", action="store_true", default=True)
    parser.add_argument("--sam-no-preview", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--frame-limit", type=int, default=0)
    return parser.parse_args()


def sanitize_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    return safe.strip("_") or "run"


def get_video_metadata(video_path: str):
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    return frame_count, width, height


def read_frame(video_path: str, frame_idx: int):
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame_bgr = capture.read()
    finally:
        capture.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {frame_idx} from {video_path}")
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


def iter_sampled_frames(video_path: str, start_frame: int, end_frame: int, step: int):
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        if start_frame > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_idx = start_frame
        while frame_idx <= end_frame:
            ok, frame_bgr = capture.read()
            if not ok:
                break
            yield frame_idx, cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            skipped = 0
            while skipped < step - 1 and frame_idx + skipped + 1 <= end_frame:
                if not capture.grab():
                    return
                skipped += 1
            frame_idx += step
    finally:
        capture.release()


def build_output_dir(video_path: str, sam_cfg: str):
    stem = Path(video_path).stem
    sam_name = Path(sam_cfg).stem.replace("sam2.1_", "")
    return DEFAULT_OUTPUT_ROOT / f"dark_compact_auto_{sanitize_name(stem)}_{sanitize_name(sam_name)}"


def build_default_bowling_corridor(frame_width: int, frame_height: int):
    return np.array(
        [
            [int(frame_width * 0.18), frame_height - 1],
            [int(frame_width * 0.82), frame_height - 1],
            [int(frame_width * 0.63), int(frame_height * 0.24)],
            [int(frame_width * 0.37), int(frame_height * 0.24)],
        ],
        dtype=np.int32,
    )


def build_lane_mask(points: np.ndarray, frame_width: int, frame_height: int):
    mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    cv2.fillPoly(mask, [points], 255)
    return mask


def lane_width_at_y(y: float, lane_mask: np.ndarray):
    row = int(min(max(round(y), 0), lane_mask.shape[0] - 1))
    xs = np.where(lane_mask[row] > 0)[0]
    if len(xs) < 2:
        return 1.0
    return float(xs[-1] - xs[0] + 1)


def circle_means(gray_frame: np.ndarray, cx: float, cy: float, radius: float, lane_mask: np.ndarray):
    yy, xx = np.ogrid[: gray_frame.shape[0], : gray_frame.shape[1]]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inner = dist2 <= radius * radius
    ring = (dist2 >= (radius * 1.20) ** 2) & (dist2 <= (radius * 1.75) ** 2)
    inner &= lane_mask > 0
    ring &= lane_mask > 0
    if not np.any(inner) or not np.any(ring):
        return None, None
    return float(np.mean(gray_frame[inner])), float(np.mean(gray_frame[ring]))


def compute_darkening_mask(frame_rgb: np.ndarray, prev_frame_rgb: np.ndarray, motion_threshold: float, lane_mask: np.ndarray):
    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
    prev_gray = cv2.cvtColor(prev_frame_rgb, cv2.COLOR_RGB2GRAY)
    darkening = cv2.subtract(prev_gray, gray)
    darkening = cv2.GaussianBlur(darkening, (5, 5), 0)
    _, motion_mask = cv2.threshold(darkening, motion_threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((5, 5), np.uint8)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_OPEN, kernel)
    motion_mask = cv2.morphologyEx(motion_mask, cv2.MORPH_CLOSE, kernel)
    motion_mask = cv2.bitwise_and(motion_mask, lane_mask)
    return motion_mask, gray


def candidate_score(motion_ratio: float, darkness: float, contrast: float, circularity: float, fill_ratio: float, lane_width_ratio: float, width: float, height: float):
    aspect = width / max(height, 1.0)
    aspect_score = max(0.4, 1.0 - min(abs(math.log(max(aspect, 1e-6))), 1.6) / 1.6)
    size_center = 0.09
    size_score = math.exp(-abs(math.log(max(lane_width_ratio, 1e-6) / size_center)))
    base = (
        0.28 * min(motion_ratio * 1.4, 1.0)
        + 0.22 * darkness
        + 0.22 * contrast
        + 0.16 * circularity
        + 0.12 * min(fill_ratio, 1.0)
    )
    return base * (0.65 + 0.35 * size_score) * (0.70 + 0.30 * aspect_score)


def extract_candidates(frame_idx: int, motion_mask: np.ndarray, gray_frame: np.ndarray, lane_mask: np.ndarray, args):
    contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_height, frame_width = motion_mask.shape[:2]
    candidates: list[Candidate] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < args.min_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 1e-6:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 10 or h < 10:
            continue
        if x <= 2 or y <= 2 or x + w >= frame_width - 2 or y + h >= frame_height - 2:
            continue

        cx = x + w / 2.0
        cy = y + h / 2.0
        lane_width_ratio = w / max(1.0, lane_width_at_y(cy, lane_mask))
        if not (args.lane_width_ratio_min <= lane_width_ratio <= args.lane_width_ratio_max):
            continue

        box_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
        box_mask[y : y + h, x : x + w] = 255
        box_area = float(max(1, w * h))
        lane_overlap = cv2.countNonZero(cv2.bitwise_and(box_mask, lane_mask)) / box_area
        if lane_overlap < args.min_lane_overlap:
            continue

        motion_ratio = cv2.countNonZero(cv2.bitwise_and(box_mask, motion_mask)) / box_area
        if motion_ratio < args.min_motion_ratio:
            continue

        circularity = min(1.0, float(4.0 * math.pi * area / (perimeter * perimeter)))
        if circularity < args.min_circularity:
            continue

        (_, _), radius = cv2.minEnclosingCircle(contour)
        circle_area = math.pi * max(radius, 1.0) * max(radius, 1.0)
        fill_ratio = min(1.5, area / max(circle_area, 1e-6))
        if fill_ratio < args.min_fill_ratio:
            continue

        inner_mean, ring_mean = circle_means(gray_frame, cx, cy, max(radius, 6.0), lane_mask)
        if inner_mean is None or ring_mean is None:
            continue
        darkness = 1.0 - inner_mean / 255.0
        contrast = max(0.0, (ring_mean - inner_mean) / 255.0)
        if darkness < args.min_darkness or contrast < args.min_contrast:
            continue

        score = candidate_score(
            motion_ratio=motion_ratio,
            darkness=darkness,
            contrast=contrast,
            circularity=circularity,
            fill_ratio=fill_ratio,
            lane_width_ratio=lane_width_ratio,
            width=float(w),
            height=float(h),
        )
        candidates.append(
            Candidate(
                frame_idx=frame_idx,
                x1=float(x),
                y1=float(y),
                x2=float(x + w),
                y2=float(y + h),
                cx=float(cx),
                cy=float(cy),
                width=float(w),
                height=float(h),
                lane_overlap=float(lane_overlap),
                lane_width_ratio=float(lane_width_ratio),
                motion_ratio=float(motion_ratio),
                darkness=float(darkness),
                contrast=float(contrast),
                circularity=float(circularity),
                fill_ratio=float(fill_ratio),
                score=float(score),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[: args.max_candidates_per_frame]


def can_link(prev: Candidate, cur: Candidate, max_track_gap: int, max_center_distance: float, size_ratio_threshold: float, max_y_increase: float):
    if cur.frame_idx <= prev.frame_idx:
        return False
    if cur.frame_idx - prev.frame_idx > max_track_gap:
        return False
    if cur.cy - prev.cy > max_y_increase:
        return False
    if math.hypot(prev.cx - cur.cx, prev.cy - cur.cy) > max_center_distance:
        return False
    width_ratio = min(prev.width, cur.width) / max(prev.width, cur.width)
    height_ratio = min(prev.height, cur.height) / max(prev.height, cur.height)
    if width_ratio < size_ratio_threshold or height_ratio < size_ratio_threshold:
        return False
    return True


def edge_score(prev: Candidate, cur: Candidate):
    frame_gap = cur.frame_idx - prev.frame_idx
    center_dist = math.hypot(prev.cx - cur.cx, prev.cy - cur.cy)
    width_ratio = min(prev.width, cur.width) / max(prev.width, cur.width)
    height_ratio = min(prev.height, cur.height) / max(prev.height, cur.height)
    y_progress = max(0.0, prev.cy - cur.cy)
    return (
        0.70 * min(y_progress / 80.0, 2.0)
        + 0.35 * (width_ratio + height_ratio)
        - 0.25 * (center_dist / 80.0)
        - 0.05 * max(frame_gap - 2, 0)
    )


def monotonic_fraction(track: PathTrack):
    if len(track.candidates) < 2:
        return 0.0
    good = 0
    total = 0
    for a, b in zip(track.candidates, track.candidates[1:]):
        total += 1
        if b.cy <= a.cy + 5:
            good += 1
    return good / max(total, 1)


def total_y_travel(track: PathTrack):
    return track.first.cy - track.last.cy


def mean_node_score(track: PathTrack):
    return sum(c.score for c in track.candidates) / max(len(track.candidates), 1)


def build_valid_tracks(candidates: list[Candidate], frame_height: int, args):
    if not candidates:
        return []

    ordered = sorted(candidates, key=lambda c: (c.frame_idx, -c.score))
    successors: list[list[int]] = [[] for _ in ordered]
    for i, prev in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            cur = ordered[j]
            if can_link(prev, cur, args.max_track_gap, args.max_center_distance, args.size_ratio_threshold, args.max_y_increase):
                successors[i].append(j)

    @lru_cache(maxsize=None)
    def best_suffix(start_idx: int):
        best_total = ordered[start_idx].score
        best_path = [start_idx]
        for next_idx in successors[start_idx]:
            child_total, child_path = best_suffix(next_idx)
            total = ordered[start_idx].score + edge_score(ordered[start_idx], ordered[next_idx]) + child_total
            if total > best_total:
                best_total = total
                best_path = [start_idx, *child_path]
        return best_total, best_path

    valid_tracks: list[PathTrack] = []
    for i, candidate in enumerate(ordered):
        total, index_path = best_suffix(i)
        track = PathTrack(candidates=[ordered[idx] for idx in index_path], total_score=float(total))
        if len(track.candidates) < args.min_track_length:
            continue
        if track.first.cy < frame_height * args.min_start_center_y_ratio:
            continue
        if total_y_travel(track) < args.min_track_travel:
            continue
        if mean_node_score(track) < args.min_mean_score:
            continue
        if monotonic_fraction(track) < 0.80:
            continue
        valid_tracks.append(track)

    return valid_tracks


def choose_track(candidates: list[Candidate], frame_height: int, args):
    valid_tracks = build_valid_tracks(candidates, frame_height, args)
    if not valid_tracks:
        return None

    valid_tracks.sort(key=lambda t: (t.first.frame_idx, -t.total_score, -mean_node_score(t)))
    return valid_tracks[0]


def refine_seed_candidate(frame_rgb: np.ndarray, coarse_candidate: Candidate, lane_mask: np.ndarray):
    frame_height, frame_width = frame_rgb.shape[:2]
    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

    margin_x = int(max(20.0, coarse_candidate.width * 0.35))
    margin_y = int(max(20.0, coarse_candidate.height * 0.35))
    roi_x1 = max(0, int(coarse_candidate.x1 - margin_x))
    roi_y1 = max(0, int(coarse_candidate.y1 - margin_y))
    roi_x2 = min(frame_width, int(coarse_candidate.x2 + margin_x))
    roi_y2 = min(frame_height, int(coarse_candidate.y2 + margin_y))

    roi_gray = gray[roi_y1:roi_y2, roi_x1:roi_x2]
    roi_lane = lane_mask[roi_y1:roi_y2, roi_x1:roi_x2]
    lane_pixels = roi_gray[roi_lane > 0]
    if lane_pixels.size == 0:
        return coarse_candidate, False

    threshold = int(np.percentile(lane_pixels, 18))
    dark_mask = np.zeros_like(roi_gray, dtype=np.uint8)
    dark_mask[(roi_gray <= threshold) & (roi_lane > 0)] = 255
    kernel = np.ones((5, 5), np.uint8)
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_OPEN, kernel)
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1e9
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 80:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 1e-6:
            continue
        circularity = min(1.0, 4.0 * math.pi * area / (perimeter * perimeter))
        if circularity < 0.30:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        radius = max(radius, 8.0)
        global_cx = roi_x1 + cx
        global_cy = roi_y1 + cy
        inner_mean, ring_mean = circle_means(gray, global_cx, global_cy, radius, lane_mask)
        if inner_mean is None or ring_mean is None:
            continue
        darkness = 1.0 - inner_mean / 255.0
        contrast = max(0.0, (ring_mean - inner_mean) / 255.0)
        dist_penalty = math.hypot(global_cx - coarse_candidate.cx, global_cy - coarse_candidate.cy) / max(
            coarse_candidate.width, coarse_candidate.height, 1.0
        )
        score = 1.20 * darkness + 1.10 * contrast + 0.40 * circularity - 0.25 * dist_penalty
        if score > best_score:
            best_score = score
            best = (global_cx, global_cy, radius, darkness, contrast)

    if best is None:
        return coarse_candidate, False

    global_cx, global_cy, radius, darkness, contrast = best
    pad = radius * 1.35
    x1 = max(0.0, global_cx - pad)
    y1 = max(0.0, global_cy - pad)
    x2 = min(float(frame_width - 1), global_cx + pad)
    y2 = min(float(frame_height - 1), global_cy + pad)
    refined = Candidate(
        frame_idx=coarse_candidate.frame_idx,
        x1=float(x1),
        y1=float(y1),
        x2=float(x2),
        y2=float(y2),
        cx=float(global_cx),
        cy=float(global_cy),
        width=float(x2 - x1),
        height=float(y2 - y1),
        lane_overlap=coarse_candidate.lane_overlap,
        lane_width_ratio=(x2 - x1) / max(1.0, lane_width_at_y(global_cy, lane_mask)),
        motion_ratio=coarse_candidate.motion_ratio,
        darkness=float(darkness),
        contrast=float(contrast),
        circularity=1.0,
        fill_ratio=1.0,
        score=float(max(coarse_candidate.score, best_score)),
    )
    return refined, True


def annotate_frame(frame_rgb, candidate: Candidate):
    image = Image.fromarray(frame_rgb)
    draw = ImageDraw.Draw(image)
    draw.rectangle((candidate.x1, candidate.y1, candidate.x2, candidate.y2), outline=(0, 255, 255), width=4)
    label = (
        f"dark_motion | score={candidate.score:.3f} | dark={candidate.darkness:.2f} "
        f"| contrast={candidate.contrast:.2f}"
    )
    draw.rectangle(
        (
            candidate.x1,
            max(0, candidate.y1 - 28),
            min(image.width - 1, candidate.x1 + 620),
            candidate.y1,
        ),
        fill=(0, 0, 0),
    )
    draw.text((candidate.x1 + 6, max(0, candidate.y1 - 24)), label, fill=(255, 255, 255))
    return image


def main():
    args = parse_args()
    if not args.video:
        raise SystemExit("No input video was provided. Pass --video <path>.")
    video_path = str(Path(args.video).resolve())
    frame_count, frame_width, frame_height = get_video_metadata(video_path)
    lane_points = build_default_bowling_corridor(frame_width, frame_height)
    lane_mask = build_lane_mask(lane_points, frame_width, frame_height)

    scan_start = max(0, args.scan_start)
    scan_end = frame_count - 1 if args.scan_end < 0 else min(frame_count - 1, args.scan_end)
    if scan_end < scan_start:
        raise ValueError("scan_end must be >= scan_start after clipping to the video range.")

    output_dir = Path(args.output_dir) if args.output_dir else build_output_dir(video_path, args.sam_model_cfg)
    output_dir.mkdir(parents=True, exist_ok=True)
    sam_output_dir = output_dir / "sam2"
    sam_output_dir.mkdir(parents=True, exist_ok=True)

    print("Scanning frames for a dark compact motion track...")
    candidates: list[Candidate] = []
    sampled_frames = 0
    prev_frame_rgb = None
    for frame_idx, frame_rgb in iter_sampled_frames(video_path, scan_start, scan_end, args.scan_step):
        sampled_frames += 1
        if prev_frame_rgb is None:
            prev_frame_rgb = frame_rgb
            continue
        motion_mask, gray = compute_darkening_mask(frame_rgb, prev_frame_rgb, args.motion_threshold, lane_mask)
        candidates.extend(extract_candidates(frame_idx, motion_mask, gray, lane_mask, args))
        prev_frame_rgb = frame_rgb

    if not candidates:
        raise RuntimeError("No plausible dark compact motion candidates were found.")

    best_track = choose_track(candidates, frame_height, args)
    if best_track is None:
        raise RuntimeError("No valid dark compact motion track was found.")

    coarse_seed_candidate = best_track.first
    best_frame = read_frame(video_path, coarse_seed_candidate.frame_idx)
    seed_candidate, refined = refine_seed_candidate(best_frame, coarse_seed_candidate, lane_mask)

    detections_csv = output_dir / "detections.csv"
    with detections_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "frame_idx",
                "x1",
                "y1",
                "x2",
                "y2",
                "cx",
                "cy",
                "width",
                "height",
                "lane_overlap",
                "lane_width_ratio",
                "motion_ratio",
                "darkness",
                "contrast",
                "circularity",
                "fill_ratio",
                "score",
            ]
        )
        for c in sorted(candidates, key=lambda row: (row.frame_idx, -row.score)):
            writer.writerow(
                [
                    c.frame_idx,
                    f"{c.x1:.2f}",
                    f"{c.y1:.2f}",
                    f"{c.x2:.2f}",
                    f"{c.y2:.2f}",
                    f"{c.cx:.2f}",
                    f"{c.cy:.2f}",
                    f"{c.width:.2f}",
                    f"{c.height:.2f}",
                    f"{c.lane_overlap:.6f}",
                    f"{c.lane_width_ratio:.6f}",
                    f"{c.motion_ratio:.6f}",
                    f"{c.darkness:.6f}",
                    f"{c.contrast:.6f}",
                    f"{c.circularity:.6f}",
                    f"{c.fill_ratio:.6f}",
                    f"{c.score:.6f}",
                ]
            )

    best_detection_path = output_dir / "best_detection.jpg"
    annotate_frame(best_frame, seed_candidate).save(best_detection_path)

    track_path = output_dir / "track.json"
    track_path.write_text(
        json.dumps(
            {
                "length": len(best_track.candidates),
                "total_score": best_track.total_score,
                "mean_score": mean_node_score(best_track),
                "monotonic_fraction": monotonic_fraction(best_track),
                "total_y_travel": total_y_travel(best_track),
                "frames": [
                    {
                        "frame_idx": c.frame_idx,
                        "box": [c.x1, c.y1, c.x2, c.y2],
                        "center": [c.cx, c.cy],
                        "score": c.score,
                        "darkness": c.darkness,
                        "contrast": c.contrast,
                    }
                    for c in best_track.candidates
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    seed_json = output_dir / "seed.json"
    seed_json.write_text(
        json.dumps(
            {
                "video": video_path,
                "frame_idx": seed_candidate.frame_idx,
                "box": [seed_candidate.x1, seed_candidate.y1, seed_candidate.x2, seed_candidate.y2],
                "center": [seed_candidate.cx, seed_candidate.cy],
                "initializer": "dark_compact_motion",
                "coarse_box": [coarse_seed_candidate.x1, coarse_seed_candidate.y1, coarse_seed_candidate.x2, coarse_seed_candidate.y2],
                "coarse_center": [coarse_seed_candidate.cx, coarse_seed_candidate.cy],
                "refined_seed": refined,
                "track_length": len(best_track.candidates),
                "score": seed_candidate.score,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(Path(args.sam_script).resolve()),
        "--video",
        video_path,
        "--checkpoint",
        str(Path(args.sam_checkpoint).resolve()),
        "--model-cfg",
        args.sam_model_cfg,
        "--seed-frame",
        str(seed_candidate.frame_idx),
        "--seed-x",
        f"{seed_candidate.cx:.2f}",
        "--seed-y",
        f"{seed_candidate.cy:.2f}",
        "--box",
        f"{seed_candidate.x1:.2f}",
        f"{seed_candidate.y1:.2f}",
        f"{seed_candidate.x2:.2f}",
        f"{seed_candidate.y2:.2f}",
        "--box-only",
        "--output-dir",
        str(sam_output_dir),
    ]
    if args.sam_vos_optimized:
        cmd.append("--vos-optimized")
    if args.sam_no_preview:
        cmd.append("--no-preview")
    if args.frame_limit > 0:
        cmd.extend(["--frame-limit", str(args.frame_limit)])

    completed = None
    if not args.seed_only:
        print("Running SAM2 from the dark compact motion seed...")
        completed = subprocess.run(cmd, check=True)

    pipeline_summary = output_dir / "pipeline_summary.txt"
    with pipeline_summary.open("w", encoding="utf-8") as handle:
        handle.write(f"video={video_path}\n")
        handle.write("initializer=dark_compact_motion\n")
        handle.write(f"lane_model=default_bowling_corridor\n")
        handle.write(f"lane_points={lane_points.tolist()}\n")
        handle.write(f"scan_start={scan_start}\n")
        handle.write(f"scan_end={scan_end}\n")
        handle.write(f"scan_step={args.scan_step}\n")
        handle.write(f"sampled_frames={sampled_frames}\n")
        handle.write(f"motion_threshold={args.motion_threshold}\n")
        handle.write(f"candidate_count={len(candidates)}\n")
        handle.write(f"track_length={len(best_track.candidates)}\n")
        handle.write(f"track_total_score={best_track.total_score:.6f}\n")
        handle.write(f"track_mean_score={mean_node_score(best_track):.6f}\n")
        handle.write(f"track_monotonic_fraction={monotonic_fraction(best_track):.6f}\n")
        handle.write(f"track_total_y_travel={total_y_travel(best_track):.2f}\n")
        handle.write(f"coarse_seed_frame={coarse_seed_candidate.frame_idx}\n")
        handle.write(f"coarse_seed_box=[{coarse_seed_candidate.x1:.2f}, {coarse_seed_candidate.y1:.2f}, {coarse_seed_candidate.x2:.2f}, {coarse_seed_candidate.y2:.2f}]\n")
        handle.write(f"coarse_seed_center=[{coarse_seed_candidate.cx:.2f}, {coarse_seed_candidate.cy:.2f}]\n")
        handle.write(f"seed_refined={refined}\n")
        handle.write(f"seed_frame={seed_candidate.frame_idx}\n")
        handle.write(f"seed_box=[{seed_candidate.x1:.2f}, {seed_candidate.y1:.2f}, {seed_candidate.x2:.2f}, {seed_candidate.y2:.2f}]\n")
        handle.write(f"seed_center=[{seed_candidate.cx:.2f}, {seed_candidate.cy:.2f}]\n")
        handle.write(f"seed_score={seed_candidate.score:.6f}\n")
        handle.write(f"track_json={track_path}\n")
        handle.write(f"seed_json={seed_json}\n")
        handle.write(f"best_detection={best_detection_path}\n")
        handle.write(f"detections_csv={detections_csv}\n")
        handle.write(f"seed_only={args.seed_only}\n")
        if not args.seed_only:
            handle.write(f"sam2_output={sam_output_dir}\n")
            handle.write(f"sam2_command={' '.join(cmd)}\n")
            handle.write(f"sam2_return_code={completed.returncode}\n")

    if args.seed_only:
        print(f"Done. Seed-only dark compact motion outputs written to {output_dir}")
    else:
        print(f"Done. Dark compact motion auto-init outputs written to {output_dir}")


if __name__ == "__main__":
    main()
