from __future__ import annotations

import numpy as np


def draw_lane_polygon(
    image_bgr: np.ndarray,
    image_points_xy: list[list[float] | None],
    labels: list[str],
    edge_color_bgr: tuple[int, int, int],
    point_color_bgr: tuple[int, int, int],
    thickness: int = 2,
) -> None:
    import cv2

    visible_points: list[tuple[int, int]] = []
    visible_labels: list[str] = []
    for label, point_xy in zip(labels, image_points_xy):
        if point_xy is None:
            continue
        x = int(round(float(point_xy[0])))
        y = int(round(float(point_xy[1])))
        visible_points.append((x, y))
        visible_labels.append(label)
        cv2.circle(image_bgr, (x, y), 6, point_color_bgr, -1, cv2.LINE_AA)
        cv2.putText(
            image_bgr,
            label,
            (x + 8, y - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            point_color_bgr,
            2,
            cv2.LINE_AA,
        )

    if len(visible_points) >= 2:
        for start_point, end_point in zip(visible_points[:-1], visible_points[1:]):
            cv2.line(image_bgr, start_point, end_point, edge_color_bgr, thickness, cv2.LINE_AA)
    if len(visible_points) == 4:
        cv2.line(image_bgr, visible_points[-1], visible_points[0], edge_color_bgr, thickness, cv2.LINE_AA)


def draw_click_points(
    image_bgr: np.ndarray,
    image_points_xy: list[list[float]],
    labels: list[str],
    color_bgr: tuple[int, int, int] = (0, 255, 255),
) -> None:
    import cv2

    for label, point_xy in zip(labels, image_points_xy):
        x = int(round(float(point_xy[0])))
        y = int(round(float(point_xy[1])))
        cv2.circle(image_bgr, (x, y), 7, color_bgr, -1, cv2.LINE_AA)
        cv2.putText(
            image_bgr,
            label,
            (x + 8, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color_bgr,
            2,
            cv2.LINE_AA,
        )


def draw_header_lines(
    image_bgr: np.ndarray,
    lines: list[str],
    origin_xy: tuple[int, int] = (16, 28),
    color_bgr: tuple[int, int, int] = (0, 220, 255),
) -> None:
    import cv2

    start_x, start_y = origin_xy
    for index, line in enumerate(lines):
        cv2.putText(
            image_bgr,
            line,
            (start_x, start_y + index * 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color_bgr,
            2,
            cv2.LINE_AA,
        )


def draw_candidate_points(
    image_bgr: np.ndarray,
    candidates: list,
    selected_candidate_ids: set[int] | None = None,
) -> None:
    import cv2

    selected_candidate_ids = selected_candidate_ids or set()
    for candidate in candidates:
        candidate_id = int(candidate.candidate_id)
        x = int(round(float(candidate.point_xy[0])))
        y = int(round(float(candidate.point_xy[1])))
        is_selected = candidate_id in selected_candidate_ids
        ring_color = (0, 255, 0) if is_selected else (255, 220, 0)
        fill_color = (0, 0, 255) if is_selected else (40, 40, 40)
        cv2.circle(image_bgr, (x, y), 10, ring_color, 2, cv2.LINE_AA)
        cv2.circle(image_bgr, (x, y), 8, fill_color, -1, cv2.LINE_AA)
        cv2.putText(
            image_bgr,
            str(candidate_id),
            (x - 7, y + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            ring_color,
            2,
            cv2.LINE_AA,
        )
