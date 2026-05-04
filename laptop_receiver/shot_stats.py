from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from laptop_receiver.lane_lock_types import LaneLockResult, LaneSpaceBallPoint


SHOT_STATS_SCHEMA_VERSION = "shot_stats_v1"
SHOT_STATS_POINT_DEFINITION = "lane_space_trajectory_stats_v1"

BOARD_COUNT = 39
METERS_TO_FEET = 3.280839895013123
MPS_TO_MPH = 2.2369362920544
ARROWS_DISTANCE_FEET = 15.0
ENTRY_BOARD_DISTANCE_FEET = 59.5
ENTRY_SPEED_START_FEET = 57.0
EARLY_SPEED_DISTANCE_FEET = 3.0
EARLY_ANGLE_DISTANCE_FEET = 10.0
MIN_STATS_PROJECTION_CONFIDENCE = 0.20
STATS_LATERAL_MARGIN_METERS = 0.10
STATS_DOWNLANE_MARGIN_METERS = 0.25


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        value_float = float(value)
        return value_float if math.isfinite(value_float) else float(default)
    except Exception:
        return float(default)


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return bool(value)


@dataclass(frozen=True)
class TrajectoryCoverageStats:
    start_s_feet: float
    end_s_feet: float
    tracked_distance_feet: float
    coverage_confidence: float

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TrajectoryCoverageStats":
        source = payload or {}
        return cls(
            start_s_feet=_float(source.get("startSFeet")),
            end_s_feet=_float(source.get("endSFeet")),
            tracked_distance_feet=_float(source.get("trackedDistanceFeet")),
            coverage_confidence=_float(source.get("coverageConfidence")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "startSFeet": self.start_s_feet,
            "endSFeet": self.end_s_feet,
            "trackedDistanceFeet": self.tracked_distance_feet,
            "coverageConfidence": self.coverage_confidence,
        }


@dataclass(frozen=True)
class ShotSpeedStats:
    average_mph: float
    early_mph: float
    entry_mph: float
    speed_loss_mph: float
    has_average_speed: bool
    has_early_speed: bool
    has_entry_speed: bool
    has_speed_loss: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShotSpeedStats":
        source = payload or {}
        return cls(
            average_mph=_float(source.get("averageMph")),
            early_mph=_float(source.get("earlyMph")),
            entry_mph=_float(source.get("entryMph")),
            speed_loss_mph=_float(source.get("speedLossMph")),
            has_average_speed=_bool(source.get("hasAverageSpeed")),
            has_early_speed=_bool(source.get("hasEarlySpeed")),
            has_entry_speed=_bool(source.get("hasEntrySpeed")),
            has_speed_loss=_bool(source.get("hasSpeedLoss")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "averageMph": self.average_mph,
            "earlyMph": self.early_mph,
            "entryMph": self.entry_mph,
            "speedLossMph": self.speed_loss_mph,
            "hasAverageSpeed": self.has_average_speed,
            "hasEarlySpeed": self.has_early_speed,
            "hasEntrySpeed": self.has_entry_speed,
            "hasSpeedLoss": self.has_speed_loss,
        }


@dataclass(frozen=True)
class ShotPositionStats:
    arrows_board: float
    breakpoint_board: float
    breakpoint_distance_feet: float
    entry_board: float
    boards_crossed: float
    has_arrows_board: bool
    has_breakpoint: bool
    has_entry_board: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShotPositionStats":
        source = payload or {}
        return cls(
            arrows_board=_float(source.get("arrowsBoard")),
            breakpoint_board=_float(source.get("breakpointBoard")),
            breakpoint_distance_feet=_float(source.get("breakpointDistanceFeet")),
            entry_board=_float(source.get("entryBoard")),
            boards_crossed=_float(source.get("boardsCrossed")),
            has_arrows_board=_bool(source.get("hasArrowsBoard")),
            has_breakpoint=_bool(source.get("hasBreakpoint")),
            has_entry_board=_bool(source.get("hasEntryBoard")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "arrowsBoard": self.arrows_board,
            "breakpointBoard": self.breakpoint_board,
            "breakpointDistanceFeet": self.breakpoint_distance_feet,
            "entryBoard": self.entry_board,
            "boardsCrossed": self.boards_crossed,
            "hasArrowsBoard": self.has_arrows_board,
            "hasBreakpoint": self.has_breakpoint,
            "hasEntryBoard": self.has_entry_board,
        }


@dataclass(frozen=True)
class ShotAngleStats:
    launch_angle_degrees: float
    entry_angle_degrees: float
    signed_entry_angle_degrees: float
    breakpoint_angle_degrees: float
    has_launch_angle: bool
    has_entry_angle: bool
    has_breakpoint_angle: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShotAngleStats":
        source = payload or {}
        return cls(
            launch_angle_degrees=_float(source.get("launchAngleDegrees")),
            entry_angle_degrees=_float(source.get("entryAngleDegrees")),
            signed_entry_angle_degrees=_float(source.get("signedEntryAngleDegrees")),
            breakpoint_angle_degrees=_float(source.get("breakpointAngleDegrees")),
            has_launch_angle=_bool(source.get("hasLaunchAngle")),
            has_entry_angle=_bool(source.get("hasEntryAngle")),
            has_breakpoint_angle=_bool(source.get("hasBreakpointAngle")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "launchAngleDegrees": self.launch_angle_degrees,
            "entryAngleDegrees": self.entry_angle_degrees,
            "signedEntryAngleDegrees": self.signed_entry_angle_degrees,
            "breakpointAngleDegrees": self.breakpoint_angle_degrees,
            "hasLaunchAngle": self.has_launch_angle,
            "hasEntryAngle": self.has_entry_angle,
            "hasBreakpointAngle": self.has_breakpoint_angle,
        }


@dataclass(frozen=True)
class ShotStatMilestone:
    kind: str
    label: str
    frame_seq: int
    s_meters: float
    x_meters: float
    board: float
    distance_feet: float
    normalized_replay_time: float
    primary_value: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShotStatMilestone":
        source = payload or {}
        return cls(
            kind=str(source.get("kind") or ""),
            label=str(source.get("label") or ""),
            frame_seq=int(_float(source.get("frameSeq"))),
            s_meters=_float(source.get("sMeters")),
            x_meters=_float(source.get("xMeters")),
            board=_float(source.get("board")),
            distance_feet=_float(source.get("distanceFeet")),
            normalized_replay_time=max(0.0, min(1.0, _float(source.get("normalizedReplayTime")))),
            primary_value=str(source.get("primaryValue") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "frameSeq": self.frame_seq,
            "sMeters": self.s_meters,
            "xMeters": self.x_meters,
            "board": self.board,
            "distanceFeet": self.distance_feet,
            "normalizedReplayTime": self.normalized_replay_time,
            "primaryValue": self.primary_value,
        }


@dataclass(frozen=True)
class ShotStats:
    schema_version: str
    point_definition: str
    lane_length_meters: float
    lane_width_meters: float
    board_count: int
    trajectory_coverage: TrajectoryCoverageStats
    speed: ShotSpeedStats
    positions: ShotPositionStats
    angles: ShotAngleStats
    milestones: list[ShotStatMilestone]

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ShotStats":
        source = payload or {}
        schema_version = str(source.get("schemaVersion") or "")
        if schema_version != SHOT_STATS_SCHEMA_VERSION:
            raise ValueError(f"Unsupported shot_stats schemaVersion {schema_version!r}.")
        return cls(
            schema_version=schema_version,
            point_definition=str(source.get("pointDefinition") or ""),
            lane_length_meters=_float(source.get("laneLengthMeters")),
            lane_width_meters=_float(source.get("laneWidthMeters")),
            board_count=int(_float(source.get("boardCount"), BOARD_COUNT)),
            trajectory_coverage=TrajectoryCoverageStats.from_dict(source.get("trajectoryCoverage")),
            speed=ShotSpeedStats.from_dict(source.get("speed")),
            positions=ShotPositionStats.from_dict(source.get("positions")),
            angles=ShotAngleStats.from_dict(source.get("angles")),
            milestones=[
                ShotStatMilestone.from_dict(item)
                for item in (source.get("milestones") or [])
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "pointDefinition": self.point_definition,
            "laneLengthMeters": self.lane_length_meters,
            "laneWidthMeters": self.lane_width_meters,
            "boardCount": self.board_count,
            "trajectoryCoverage": self.trajectory_coverage.to_dict(),
            "speed": self.speed.to_dict(),
            "positions": self.positions.to_dict(),
            "angles": self.angles.to_dict(),
            "milestones": [milestone.to_dict() for milestone in self.milestones],
        }


@dataclass(frozen=True)
class _Sample:
    point: LaneSpaceBallPoint
    x: float
    s: float
    t: float
    index: float


def _ordered_samples(trajectory: Sequence[LaneSpaceBallPoint]) -> list[_Sample]:
    ordered = sorted(trajectory, key=lambda point: (int(point.frame_seq), int(point.pts_us)))
    if not ordered:
        return []
    pts_values = [float(point.pts_us) for point in ordered]
    use_pts = max(pts_values) > min(pts_values)
    samples: list[_Sample] = []
    t0 = pts_values[0] if use_pts else float(ordered[0].frame_seq) / 30.0
    for index, point in enumerate(ordered):
        timestamp = float(point.pts_us) if use_pts else float(point.frame_seq) / 30.0
        samples.append(
            _Sample(
                point=point,
                x=float(point.lane_point.x_meters),
                s=float(point.lane_point.s_meters),
                t=(timestamp - t0) / (1_000_000.0 if use_pts else 1.0),
                index=float(index),
            )
        )
    return samples


def _finite(*values: float) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _is_valid_stat_sample(sample: _Sample, lane_lock: LaneLockResult) -> bool:
    point = sample.point
    if point.lane_point is None:
        return False
    if not bool(point.is_on_locked_lane):
        return False
    if float(point.projection_confidence) < MIN_STATS_PROJECTION_CONFIDENCE:
        return False
    if not _finite(float(sample.x), float(sample.s), float(sample.t)):
        return False

    lane_width = max(float(lane_lock.lane_width_meters), 0.01)
    lane_length = max(float(lane_lock.lane_length_meters), 0.01)
    if abs(float(sample.x)) > lane_width * 0.5 + STATS_LATERAL_MARGIN_METERS:
        return False
    if float(sample.s) < -STATS_DOWNLANE_MARGIN_METERS:
        return False
    if float(sample.s) > lane_length + STATS_DOWNLANE_MARGIN_METERS:
        return False
    return True


def _valid_stat_samples(samples: Sequence[_Sample], lane_lock: LaneLockResult) -> list[_Sample]:
    return [sample for sample in samples if _is_valid_stat_sample(sample, lane_lock)]


def _board_from_x(x_meters: float, lane_width_meters: float, board_count: int = BOARD_COUNT) -> float:
    board_width = max(float(lane_width_meters) / float(board_count), 1e-9)
    return ((float(lane_width_meters) * 0.5 - float(x_meters)) / board_width) + 0.5


def _normalized_time(index: float, count: int) -> float:
    if count <= 1:
        return 0.0
    return max(0.0, min(1.0, float(index) / float(count - 1)))


def _normalized_sample_time(sample: _Sample, samples: Sequence[_Sample]) -> float:
    if len(samples) <= 1:
        return 0.0
    start_t = float(samples[0].t)
    end_t = float(samples[-1].t)
    if end_t > start_t + 1e-4:
        return max(0.0, min(1.0, (float(sample.t) - start_t) / (end_t - start_t)))
    return _normalized_time(sample.index, len(samples))


def _interpolate_at_s(samples: Sequence[_Sample], target_s: float) -> _Sample | None:
    if not samples:
        return None
    target = float(target_s)
    if target < float(samples[0].s) or target > float(samples[-1].s):
        return None
    for index in range(len(samples) - 1):
        a = samples[index]
        b = samples[index + 1]
        if float(a.s) <= target <= float(b.s):
            span = float(b.s) - float(a.s)
            ratio = 0.0 if abs(span) <= 1e-9 else (target - float(a.s)) / span
            return _Sample(
                point=a.point if ratio < 0.5 else b.point,
                x=float(a.x) + (float(b.x) - float(a.x)) * ratio,
                s=target,
                t=float(a.t) + (float(b.t) - float(a.t)) * ratio,
                index=float(a.index) + (float(b.index) - float(a.index)) * ratio,
            )
    last = samples[-1]
    if abs(float(last.s) - target) <= 1e-6:
        return last
    return None


def _path_distance_meters(samples: Sequence[_Sample]) -> float:
    if len(samples) < 2:
        return 0.0
    total = 0.0
    for index in range(len(samples) - 1):
        dx = float(samples[index + 1].x) - float(samples[index].x)
        ds = float(samples[index + 1].s) - float(samples[index].s)
        total += math.hypot(dx, ds)
    return total


def _trim_repeated_image_tail(samples: Sequence[_Sample]) -> list[_Sample]:
    if len(samples) < 3:
        return list(samples)

    last = samples[-1]
    suffix_start = len(samples) - 1
    for index in range(len(samples) - 2, -1, -1):
        point = samples[index].point.image_point_px
        dx = abs(float(point.x) - float(last.point.image_point_px.x))
        dy = abs(float(point.y) - float(last.point.image_point_px.y))
        if dx > 0.01 or dy > 0.01:
            break
        suffix_start = index

    repeated_count = len(samples) - suffix_start
    if repeated_count <= 2:
        return list(samples)
    return list(samples[: suffix_start + 1])


def _trim_after_lane_length(samples: Sequence[_Sample], lane_length_meters: float) -> list[_Sample]:
    if not samples:
        return []
    trimmed: list[_Sample] = []
    lane_length = float(lane_length_meters)
    for sample in samples:
        trimmed.append(sample)
        if float(sample.s) >= lane_length - 0.001:
            break
    return trimmed


def _speed_mph(samples: Sequence[_Sample]) -> float | None:
    if len(samples) < 2:
        return None
    dt = float(samples[-1].t) - float(samples[0].t)
    if dt <= 1e-4:
        return None
    # Ball speed should be the downlane speed. Using full 2D arc length here
    # lets small lateral/projection wiggle inflate the number enough to look
    # like km/h while being labelled mph.
    downlane_distance = max(0.0, float(samples[-1].s) - float(samples[0].s))
    if downlane_distance <= 1e-6:
        return None
    return (downlane_distance / dt) * MPS_TO_MPH


def _slice_between_s(samples: Sequence[_Sample], start_s: float, end_s: float) -> list[_Sample]:
    if not samples or end_s <= start_s:
        return []
    start = _interpolate_at_s(samples, start_s)
    end = _interpolate_at_s(samples, end_s)
    if start is None or end is None:
        return []
    sliced = [start]
    sliced.extend(sample for sample in samples if start_s < float(sample.s) < end_s)
    sliced.append(end)
    return sorted(sliced, key=lambda sample: sample.s)


def _angle_degrees(a: _Sample | None, b: _Sample | None) -> float | None:
    if a is None or b is None:
        return None
    ds = float(b.s) - float(a.s)
    if abs(ds) <= 1e-6:
        return None
    dx = float(b.x) - float(a.x)
    return math.degrees(math.atan2(dx, ds))


def _format_mph(value: float | None) -> str:
    return "--" if value is None else f"{value:.1f} mph"


def _format_board(value: float | None) -> str:
    return "--" if value is None else f"{value:.1f}"


def build_shot_stats(
    *,
    trajectory: Sequence[LaneSpaceBallPoint],
    lane_lock: LaneLockResult,
) -> ShotStats:
    samples = _valid_stat_samples(_ordered_samples(trajectory), lane_lock)
    if len(samples) < 2:
        raise RuntimeError("Cannot compute shot stats from fewer than two valid trajectory points.")

    lane_width = float(lane_lock.lane_width_meters)
    lane_length = float(lane_lock.lane_length_meters)
    shape_samples = _trim_after_lane_length(samples, lane_length)
    speed_samples = _trim_after_lane_length(_trim_repeated_image_tail(samples), lane_length)
    if len(shape_samples) < 2:
        shape_samples = samples
    if len(speed_samples) < 2:
        speed_samples = shape_samples

    start_s = float(samples[0].s)
    end_s = float(samples[-1].s)
    tracked_distance = _path_distance_meters(samples)
    confidence_values = [max(0.0, min(1.0, float(sample.point.projection_confidence))) for sample in samples]
    coverage_fraction = max(0.0, min(1.0, (end_s - start_s) / max(lane_length, 1e-6)))
    confidence_mean = sum(confidence_values) / len(confidence_values)
    coverage_confidence = max(0.0, min(1.0, 0.65 * confidence_mean + 0.35 * coverage_fraction))

    average_mph = _speed_mph(speed_samples)
    speed_start_s = float(speed_samples[0].s)
    speed_end_s = float(speed_samples[-1].s)
    early_end_s = min(speed_end_s, speed_start_s + EARLY_SPEED_DISTANCE_FEET / METERS_TO_FEET)
    early_mph = (
        _speed_mph(_slice_between_s(speed_samples, speed_start_s, early_end_s))
        if early_end_s > speed_start_s
        else None
    )
    entry_start_s = ENTRY_SPEED_START_FEET / METERS_TO_FEET
    entry_end_s = ENTRY_BOARD_DISTANCE_FEET / METERS_TO_FEET
    entry_mph = _speed_mph(_slice_between_s(speed_samples, entry_start_s, entry_end_s))
    speed_loss_mph = (
        float(early_mph) - float(entry_mph)
        if early_mph is not None and entry_mph is not None
        else None
    )

    arrows = _interpolate_at_s(shape_samples, ARROWS_DISTANCE_FEET / METERS_TO_FEET)
    entry = _interpolate_at_s(shape_samples, ENTRY_BOARD_DISTANCE_FEET / METERS_TO_FEET)
    breakpoint = max(shape_samples, key=lambda sample: abs(float(sample.x)))

    arrows_board = _board_from_x(arrows.x, lane_width) if arrows is not None else None
    breakpoint_board = _board_from_x(breakpoint.x, lane_width)
    entry_board = _board_from_x(entry.x, lane_width) if entry is not None else None
    boards = [_board_from_x(sample.x, lane_width) for sample in shape_samples]
    boards_crossed = max(boards) - min(boards) if boards else 0.0

    launch_angle_start = shape_samples[0]
    launch_angle_end = _interpolate_at_s(
        shape_samples,
        min(float(shape_samples[-1].s), float(shape_samples[0].s) + EARLY_ANGLE_DISTANCE_FEET / METERS_TO_FEET),
    )
    launch_angle = _angle_degrees(launch_angle_start, launch_angle_end)
    entry_angle = _angle_degrees(
        _interpolate_at_s(shape_samples, ENTRY_SPEED_START_FEET / METERS_TO_FEET),
        entry,
    )
    breakpoint_angle = (
        abs(float(entry_angle) - float(launch_angle))
        if entry_angle is not None and launch_angle is not None
        else None
    )

    milestones: list[ShotStatMilestone] = []
    use_entry_speed = entry is not None and entry_mph is not None
    speed_sample = entry if use_entry_speed else samples[min(1, len(samples) - 1)]
    speed_value = entry_mph if use_entry_speed else average_mph
    if speed_value is not None:
        milestones.append(
            ShotStatMilestone(
                kind="entry_speed" if use_entry_speed else "average_speed",
                label="Speed",
                frame_seq=int(speed_sample.point.frame_seq),
                s_meters=float(speed_sample.s),
                x_meters=float(speed_sample.x),
                board=_board_from_x(speed_sample.x, lane_width),
                distance_feet=float(speed_sample.s) * METERS_TO_FEET,
                normalized_replay_time=_normalized_sample_time(speed_sample, samples),
                primary_value=_format_mph(speed_value),
            )
        )
    if arrows is not None and arrows_board is not None:
        milestones.append(
            ShotStatMilestone(
                kind="arrows",
                label="Arrows",
                frame_seq=int(arrows.point.frame_seq),
                s_meters=float(arrows.s),
                x_meters=float(arrows.x),
                board=arrows_board,
                distance_feet=ARROWS_DISTANCE_FEET,
                normalized_replay_time=_normalized_sample_time(arrows, samples),
                primary_value=_format_board(arrows_board),
            )
        )
    milestones.append(
        ShotStatMilestone(
            kind="breakpoint",
            label="Breakpoint",
            frame_seq=int(breakpoint.point.frame_seq),
            s_meters=float(breakpoint.s),
            x_meters=float(breakpoint.x),
            board=breakpoint_board,
            distance_feet=float(breakpoint.s) * METERS_TO_FEET,
            normalized_replay_time=_normalized_sample_time(breakpoint, samples),
            primary_value=f"{breakpoint_board:.1f} @ {float(breakpoint.s) * METERS_TO_FEET:.0f} ft",
        )
    )
    if entry is not None and entry_board is not None and entry_angle is not None:
        milestones.append(
            ShotStatMilestone(
                kind="entry",
                label="Entry",
                frame_seq=int(entry.point.frame_seq),
                s_meters=float(entry.s),
                x_meters=float(entry.x),
                board=entry_board,
                distance_feet=ENTRY_BOARD_DISTANCE_FEET,
                normalized_replay_time=_normalized_sample_time(entry, samples),
                primary_value=f"{entry_board:.1f} board, {abs(entry_angle):.1f} deg",
            )
        )
    display_speed_mph = entry_mph if entry_mph is not None else average_mph
    summary_parts = [_format_mph(display_speed_mph)]
    if entry_board is not None and entry_angle is not None:
        summary_parts.append(f"Entry {entry_board:.1f}, {abs(entry_angle):.1f} deg")
    else:
        summary_parts.append(f"Bkpt {breakpoint_board:.1f} @ {float(breakpoint.s) * METERS_TO_FEET:.0f} ft")

    milestones.append(
        ShotStatMilestone(
            kind="summary",
            label="Summary",
            frame_seq=int(samples[-1].point.frame_seq),
            s_meters=float(samples[-1].s),
            x_meters=float(samples[-1].x),
            board=_board_from_x(samples[-1].x, lane_width),
            distance_feet=float(samples[-1].s) * METERS_TO_FEET,
            normalized_replay_time=1.0,
            primary_value="\n".join(summary_parts),
        )
    )

    return ShotStats(
        schema_version=SHOT_STATS_SCHEMA_VERSION,
        point_definition=SHOT_STATS_POINT_DEFINITION,
        lane_length_meters=lane_length,
        lane_width_meters=lane_width,
        board_count=BOARD_COUNT,
        trajectory_coverage=TrajectoryCoverageStats(
            start_s_feet=start_s * METERS_TO_FEET,
            end_s_feet=end_s * METERS_TO_FEET,
            tracked_distance_feet=tracked_distance * METERS_TO_FEET,
            coverage_confidence=coverage_confidence,
        ),
        speed=ShotSpeedStats(
            average_mph=float(average_mph or 0.0),
            early_mph=float(early_mph or 0.0),
            entry_mph=float(entry_mph or 0.0),
            speed_loss_mph=float(speed_loss_mph or 0.0),
            has_average_speed=average_mph is not None,
            has_early_speed=early_mph is not None,
            has_entry_speed=entry_mph is not None,
            has_speed_loss=speed_loss_mph is not None,
        ),
        positions=ShotPositionStats(
            arrows_board=float(arrows_board or 0.0),
            breakpoint_board=float(breakpoint_board),
            breakpoint_distance_feet=float(breakpoint.s) * METERS_TO_FEET,
            entry_board=float(entry_board or 0.0),
            boards_crossed=float(boards_crossed),
            has_arrows_board=arrows_board is not None,
            has_breakpoint=True,
            has_entry_board=entry_board is not None,
        ),
        angles=ShotAngleStats(
            launch_angle_degrees=abs(float(launch_angle or 0.0)),
            entry_angle_degrees=abs(float(entry_angle or 0.0)),
            signed_entry_angle_degrees=float(entry_angle or 0.0),
            breakpoint_angle_degrees=float(breakpoint_angle or 0.0),
            has_launch_angle=launch_angle is not None,
            has_entry_angle=entry_angle is not None,
            has_breakpoint_angle=breakpoint_angle is not None,
        ),
        milestones=milestones,
    )
