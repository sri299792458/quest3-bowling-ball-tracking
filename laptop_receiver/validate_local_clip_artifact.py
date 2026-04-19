from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import cv2

from laptop_receiver.local_clip_artifact import LocalClipArtifact, load_local_clip_artifact


FRAME_REQUIRED_KEYS = (
    "frameSeq",
    "cameraTimestampUs",
    "ptsUs",
    "isKeyframe",
    "width",
    "height",
    "cameraPosition",
    "cameraRotation",
    "headPosition",
    "headRotation",
    "laneLockState",
)


@dataclass(frozen=True)
class LocalClipValidationReport:
    artifact_dir: str
    video_width: int
    video_height: int
    video_fps: float
    probed_video_frame_count: int
    decoded_video_frame_count: int
    metadata_frame_count: int
    first_camera_timestamp_us: int | None
    last_camera_timestamp_us: int | None
    first_pts_us: int | None
    last_pts_us: int | None
    pts_camera_offset_min_us: int | None
    pts_camera_offset_max_us: int | None
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _decode_video_frame_count(video_path: Path) -> int:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video for validation: {video_path}")

    frame_count = 0
    try:
        while True:
            ok, _frame = capture.read()
            if not ok:
                break
            frame_count += 1
    finally:
        capture.release()

    return frame_count


def _expect_keys(record: dict[str, Any], required_keys: tuple[str, ...], record_name: str, errors: list[str]) -> None:
    missing = [key for key in required_keys if key not in record]
    if missing:
        errors.append(f"{record_name} is missing required keys: {', '.join(missing)}")


def _expect_vector(record: dict[str, Any], key: str, record_name: str, errors: list[str]) -> None:
    value = record.get(key)
    if not isinstance(value, dict) or not {"x", "y", "z"}.issubset(value.keys()):
        errors.append(f"{record_name}.{key} must be a Unity-style Vector3 object")


def _expect_quaternion(record: dict[str, Any], key: str, record_name: str, errors: list[str]) -> None:
    value = record.get(key)
    if not isinstance(value, dict) or not {"x", "y", "z", "w"}.issubset(value.keys()):
        errors.append(f"{record_name}.{key} must be a Unity-style Quaternion object")


def validate_local_clip_artifact(artifact_dir: Path | str) -> LocalClipValidationReport:
    artifact = load_local_clip_artifact(artifact_dir)
    errors: list[str] = []
    warnings: list[str] = []

    manifest = artifact.manifest
    session_metadata = artifact.session_metadata
    lane_lock_metadata = artifact.lane_lock_metadata
    shot_metadata = artifact.shot_metadata
    frame_metadata = artifact.frame_metadata

    if manifest.get("schemaVersion") != "local_clip_artifact_v1":
        warnings.append(
            f"artifact_manifest schemaVersion is {manifest.get('schemaVersion')!r}, expected 'local_clip_artifact_v1'"
        )

    for name, record in (
        ("session_metadata", session_metadata),
        ("lane_lock_metadata", lane_lock_metadata),
        ("shot_metadata", shot_metadata),
    ):
        if record.get("schemaVersion") != "capture_metadata_v1":
            warnings.append(
                f"{name} schemaVersion is {record.get('schemaVersion')!r}, expected 'capture_metadata_v1'"
            )

    if not frame_metadata:
        errors.append("frame_metadata.jsonl is empty")
    else:
        offsets: list[int] = []
        previous_frame_seq: int | None = None
        previous_camera_timestamp_us: int | None = None
        previous_pts_us: int | None = None
        first_camera_timestamp_us: int | None = None

        for frame_index, record in enumerate(frame_metadata):
            record_name = f"frame_metadata[{frame_index}]"
            error_count_before_record = len(errors)
            _expect_keys(record, FRAME_REQUIRED_KEYS, record_name, errors)
            if len(errors) != error_count_before_record:
                continue

            _expect_vector(record, "cameraPosition", record_name, errors)
            _expect_vector(record, "headPosition", record_name, errors)
            _expect_quaternion(record, "cameraRotation", record_name, errors)
            _expect_quaternion(record, "headRotation", record_name, errors)
            if len(errors) != error_count_before_record:
                continue

            frame_seq = int(record["frameSeq"])
            camera_timestamp_us = int(record["cameraTimestampUs"])
            pts_us = int(record["ptsUs"])
            width = int(record["width"])
            height = int(record["height"])
            if first_camera_timestamp_us is None:
                first_camera_timestamp_us = camera_timestamp_us

            if previous_frame_seq is not None and frame_seq != previous_frame_seq + 1:
                errors.append(
                    f"{record_name}.frameSeq is {frame_seq}, expected {previous_frame_seq + 1}"
                )
            if previous_camera_timestamp_us is not None and camera_timestamp_us <= previous_camera_timestamp_us:
                errors.append(
                    f"{record_name}.cameraTimestampUs must increase monotonically"
                )
            if previous_pts_us is not None and pts_us <= previous_pts_us:
                errors.append(f"{record_name}.ptsUs must increase monotonically")

            if width != artifact.video_info.width or height != artifact.video_info.height:
                errors.append(
                    f"{record_name} dimensions {width}x{height} do not match probed video "
                    f"{artifact.video_info.width}x{artifact.video_info.height}"
                )

            offsets.append(pts_us - (camera_timestamp_us - first_camera_timestamp_us))
            previous_frame_seq = frame_seq
            previous_camera_timestamp_us = camera_timestamp_us
            previous_pts_us = pts_us

        offset_spread = (max(offsets) - min(offsets)) if offsets else None
        if offset_spread is not None and offset_spread > 1_000:
            errors.append(
                f"ptsUs vs cameraTimestampUs offset varies by {offset_spread} us, expected a stable join"
            )

    decoded_video_frame_count = _decode_video_frame_count(artifact.video_path)
    metadata_frame_count = artifact.metadata_frame_count
    probed_video_frame_count = artifact.video_info.frame_count

    if decoded_video_frame_count != metadata_frame_count:
        errors.append(
            f"decoded video frame count ({decoded_video_frame_count}) does not match metadata frame count ({metadata_frame_count})"
        )

    if probed_video_frame_count and probed_video_frame_count != decoded_video_frame_count:
        warnings.append(
            f"container-reported frame count ({probed_video_frame_count}) differs from decoded count ({decoded_video_frame_count})"
        )

    if frame_metadata:
        first_camera_timestamp_us = int(frame_metadata[0]["cameraTimestampUs"])
        last_camera_timestamp_us = int(frame_metadata[-1]["cameraTimestampUs"])
        first_pts_us = int(frame_metadata[0]["ptsUs"])
        last_pts_us = int(frame_metadata[-1]["ptsUs"])
        offsets = [
            int(record["ptsUs"]) - (int(record["cameraTimestampUs"]) - first_camera_timestamp_us)
            for record in frame_metadata
        ]
        pts_camera_offset_min_us = min(offsets)
        pts_camera_offset_max_us = max(offsets)
    else:
        first_camera_timestamp_us = None
        last_camera_timestamp_us = None
        first_pts_us = None
        last_pts_us = None
        pts_camera_offset_min_us = None
        pts_camera_offset_max_us = None

    if frame_metadata:
        shot_start_time_us = int(shot_metadata.get("shotStartTimeUs", 0))
        shot_end_time_us = int(shot_metadata.get("shotEndTimeUs", 0))
        if not (first_camera_timestamp_us <= shot_start_time_us <= shot_end_time_us <= last_camera_timestamp_us):
            errors.append(
                "shot_metadata time span must fall inside the available frame metadata time span"
            )

    requested_width = int(session_metadata.get("requestedWidth", 0) or 0)
    requested_height = int(session_metadata.get("requestedHeight", 0) or 0)
    if requested_width and requested_height:
        if artifact.video_info.width != requested_width or artifact.video_info.height != requested_height:
            warnings.append(
                f"video dimensions {artifact.video_info.width}x{artifact.video_info.height} differ from "
                f"requested session dimensions {requested_width}x{requested_height}"
            )

    if "laneLockState" not in lane_lock_metadata:
        warnings.append("lane_lock_metadata.json does not include laneLockState")

    return LocalClipValidationReport(
        artifact_dir=str(artifact.root_dir),
        video_width=artifact.video_info.width,
        video_height=artifact.video_info.height,
        video_fps=artifact.video_info.fps,
        probed_video_frame_count=probed_video_frame_count,
        decoded_video_frame_count=decoded_video_frame_count,
        metadata_frame_count=metadata_frame_count,
        first_camera_timestamp_us=first_camera_timestamp_us,
        last_camera_timestamp_us=last_camera_timestamp_us,
        first_pts_us=first_pts_us,
        last_pts_us=last_pts_us,
        pts_camera_offset_min_us=pts_camera_offset_min_us,
        pts_camera_offset_max_us=pts_camera_offset_max_us,
        errors=errors,
        warnings=warnings,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a standalone Quest local clip artifact (video.mp4 + metadata sidecars)."
    )
    parser.add_argument("artifact_dir", type=Path, help="Path to the clip_<session>_<shot> artifact directory")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the validation report as JSON instead of plain text.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()
    report = validate_local_clip_artifact(args.artifact_dir)

    if args.emit_json:
        print(json.dumps(asdict(report), indent=2))
    else:
        status = "PASS" if report.ok else "FAIL"
        print(f"[{status}] {report.artifact_dir}")
        print(
            f"video: {report.video_width}x{report.video_height} @ {report.video_fps:.2f} fps | "
            f"decoded_frames={report.decoded_video_frame_count} | metadata_frames={report.metadata_frame_count}"
        )
        print(
            f"timestamps: camera=[{report.first_camera_timestamp_us}, {report.last_camera_timestamp_us}] | "
            f"pts=[{report.first_pts_us}, {report.last_pts_us}] | "
            f"offset_us=[{report.pts_camera_offset_min_us}, {report.pts_camera_offset_max_us}]"
        )

        for warning in report.warnings:
            print(f"warning: {warning}")
        for error in report.errors:
            print(f"error: {error}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
