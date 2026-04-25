from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np

from laptop_receiver.local_clip_artifact import LocalClipArtifact


@dataclass(frozen=True)
class LaneSupportSegment:
    frame_seq: int
    frame_index: int
    line_xyxy: tuple[int, int, int, int]
    length_px: float
    angle_deg: float
    midpoint_x: float
    midpoint_y: float
    orientation_group: str
    support_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _segment_angle_deg(x1: int, y1: int, x2: int, y2: int) -> float:
    return float(np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1))))


def _segment_length_px(x1: int, y1: int, x2: int, y2: int) -> float:
    return float(np.hypot(float(x2 - x1), float(y2 - y1)))


def _region_of_interest_mask(height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.uint8)
    polygon = np.array(
        [
            [int(width * 0.03), height - 1],
            [int(width * 0.20), int(height * 0.30)],
            [int(width * 0.80), int(height * 0.30)],
            [int(width * 0.97), height - 1],
        ],
        dtype=np.int32,
    )
    cv2.fillConvexPoly(mask, polygon, 255)
    return mask


def _classify_orientation(angle_deg: float) -> str:
    if angle_deg <= -18.0:
        return "left"
    if angle_deg >= 18.0:
        return "right"
    return "horizontal"


def _support_score(
    *,
    length_px: float,
    midpoint_x: float,
    midpoint_y: float,
    width: int,
    height: int,
    orientation_group: str,
) -> float:
    lower_frame_bonus = midpoint_y / max(float(height), 1.0)
    centered_bonus = 1.0 - min(abs(midpoint_x - (float(width) * 0.5)) / max(float(width) * 0.5, 1.0), 1.0)

    if orientation_group == "horizontal":
        return float(length_px * (0.45 + 0.45 * lower_frame_bonus + 0.10 * centered_bonus))
    return float(length_px * (0.55 + 0.25 * lower_frame_bonus + 0.20 * centered_bonus))


def extract_lane_support_segments(
    image_bgr: Any,
    frame_seq: int,
    frame_index: int,
    min_length_px: float = 60.0,
    max_segments: int = 36,
) -> list[LaneSupportSegment]:
    image = np.asarray(image_bgr)
    height, width = image.shape[:2]

    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)

    roi_mask = _region_of_interest_mask(height, width)
    masked_edges = cv2.bitwise_and(edges, roi_mask)

    raw_lines = cv2.HoughLinesP(
        masked_edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=40,
        minLineLength=int(min_length_px),
        maxLineGap=20,
    )
    if raw_lines is None:
        return []

    segments: list[LaneSupportSegment] = []
    for raw_line in raw_lines:
        x1, y1, x2, y2 = (int(value) for value in raw_line[0])
        length_px = _segment_length_px(x1, y1, x2, y2)
        if length_px < float(min_length_px):
            continue

        angle_deg = _segment_angle_deg(x1, y1, x2, y2)
        midpoint_x = (float(x1) + float(x2)) * 0.5
        midpoint_y = (float(y1) + float(y2)) * 0.5
        orientation_group = _classify_orientation(angle_deg)
        support_score = _support_score(
            length_px=length_px,
            midpoint_x=midpoint_x,
            midpoint_y=midpoint_y,
            width=width,
            height=height,
            orientation_group=orientation_group,
        )

        segments.append(
            LaneSupportSegment(
                frame_seq=int(frame_seq),
                frame_index=int(frame_index),
                line_xyxy=(x1, y1, x2, y2),
                length_px=length_px,
                angle_deg=angle_deg,
                midpoint_x=midpoint_x,
                midpoint_y=midpoint_y,
                orientation_group=orientation_group,
                support_score=support_score,
            )
        )

    segments.sort(key=lambda segment: segment.support_score, reverse=True)
    return segments[: int(max_segments)]


def extract_lane_support_from_artifact(
    artifact: LocalClipArtifact,
    frame_seq_start: int,
    frame_seq_end: int,
    min_length_px: float = 60.0,
    max_segments_per_frame: int = 36,
) -> list[LaneSupportSegment]:
    support_segments: list[LaneSupportSegment] = []
    for decoded_frame in artifact.iter_frames():
        frame_metadata = decoded_frame.metadata or {}
        frame_seq = int(frame_metadata.get("frameSeq", decoded_frame.frame_index))
        if frame_seq < int(frame_seq_start) or frame_seq > int(frame_seq_end):
            continue
        support_segments.extend(
            extract_lane_support_segments(
                decoded_frame.image_bgr,
                frame_seq=frame_seq,
                frame_index=decoded_frame.frame_index,
                min_length_px=min_length_px,
                max_segments=max_segments_per_frame,
            )
        )
    return support_segments
