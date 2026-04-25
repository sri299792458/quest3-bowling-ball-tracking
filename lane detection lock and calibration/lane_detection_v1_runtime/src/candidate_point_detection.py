from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .edge_refinement import EdgeContext, build_edge_context


@dataclass(frozen=True)
class CandidatePoint:
    candidate_id: int
    point_xy: tuple[float, float]
    score: float
    side_support: float
    cross_support: float
    corner_strength: float
    bottom_score: float
    sources: tuple[str, ...]
    debug: dict

    def as_dict(self) -> dict:
        return {
            "candidate_id": int(self.candidate_id),
            "point_xy": [float(self.point_xy[0]), float(self.point_xy[1])],
            "score": float(self.score),
            "side_support": float(self.side_support),
            "cross_support": float(self.cross_support),
            "corner_strength": float(self.corner_strength),
            "bottom_score": float(self.bottom_score),
            "sources": list(self.sources),
            "debug": self.debug,
        }


def detect_candidate_points(
    image_bgr: np.ndarray,
    max_candidates: int = 26,
) -> list[CandidatePoint]:
    gray, corner_strength_map, corner_points_xy = _build_corner_context(image_bgr)
    edge_context = build_edge_context(
        image_bgr=image_bgr,
        canny_low_threshold=60,
        canny_high_threshold=160,
        hough_threshold=35,
        min_line_length_px=25,
        max_line_gap_px=20,
    )
    height, width = gray.shape[:2]

    side_segments = []
    cross_segments = []
    for segment in edge_context.hough_segments:
        start_xy = np.asarray(segment.start_xy, dtype=np.float64)
        end_xy = np.asarray(segment.end_xy, dtype=np.float64)
        midpoint_xy = 0.5 * (start_xy + end_xy)
        absolute_angle_deg = abs(float(np.degrees(segment.angle_rad)))
        if 38.0 <= absolute_angle_deg <= 100.0 and segment.length_px >= 55.0:
            side_segments.append((start_xy, end_xy, segment.angle_rad, segment.length_px, midpoint_xy, segment))
        if absolute_angle_deg <= 25.0 and segment.length_px >= 40.0 and midpoint_xy[1] >= 0.32 * float(height):
            cross_segments.append((start_xy, end_xy, segment.angle_rad, segment.length_px, midpoint_xy, segment))

    raw_candidates: list[dict] = []

    def add_candidate(
        point_xy: np.ndarray,
        source: str,
        base_score: float,
        side_support: float,
        cross_support: float,
        debug: dict,
    ) -> None:
        if not (-30.0 <= point_xy[0] < float(width) + 30.0 and -30.0 <= point_xy[1] < float(height) + 30.0):
            return
        x_index = int(np.clip(round(float(point_xy[0])), 0, width - 1))
        y_index = int(np.clip(round(float(point_xy[1])), 0, height - 1))
        raw_candidates.append(
            {
                "point_xy": point_xy.astype(np.float64),
                "sources": {source},
                "base_score": float(base_score),
                "side_support": float(max(0.0, side_support)),
                "cross_support": float(max(0.0, cross_support)),
                "corner_strength": float(corner_strength_map[y_index, x_index]),
                "bottom_score": float(y_index / max(1, height)),
                "debug": debug,
            }
        )

    # Candidate source 1: intersections between strong lane-side segments and lower seam-like segments.
    for (
        side_start_xy,
        side_end_xy,
        side_angle_rad,
        side_length_px,
        _side_midpoint_xy,
        side_segment,
    ) in side_segments:
        for (
            cross_start_xy,
            cross_end_xy,
            cross_angle_rad,
            cross_length_px,
            _cross_midpoint_xy,
            cross_segment,
        ) in cross_segments:
            intersection_xy = _line_intersection_xy(
                side_start_xy,
                side_end_xy,
                cross_start_xy,
                cross_end_xy,
            )
            if intersection_xy is None:
                continue

            angle_delta_deg = float(np.degrees(_wrapped_angle_distance_rad(side_angle_rad, cross_angle_rad)))
            if angle_delta_deg < 45.0 or angle_delta_deg > 130.0:
                continue

            side_endpoint_distance_px = _endpoint_distance_px(intersection_xy, side_start_xy, side_end_xy)
            cross_segment_distance_px, cross_segment_t = _point_to_segment_distance_and_parameter(
                intersection_xy,
                cross_start_xy,
                cross_end_xy,
            )
            if side_endpoint_distance_px > 38.0:
                continue
            if not (-1.2 <= cross_segment_t <= 5.2):
                continue

            extension_support = max(
                0.0,
                1.0 - max(0.0, abs(cross_segment_t - 0.5) - 0.5) / 4.2,
            )
            finite_cross_support = max(0.0, 1.0 - min(cross_segment_distance_px, 180.0) / 180.0)

            x_index = int(np.clip(round(float(intersection_xy[0])), 0, width - 1))
            y_index = int(np.clip(round(float(intersection_xy[1])), 0, height - 1))
            corner_strength = float(corner_strength_map[y_index, x_index])

            base_score = (
                0.28 * min(side_length_px, 250.0) / 250.0
                + 0.22 * min(cross_length_px, 200.0) / 200.0
                + 0.16 * (1.0 - abs(angle_delta_deg - 90.0) / 45.0)
                + 0.18 * (1.0 - min(side_endpoint_distance_px, 38.0) / 38.0)
                + 0.10 * extension_support
                + 0.06 * finite_cross_support
                + 0.10 * corner_strength
            )
            add_candidate(
                point_xy=intersection_xy,
                source="side_cross",
                base_score=base_score,
                side_support=1.0 - min(side_endpoint_distance_px, 38.0) / 38.0,
                cross_support=max(extension_support, finite_cross_support),
                debug={
                    "type": "side_cross",
                    "angle_delta_deg": angle_delta_deg,
                    "side_endpoint_distance_px": float(side_endpoint_distance_px),
                    "cross_segment_distance_px": float(cross_segment_distance_px),
                    "cross_segment_t": float(cross_segment_t),
                    "side_segment": side_segment.as_dict(),
                    "cross_segment": cross_segment.as_dict(),
                },
            )

    # Candidate source 2: corner points supported by nearby lane-side lines, optionally plus seam support.
    for corner_point_xy in corner_points_xy:
        x_index = int(np.clip(round(float(corner_point_xy[0])), 0, width - 1))
        y_index = int(np.clip(round(float(corner_point_xy[1])), 0, height - 1))
        if y_index < int(0.28 * float(height)):
            continue

        best_side_support = 0.0
        best_cross_support = 0.0
        best_side_debug = None
        best_cross_debug = None

        for side_start_xy, side_end_xy, _side_angle_rad, side_length_px, _side_midpoint_xy, side_segment in side_segments:
            distance_px, _segment_t = _point_to_segment_distance_and_parameter(
                corner_point_xy,
                side_start_xy,
                side_end_xy,
            )
            if distance_px >= 12.0:
                continue
            endpoint_distance_px = _endpoint_distance_px(corner_point_xy, side_start_xy, side_end_xy)
            support = (
                0.60 * min(side_length_px, 220.0) / 220.0
                + 0.40 * max(0.0, 1.0 - distance_px / 12.0)
                + 0.25 * max(0.0, 1.0 - min(endpoint_distance_px, 40.0) / 40.0)
            )
            if support > best_side_support:
                best_side_support = float(support)
                best_side_debug = {
                    "distance_px": float(distance_px),
                    "endpoint_distance_px": float(endpoint_distance_px),
                    "segment": side_segment.as_dict(),
                }

        for cross_start_xy, cross_end_xy, _cross_angle_rad, cross_length_px, _cross_midpoint_xy, cross_segment in cross_segments:
            distance_px, segment_t = _point_to_segment_distance_and_parameter(
                corner_point_xy,
                cross_start_xy,
                cross_end_xy,
            )
            if not (distance_px < 15.0 or (-1.0 <= segment_t <= 4.5 and distance_px < 35.0)):
                continue
            extension_support = max(
                0.0,
                1.0 - max(0.0, abs(segment_t - 0.5) - 0.5) / 4.0,
            )
            support = (
                0.50 * min(cross_length_px, 180.0) / 180.0
                + 0.20 * max(0.0, 1.0 - min(distance_px, 35.0) / 35.0)
                + 0.30 * extension_support
            )
            if support > best_cross_support:
                best_cross_support = float(support)
                best_cross_debug = {
                    "distance_px": float(distance_px),
                    "segment_t": float(segment_t),
                    "segment": cross_segment.as_dict(),
                }

        if best_side_support <= 0.18 and best_cross_support <= 0.30:
            continue

        base_score = (
            0.48 * best_side_support
            + 0.32 * best_cross_support
            + 0.12 * float(corner_strength_map[y_index, x_index])
        )
        add_candidate(
            point_xy=corner_point_xy,
            source="corner_support",
            base_score=base_score,
            side_support=best_side_support,
            cross_support=best_cross_support,
            debug={
                "type": "corner_support",
                "best_side_debug": best_side_debug,
                "best_cross_debug": best_cross_debug,
            },
        )

    merged_candidates = _merge_close_candidates(raw_candidates, merge_radius_px=16.0)
    shortlisted_candidates = _select_final_candidates(
        merged_candidates=merged_candidates,
        image_width=width,
        image_height=height,
        max_candidates=max_candidates,
    )

    final_candidates: list[CandidatePoint] = []
    for candidate_id, candidate in enumerate(shortlisted_candidates, start=1):
        final_candidates.append(
            CandidatePoint(
                candidate_id=candidate_id,
                point_xy=(float(candidate["point_xy"][0]), float(candidate["point_xy"][1])),
                score=float(candidate["score"]),
                side_support=float(candidate["side_support"]),
                cross_support=float(candidate["cross_support"]),
                corner_strength=float(candidate["corner_strength"]),
                bottom_score=float(candidate["bottom_score"]),
                sources=tuple(sorted(candidate["sources"])),
                debug=candidate["debug"],
            )
        )
    return final_candidates


def find_nearest_candidate(
    click_xy: tuple[float, float],
    candidates: list[CandidatePoint],
) -> tuple[CandidatePoint | None, float]:
    if not candidates:
        return None, float("inf")
    click_vector = np.asarray(click_xy, dtype=np.float64)
    best_candidate = None
    best_distance = float("inf")
    for candidate in candidates:
        candidate_vector = np.asarray(candidate.point_xy, dtype=np.float64)
        distance_px = float(np.linalg.norm(click_vector - candidate_vector))
        if distance_px < best_distance:
            best_candidate = candidate
            best_distance = distance_px
    return best_candidate, best_distance


def _build_corner_context(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    import cv2

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    corner_strength = cv2.cornerHarris(np.float32(gray) / 255.0, 2, 3, 0.04)
    corner_strength = cv2.GaussianBlur(corner_strength, (3, 3), 0)
    corner_strength = (corner_strength - corner_strength.min()) / max(1e-6, corner_strength.max() - corner_strength.min())

    raw_corners = cv2.goodFeaturesToTrack(
        gray,
        maxCorners=220,
        qualityLevel=0.005,
        minDistance=8,
        blockSize=5,
        useHarrisDetector=True,
        k=0.04,
    )
    corner_points_xy = [] if raw_corners is None else [np.asarray(corner[0], dtype=np.float64) for corner in raw_corners]
    return gray, corner_strength, corner_points_xy


def _merge_close_candidates(raw_candidates: list[dict], merge_radius_px: float) -> list[dict]:
    merged_candidates: list[dict] = []
    sorted_candidates = sorted(
        raw_candidates,
        key=lambda candidate: (
            candidate["base_score"] + 0.20 * candidate["bottom_score"] + 0.15 * candidate["corner_strength"]
        ),
        reverse=True,
    )

    for candidate in sorted_candidates:
        merged_into_existing = False
        for existing in merged_candidates:
            if np.linalg.norm(candidate["point_xy"] - existing["point_xy"]) >= merge_radius_px:
                continue
            previous_base_score = existing["base_score"]
            existing["sources"] |= candidate["sources"]
            existing["base_score"] = max(existing["base_score"], candidate["base_score"])
            existing["side_support"] = max(existing["side_support"], candidate["side_support"])
            existing["cross_support"] = max(existing["cross_support"], candidate["cross_support"])
            existing["corner_strength"] = max(existing["corner_strength"], candidate["corner_strength"])
            existing["bottom_score"] = max(existing["bottom_score"], candidate["bottom_score"])
            if candidate["base_score"] > previous_base_score:
                existing["point_xy"] = candidate["point_xy"]
            existing["debug"]["merged_members"].append(candidate["debug"])
            merged_into_existing = True
            break
        if merged_into_existing:
            continue
        merged_candidates.append(
            {
                **candidate,
                "sources": set(candidate["sources"]),
                "debug": {
                    "primary": candidate["debug"],
                    "merged_members": [candidate["debug"]],
                },
            }
        )
    return merged_candidates


def _select_final_candidates(
    merged_candidates: list[dict],
    image_width: int,
    image_height: int,
    max_candidates: int,
) -> list[dict]:
    for candidate in merged_candidates:
        x_norm = float(candidate["point_xy"][0]) / max(1, image_width)
        candidate["score"] = (
            candidate["base_score"]
            + 0.18 * candidate["bottom_score"]
            + 0.10 * candidate["corner_strength"]
            + 0.08 * len(candidate["sources"])
        )
        candidate["lower_preference"] = (
            0.55 * candidate["side_support"]
            + 0.25 * candidate["cross_support"]
            + 0.45 * candidate["bottom_score"]
            + 0.10 * candidate["corner_strength"]
        )
        candidate["left_preference"] = candidate["lower_preference"] - 0.30 * abs(x_norm - 0.35)
        candidate["right_preference"] = candidate["lower_preference"] - 0.30 * abs(x_norm - 0.65)

    final_candidates: list[dict] = []

    def add_ranked_candidates(ranked_candidates: list[dict], cap: int) -> None:
        for candidate in ranked_candidates:
            if all(np.linalg.norm(candidate["point_xy"] - existing["point_xy"]) > 18.0 for existing in final_candidates):
                final_candidates.append(candidate)
            if len(final_candidates) >= cap:
                break

    add_ranked_candidates(sorted(merged_candidates, key=lambda candidate: candidate["score"], reverse=True), min(10, max_candidates))
    add_ranked_candidates(
        sorted(
            [candidate for candidate in merged_candidates if candidate["point_xy"][1] >= 0.45 * float(image_height)],
            key=lambda candidate: candidate["lower_preference"],
            reverse=True,
        ),
        min(18, max_candidates),
    )
    add_ranked_candidates(
        sorted(
            [
                candidate
                for candidate in merged_candidates
                if candidate["point_xy"][1] >= 0.45 * float(image_height) and candidate["point_xy"][0] <= 0.58 * float(image_width)
            ],
            key=lambda candidate: candidate["left_preference"],
            reverse=True,
        ),
        min(22, max_candidates),
    )
    add_ranked_candidates(
        sorted(
            [
                candidate
                for candidate in merged_candidates
                if candidate["point_xy"][1] >= 0.45 * float(image_height) and candidate["point_xy"][0] >= 0.42 * float(image_width)
            ],
            key=lambda candidate: candidate["right_preference"],
            reverse=True,
        ),
        max_candidates,
    )
    return final_candidates[:max_candidates]


def _line_intersection_xy(
    start_a_xy: np.ndarray,
    end_a_xy: np.ndarray,
    start_b_xy: np.ndarray,
    end_b_xy: np.ndarray,
) -> np.ndarray | None:
    x1, y1 = start_a_xy.tolist()
    x2, y2 = end_a_xy.tolist()
    x3, y3 = start_b_xy.tolist()
    x4, y4 = end_b_xy.tolist()
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) <= 1e-6:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denominator
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denominator
    return np.array([px, py], dtype=np.float64)


def _wrapped_angle_distance_rad(angle_a_rad: float, angle_b_rad: float) -> float:
    delta = abs(angle_a_rad - angle_b_rad)
    return float(min(delta, abs(delta - math.pi), abs(delta + math.pi)))


def _endpoint_distance_px(point_xy: np.ndarray, start_xy: np.ndarray, end_xy: np.ndarray) -> float:
    return float(min(np.linalg.norm(point_xy - start_xy), np.linalg.norm(point_xy - end_xy)))


def _point_to_segment_distance_and_parameter(
    point_xy: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
) -> tuple[float, float]:
    segment_vector = end_xy - start_xy
    denominator = float(np.dot(segment_vector, segment_vector))
    if denominator <= 1e-12:
        return float(np.linalg.norm(point_xy - start_xy)), 0.0
    parameter_t = float(np.dot(point_xy - start_xy, segment_vector) / denominator)
    closest_xy = start_xy + np.clip(parameter_t, 0.0, 1.0) * segment_vector
    return float(np.linalg.norm(point_xy - closest_xy)), parameter_t
