from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class HoughSegment:
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]
    length_px: float
    angle_rad: float

    def as_dict(self) -> dict:
        return {
            "start_xy": [float(self.start_xy[0]), float(self.start_xy[1])],
            "end_xy": [float(self.end_xy[0]), float(self.end_xy[1])],
            "length_px": float(self.length_px),
            "angle_deg": float(np.degrees(self.angle_rad)),
        }


@dataclass(frozen=True)
class EdgeContext:
    gray: np.ndarray
    edges: np.ndarray
    distance_to_edge: np.ndarray
    hough_segments: list[HoughSegment]


def build_edge_context(
    image_bgr: np.ndarray,
    canny_low_threshold: int = 80,
    canny_high_threshold: int = 180,
    hough_threshold: int = 50,
    min_line_length_px: int = 50,
    max_line_gap_px: int = 25,
) -> EdgeContext:
    import cv2

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, canny_low_threshold, canny_high_threshold)
    distance_to_edge = cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3)

    raw_segments = cv2.HoughLinesP(
        edges,
        rho=1.0,
        theta=np.pi / 180.0,
        threshold=hough_threshold,
        minLineLength=min_line_length_px,
        maxLineGap=max_line_gap_px,
    )
    hough_segments: list[HoughSegment] = []
    if raw_segments is not None:
        for segment in raw_segments[:, 0, :].tolist():
            x1, y1, x2, y2 = [float(value) for value in segment]
            dx = x2 - x1
            dy = y2 - y1
            length_px = float(np.hypot(dx, dy))
            if length_px < float(min_line_length_px):
                continue
            hough_segments.append(
                HoughSegment(
                    start_xy=(x1, y1),
                    end_xy=(x2, y2),
                    length_px=length_px,
                    angle_rad=float(np.arctan2(dy, dx)),
                )
            )

    return EdgeContext(
        gray=gray,
        edges=edges,
        distance_to_edge=distance_to_edge,
        hough_segments=hough_segments,
    )


def score_lane_projection(
    edge_context: EdgeContext,
    image_points_xy: list[list[float] | None],
    max_distance_px: float = 12.0,
    angle_tolerance_deg: float = 12.0,
    line_distance_tolerance_px: float = 20.0,
) -> dict:
    projected = [None if point is None else np.asarray(point, dtype=np.float64) for point in image_points_xy]
    if projected[0] is None or projected[1] is None or projected[2] is None or projected[3] is None:
        return {
            "total_score": 0.0,
            "left_score": 0.0,
            "right_score": 0.0,
            "left_edge_score": 0.0,
            "right_edge_score": 0.0,
            "left_hough_score": 0.0,
            "right_hough_score": 0.0,
            "left_match": None,
            "right_match": None,
        }

    left = _score_projected_segment(
        edge_context=edge_context,
        start_xy=projected[0],
        end_xy=projected[3],
        max_distance_px=max_distance_px,
        angle_tolerance_deg=angle_tolerance_deg,
        line_distance_tolerance_px=line_distance_tolerance_px,
    )
    right = _score_projected_segment(
        edge_context=edge_context,
        start_xy=projected[1],
        end_xy=projected[2],
        max_distance_px=max_distance_px,
        angle_tolerance_deg=angle_tolerance_deg,
        line_distance_tolerance_px=line_distance_tolerance_px,
    )
    total_score = 0.5 * (left["segment_score"] + right["segment_score"])
    return {
        "total_score": float(total_score),
        "left_score": float(left["segment_score"]),
        "right_score": float(right["segment_score"]),
        "left_edge_score": float(left["edge_score"]),
        "right_edge_score": float(right["edge_score"]),
        "left_hough_score": float(left["hough_score"]),
        "right_hough_score": float(right["hough_score"]),
        "left_match": left["match"],
        "right_match": right["match"],
    }


def _score_projected_segment(
    edge_context: EdgeContext,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    max_distance_px: float,
    angle_tolerance_deg: float,
    line_distance_tolerance_px: float,
) -> dict:
    edge_score = _edge_support_score(
        distance_to_edge=edge_context.distance_to_edge,
        start_xy=start_xy,
        end_xy=end_xy,
        max_distance_px=max_distance_px,
    )
    hough_score, match = _best_hough_match(
        hough_segments=edge_context.hough_segments,
        start_xy=start_xy,
        end_xy=end_xy,
        angle_tolerance_deg=angle_tolerance_deg,
        line_distance_tolerance_px=line_distance_tolerance_px,
    )
    segment_score = 0.65 * edge_score + 0.35 * hough_score
    return {
        "edge_score": float(edge_score),
        "hough_score": float(hough_score),
        "segment_score": float(segment_score),
        "match": match,
    }


def _edge_support_score(
    distance_to_edge: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    max_distance_px: float,
    sample_count: int = 48,
) -> float:
    scores: list[float] = []
    height, width = distance_to_edge.shape[:2]
    for t in np.linspace(0.05, 0.95, sample_count):
        sample = (1.0 - t) * start_xy + t * end_xy
        x = int(round(float(sample[0])))
        y = int(round(float(sample[1])))
        if 0 <= x < width and 0 <= y < height:
            distance_px = float(distance_to_edge[y, x])
            scores.append(max(0.0, 1.0 - min(distance_px, max_distance_px) / max_distance_px))
    if not scores:
        return 0.0
    return float(np.mean(scores))


def _best_hough_match(
    hough_segments: list[HoughSegment],
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    angle_tolerance_deg: float,
    line_distance_tolerance_px: float,
) -> tuple[float, dict | None]:
    dx = float(end_xy[0] - start_xy[0])
    dy = float(end_xy[1] - start_xy[1])
    segment_length = float(np.hypot(dx, dy))
    if segment_length <= 1e-6:
        return 0.0, None

    predicted_angle = float(np.arctan2(dy, dx))
    best_score = 0.0
    best_match = None
    angle_tolerance_rad = np.radians(angle_tolerance_deg)

    for hough_segment in hough_segments:
        angle_delta = _wrapped_angle_distance_rad(predicted_angle, hough_segment.angle_rad)
        if angle_delta > angle_tolerance_rad:
            continue

        midpoint = 0.5 * (
            np.asarray(hough_segment.start_xy, dtype=np.float64) + np.asarray(hough_segment.end_xy, dtype=np.float64)
        )
        line_distance_px = _point_to_line_distance_px(midpoint, start_xy, end_xy)
        if line_distance_px > line_distance_tolerance_px:
            continue

        angle_score = max(0.0, 1.0 - angle_delta / angle_tolerance_rad)
        distance_score = max(0.0, 1.0 - line_distance_px / line_distance_tolerance_px)
        length_score = min(1.0, hough_segment.length_px / 220.0)
        score = float(angle_score * distance_score * length_score)
        if score <= best_score:
            continue

        best_score = score
        best_match = {
            **hough_segment.as_dict(),
            "angle_delta_deg": float(np.degrees(angle_delta)),
            "line_distance_px": float(line_distance_px),
            "score": float(score),
        }

    return best_score, best_match


def _wrapped_angle_distance_rad(angle_a: float, angle_b: float) -> float:
    delta = abs(angle_a - angle_b)
    delta = min(delta, abs(delta - np.pi), abs(delta + np.pi))
    return float(delta)


def _point_to_line_distance_px(point_xy: np.ndarray, start_xy: np.ndarray, end_xy: np.ndarray) -> float:
    line_dx = float(end_xy[0] - start_xy[0])
    line_dy = float(end_xy[1] - start_xy[1])
    norm = float(np.hypot(line_dx, line_dy))
    if norm <= 1e-6:
        return float(np.hypot(*(point_xy - start_xy)))
    numerator = abs(line_dy * float(point_xy[0] - start_xy[0]) - line_dx * float(point_xy[1] - start_xy[1]))
    return float(numerator / norm)
