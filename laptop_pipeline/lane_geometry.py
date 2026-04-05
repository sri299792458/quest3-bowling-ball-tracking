from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np


@dataclass
class LaneHypothesis:
    points: np.ndarray
    model: str
    confidence: float
    geometry_score: float
    brightness_score: float
    line_score: float
    bottom_width: float
    top_width: float
    top_y: int
    vanishing_point: tuple[float, float] | None = None
    source_lines: list[list[int]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [[float(x), float(y)] for x, y in self.points.tolist()],
            "model": self.model,
            "confidence": float(self.confidence),
            "geometry_score": float(self.geometry_score),
            "brightness_score": float(self.brightness_score),
            "line_score": float(self.line_score),
            "bottom_width": float(self.bottom_width),
            "top_width": float(self.top_width),
            "top_y": int(self.top_y),
            "vanishing_point": [float(v) for v in self.vanishing_point] if self.vanishing_point is not None else None,
            "source_lines": self.source_lines or [],
        }


@dataclass
class _BoundaryLine:
    x1: float
    y1: float
    x2: float
    y2: float
    a: float
    b: float
    length: float
    side: str

    def x_at(self, y: float) -> float:
        return self.a * y + self.b

    def to_list(self) -> list[int]:
        return [int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2))]


def build_default_lane_hypothesis(frame_width: int, frame_height: int) -> LaneHypothesis:
    points = np.array(
        [
            [int(frame_width * 0.18), frame_height - 1],
            [int(frame_width * 0.82), frame_height - 1],
            [int(frame_width * 0.63), int(frame_height * 0.24)],
            [int(frame_width * 0.37), int(frame_height * 0.24)],
        ],
        dtype=np.int32,
    )
    return LaneHypothesis(
        points=points,
        model="default_bowling_corridor",
        confidence=0.15,
        geometry_score=0.15,
        brightness_score=0.0,
        line_score=0.0,
        bottom_width=float(points[1, 0] - points[0, 0]),
        top_width=float(points[2, 0] - points[3, 0]),
        top_y=int(points[2, 1]),
        vanishing_point=None,
        source_lines=[],
    )


def build_lane_mask(points: np.ndarray, frame_width: int, frame_height: int) -> np.ndarray:
    mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    cv2.fillPoly(mask, [points.astype(np.int32)], 255)
    return mask


def build_union_lane_mask(hypotheses: list[LaneHypothesis], frame_width: int, frame_height: int) -> np.ndarray:
    if not hypotheses:
        return build_lane_mask(build_default_lane_hypothesis(frame_width, frame_height).points, frame_width, frame_height)
    mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    for hypothesis in hypotheses:
        cv2.fillPoly(mask, [hypothesis.points.astype(np.int32)], 255)
    return mask


def lane_bounds_at_y(points: np.ndarray, y: float) -> tuple[float, float]:
    left_bottom = points[0].astype(np.float32)
    right_bottom = points[1].astype(np.float32)
    right_top = points[2].astype(np.float32)
    left_top = points[3].astype(np.float32)

    min_y = min(float(left_top[1]), float(right_top[1]))
    max_y = max(float(left_bottom[1]), float(right_bottom[1]))
    clamped_y = min(max(float(y), min_y), max_y)

    def _interp_x(a: np.ndarray, b: np.ndarray) -> float:
        dy = float(b[1] - a[1])
        if abs(dy) < 1e-6:
            return float(a[0])
        t = (clamped_y - float(a[1])) / dy
        return float(a[0] + t * float(b[0] - a[0]))

    left_x = _interp_x(left_top, left_bottom)
    right_x = _interp_x(right_top, right_bottom)
    if left_x > right_x:
        left_x, right_x = right_x, left_x
    return left_x, right_x


def normalized_lateral_position(points: np.ndarray, x: float, y: float) -> Optional[float]:
    left_x, right_x = lane_bounds_at_y(points, y)
    width = right_x - left_x
    if width <= 1e-6:
        return None
    return float((x - left_x) / width)


def render_lane_overlay(
    frame_rgb: np.ndarray,
    hypotheses: list[LaneHypothesis],
    selected_hypothesis: LaneHypothesis | None = None,
) -> np.ndarray:
    image_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    palette = [(0, 220, 255), (60, 180, 75), (255, 190, 0), (255, 120, 120), (160, 90, 255)]
    for index, hypothesis in enumerate(hypotheses):
        color = palette[index % len(palette)]
        cv2.polylines(image_bgr, [hypothesis.points.astype(np.int32)], True, color, 2, cv2.LINE_AA)
        label = f"{index + 1}: {hypothesis.model} {hypothesis.confidence:.2f}"
        anchor = tuple(int(v) for v in hypothesis.points[3])
        cv2.putText(image_bgr, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    if selected_hypothesis is not None:
        cv2.polylines(image_bgr, [selected_hypothesis.points.astype(np.int32)], True, (0, 0, 255), 3, cv2.LINE_AA)
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def estimate_lane_hypotheses(frame_rgb: np.ndarray, max_hypotheses: int = 4) -> list[LaneHypothesis]:
    frame_height, frame_width = frame_rgb.shape[:2]
    default = build_default_lane_hypothesis(frame_width, frame_height)

    gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=80,
        minLineLength=int(frame_height * 0.18),
        maxLineGap=25,
    )
    if lines is None or len(lines) == 0:
        return [default]

    left_lines, right_lines = _extract_boundary_lines(lines, frame_width, frame_height)
    if not left_lines or not right_lines:
        return [default]

    hypotheses = _pair_lane_boundaries(gray, left_lines, right_lines, frame_width, frame_height)
    if not hypotheses:
        return [default]

    hypotheses.sort(key=lambda item: item.confidence, reverse=True)
    return hypotheses[:max_hypotheses]


def _extract_boundary_lines(lines: np.ndarray, frame_width: int, frame_height: int) -> tuple[list[_BoundaryLine], list[_BoundaryLine]]:
    candidates: list[_BoundaryLine] = []
    for entry in lines[:, 0, :]:
        x1, y1, x2, y2 = (float(value) for value in entry.tolist())
        dx = x2 - x1
        dy = y2 - y1
        if abs(dy) < frame_height * 0.12:
            continue
        slope = dx / dy
        if abs(slope) < 0.08 or abs(slope) > 1.8:
            continue
        length = math.hypot(dx, dy)
        intercept = x1 - slope * y1
        x_bottom = slope * (frame_height - 1) + intercept
        if x_bottom < -frame_width * 0.60 or x_bottom > frame_width * 1.60:
            continue
        side = "left" if slope < 0.0 else "right"
        candidates.append(
            _BoundaryLine(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                a=slope,
                b=intercept,
                length=length,
                side=side,
            )
        )

    def _dedupe(side: str) -> list[_BoundaryLine]:
        kept: list[_BoundaryLine] = []
        candidates_for_side = sorted([line for line in candidates if line.side == side], key=lambda item: item.length, reverse=True)
        sample_y_bottom = frame_height - 1
        sample_y_mid = frame_height * 0.55
        for candidate in candidates_for_side:
            duplicated = False
            for existing in kept:
                if (
                    abs(candidate.x_at(sample_y_bottom) - existing.x_at(sample_y_bottom)) < 26.0
                    and abs(candidate.x_at(sample_y_mid) - existing.x_at(sample_y_mid)) < 18.0
                    and abs(candidate.a - existing.a) < 0.12
                ):
                    duplicated = True
                    break
            if not duplicated:
                kept.append(candidate)
            if len(kept) >= 10:
                break
        return kept

    return _dedupe("left"), _dedupe("right")


def _pair_lane_boundaries(
    gray_frame: np.ndarray,
    left_lines: list[_BoundaryLine],
    right_lines: list[_BoundaryLine],
    frame_width: int,
    frame_height: int,
) -> list[LaneHypothesis]:
    center_x = frame_width / 2.0
    hypotheses: list[LaneHypothesis] = []

    for left in left_lines:
        for right in right_lines:
            denom = left.a - right.a
            if abs(denom) < 1e-6:
                continue
            vanishing_y = (right.b - left.b) / denom
            vanishing_x = left.x_at(vanishing_y)
            if not (frame_height * 0.05 <= vanishing_y <= frame_height * 0.45):
                continue
            if not (frame_width * 0.15 <= vanishing_x <= frame_width * 0.85):
                continue

            top_y = int(round(np.clip(vanishing_y + frame_height * 0.07, frame_height * 0.18, frame_height * 0.42)))
            bottom_y = frame_height - 1
            left_bottom_x = left.x_at(bottom_y)
            right_bottom_x = right.x_at(bottom_y)
            left_top_x = left.x_at(top_y)
            right_top_x = right.x_at(top_y)
            bottom_width = right_bottom_x - left_bottom_x
            top_width = right_top_x - left_top_x
            if bottom_width <= frame_width * 0.18 or bottom_width >= frame_width * 0.80:
                continue
            if top_width <= frame_width * 0.02 or top_width >= frame_width * 0.28:
                continue

            polygon = np.array(
                [
                    [left_bottom_x, bottom_y],
                    [right_bottom_x, bottom_y],
                    [right_top_x, top_y],
                    [left_top_x, top_y],
                ],
                dtype=np.float32,
            )
            polygon[:, 0] = np.clip(polygon[:, 0], -frame_width * 0.10, frame_width * 1.10)
            polygon[:, 1] = np.clip(polygon[:, 1], 0, frame_height - 1)
            brightness_score = _corridor_brightness(gray_frame, polygon.astype(np.int32), frame_width, frame_height)
            line_score = min((left.length + right.length) / max(frame_height * 1.3, 1.0), 1.0)
            center_bottom = (left_bottom_x + right_bottom_x) * 0.5
            center_top = (left_top_x + right_top_x) * 0.5
            geometry_score = _geometry_score(
                frame_width,
                frame_height,
                center_x,
                vanishing_x,
                center_bottom,
                center_top,
                bottom_width,
                top_width,
            )
            confidence = 0.45 * geometry_score + 0.35 * brightness_score + 0.20 * line_score
            hypotheses.append(
                LaneHypothesis(
                    points=polygon.astype(np.int32),
                    model="video_lane_hough",
                    confidence=float(confidence),
                    geometry_score=float(geometry_score),
                    brightness_score=float(brightness_score),
                    line_score=float(line_score),
                    bottom_width=float(bottom_width),
                    top_width=float(top_width),
                    top_y=int(top_y),
                    vanishing_point=(float(vanishing_x), float(vanishing_y)),
                    source_lines=[left.to_list(), right.to_list()],
                )
            )

    return _dedupe_hypotheses(hypotheses)


def _corridor_brightness(gray_frame: np.ndarray, polygon: np.ndarray, frame_width: int, frame_height: int) -> float:
    mask = build_lane_mask(polygon, frame_width, frame_height)
    lane_pixels = gray_frame[mask > 0]
    if lane_pixels.size == 0:
        return 0.0

    inside_mean = float(np.mean(lane_pixels))
    bottom_slice = mask.copy()
    top_cutoff = int(round(polygon[:, 1].min() + (frame_height - polygon[:, 1].min()) * 0.35))
    bottom_slice[:top_cutoff, :] = 0
    bottom_pixels = gray_frame[bottom_slice > 0]
    if bottom_pixels.size == 0:
        bottom_pixels = lane_pixels
    bottom_mean = float(np.mean(bottom_pixels))

    margin = int(max(16, round(frame_width * 0.015)))
    expanded = polygon.astype(np.int32).copy()
    expanded[0, 0] -= margin
    expanded[3, 0] -= margin
    expanded[1, 0] += margin
    expanded[2, 0] += margin
    expanded[:, 0] = np.clip(expanded[:, 0], 0, frame_width - 1)
    outer_mask = build_lane_mask(expanded, frame_width, frame_height)
    ring_mask = cv2.subtract(outer_mask, mask)
    ring_pixels = gray_frame[ring_mask > 0]
    ring_mean = float(np.mean(ring_pixels)) if ring_pixels.size > 0 else inside_mean

    mean_score = np.clip((inside_mean - 105.0) / 85.0, 0.0, 1.0)
    bottom_score = np.clip((bottom_mean - 120.0) / 75.0, 0.0, 1.0)
    contrast_score = np.clip((inside_mean - ring_mean + 18.0) / 55.0, 0.0, 1.0)
    std_value = float(np.std(bottom_pixels))
    std_score = 1.0 - np.clip((std_value - 24.0) / 40.0, 0.0, 1.0)
    dark_fraction = float(np.mean(bottom_pixels < 72.0))
    dark_score = 1.0 - np.clip((dark_fraction - 0.03) / 0.18, 0.0, 1.0)
    return float(
        0.25 * mean_score
        + 0.25 * bottom_score
        + 0.20 * contrast_score
        + 0.18 * std_score
        + 0.12 * dark_score
    )


def _geometry_score(
    frame_width: int,
    frame_height: int,
    image_center_x: float,
    vanishing_x: float,
    bottom_center_x: float,
    top_center_x: float,
    bottom_width: float,
    top_width: float,
) -> float:
    vanish_score = 1.0 - np.clip(abs(vanishing_x - image_center_x) / (frame_width * 0.42), 0.0, 1.0)
    bottom_width_score = 1.0 - np.clip(abs((bottom_width / frame_width) - 0.38) / 0.22, 0.0, 1.0)
    top_width_score = 1.0 - np.clip(abs((top_width / frame_width) - 0.06) / 0.09, 0.0, 1.0)
    bottom_center_score = 1.0 - np.clip(abs(bottom_center_x - image_center_x) / (frame_width * 0.58), 0.0, 1.0)
    top_center_score = 1.0 - np.clip(abs(top_center_x - image_center_x) / (frame_width * 0.20), 0.0, 1.0)
    return float(
        0.25 * vanish_score
        + 0.25 * bottom_width_score
        + 0.20 * top_width_score
        + 0.15 * bottom_center_score
        + 0.15 * top_center_score
    )


def _dedupe_hypotheses(hypotheses: list[LaneHypothesis]) -> list[LaneHypothesis]:
    unique: list[LaneHypothesis] = []
    ordered = sorted(hypotheses, key=lambda item: item.confidence, reverse=True)
    for candidate in ordered:
        duplicate = False
        candidate_bottom_center = float((candidate.points[0, 0] + candidate.points[1, 0]) * 0.5)
        candidate_top_center = float((candidate.points[2, 0] + candidate.points[3, 0]) * 0.5)
        for existing in unique:
            existing_bottom_center = float((existing.points[0, 0] + existing.points[1, 0]) * 0.5)
            existing_top_center = float((existing.points[2, 0] + existing.points[3, 0]) * 0.5)
            if (
                abs(candidate_bottom_center - existing_bottom_center) < 42.0
                and abs(candidate.bottom_width - existing.bottom_width) < 60.0
                and abs(candidate_top_center - existing_top_center) < 18.0
            ):
                duplicate = True
                break
        if not duplicate:
            unique.append(candidate)
        if len(unique) >= 6:
            break
    return unique
