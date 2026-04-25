from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2


DEFAULT_OUTPUT_ROOT = Path(r"C:\Users\student\QuestBowlingStandalone\data\imported_artifacts")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _vector3(values: list[float] | tuple[float, float, float] | None) -> dict[str, float]:
    source = list(values or [0.0, 0.0, 0.0])
    return {"x": float(source[0]), "y": float(source[1]), "z": float(source[2])}


def _quaternion(values: list[float] | tuple[float, float, float, float] | None) -> dict[str, float]:
    source = list(values or [0.0, 0.0, 0.0, 1.0])
    return {"x": float(source[0]), "y": float(source[1]), "z": float(source[2]), "w": float(source[3])}


def _camera_side_from_eye(camera_eye: Any) -> str:
    try:
        eye = int(camera_eye)
    except Exception:
        return "Unknown"
    if eye == 0:
        return "Left"
    if eye == 1:
        return "Right"
    return "Unknown"


def _legacy_run_root_paths(run_dir: Path) -> dict[str, Path]:
    raw_dir = run_dir / "raw"
    return {
        "raw_dir": raw_dir,
        "frames_dir": raw_dir / "frames",
        "manifest_path": raw_dir / "manifest.json",
        "frames_metadata_path": raw_dir / "frames.jsonl",
        "session_config_path": run_dir / "session_config.json",
    }


def _write_video_from_frames(frames_dir: Path, output_path: Path, fps: float, frame_width: int, frame_height: int) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(float(fps), 1.0),
        (int(frame_width), int(frame_height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {output_path}")

    frame_count = 0
    try:
        for image_path in sorted(frames_dir.glob("*.jpg"), key=lambda path: int(path.stem)):
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError(f"Could not read legacy frame: {image_path}")
            if image.shape[1] != frame_width or image.shape[0] != frame_height:
                raise RuntimeError(
                    f"Legacy frame {image_path.name} has unexpected size {image.shape[1]}x{image.shape[0]}, "
                    f"expected {frame_width}x{frame_height}"
                )
            writer.write(image)
            frame_count += 1
    finally:
        writer.release()

    return frame_count


def import_legacy_bowling_run(run_dir: Path | str, output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    source_run_dir = Path(run_dir).expanduser().resolve()
    output_root_path = Path(output_root).expanduser().resolve()
    paths = _legacy_run_root_paths(source_run_dir)

    manifest = _load_json(paths["manifest_path"])
    frame_rows = _load_jsonl(paths["frames_metadata_path"])
    session_config = _load_json(paths["session_config_path"])
    session_id = str(session_config.get("session_id") or source_run_dir.name.split("_shot_", 1)[0])
    shot_id = str(frame_rows[0].get("shot_id") or source_run_dir.name)
    artifact_dir = output_root_path / f"{source_run_dir.name}_standalone-artifact"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    frame_width = int(manifest.get("frame_width") or session_config.get("width") or 0)
    frame_height = int(manifest.get("frame_height") or session_config.get("height") or 0)
    fps = float(manifest.get("fps") or 30.0)
    first_timestamp_us = int(manifest.get("first_timestamp_us") or frame_rows[0]["timestamp_us"])

    video_path = artifact_dir / "video.mp4"
    video_frame_count = _write_video_from_frames(paths["frames_dir"], video_path, fps=fps, frame_width=frame_width, frame_height=frame_height)

    session_metadata = {
        "schemaVersion": "capture_metadata_v1",
        "sessionId": session_id,
        "deviceName": "Legacy Quest Capture Import",
        "cameraSide": _camera_side_from_eye(session_config.get("camera_eye")),
        "requestedWidth": int(session_config.get("width") or frame_width),
        "requestedHeight": int(session_config.get("height") or frame_height),
        "actualWidth": frame_width,
        "actualHeight": frame_height,
        "requestedFps": float(fps),
        "actualSourceFps": float(fps),
        "videoCodec": "legacy_mp4v_import",
        "targetBitrateKbps": 0,
        "fx": float(session_config.get("fx") or 0.0),
        "fy": float(session_config.get("fy") or 0.0),
        "cx": float(session_config.get("cx") or 0.0),
        "cy": float(session_config.get("cy") or 0.0),
        "sensorWidth": int(session_config.get("sensor_width") or frame_width),
        "sensorHeight": int(session_config.get("sensor_height") or frame_height),
        "lensOffsetPosition": _vector3(session_config.get("lens_position")),
        "lensOffsetRotation": _quaternion(session_config.get("lens_rotation")),
    }

    lane_lock_state = 0
    lane_lock_metadata = {
        "schemaVersion": "capture_metadata_v1",
        "laneLockState": lane_lock_state,
        "lockedAtUnixMs": 0,
        "confidence": 0.0,
        "note": "Legacy imports do not carry a real standalone lane lock result.",
    }

    frame_metadata_path = artifact_dir / "frame_metadata.jsonl"
    with frame_metadata_path.open("w", encoding="utf-8") as handle:
        for row in frame_rows:
            local_frame_idx = int(row["local_frame_idx"])
            camera_timestamp_us = int(row["timestamp_us"])
            frame_metadata = {
                "schemaVersion": "capture_metadata_v1",
                "frameSeq": local_frame_idx,
                "cameraTimestampUs": camera_timestamp_us,
                "ptsUs": camera_timestamp_us - first_timestamp_us,
                "isKeyframe": local_frame_idx == 0,
                "width": frame_width,
                "height": frame_height,
                "timestampSource": 2,
                "cameraPosition": _vector3(row.get("camera_position")),
                "cameraRotation": _quaternion(row.get("camera_rotation")),
                "headPosition": _vector3(row.get("head_position")),
                "headRotation": _quaternion(row.get("head_rotation")),
                "laneLockState": lane_lock_state,
            }
            handle.write(json.dumps(frame_metadata, separators=(",", ":")) + "\n")

    shot_metadata = {
        "schemaVersion": "capture_metadata_v1",
        "shotId": shot_id,
        "shotStartTimeUs": int(frame_rows[0]["timestamp_us"]),
        "shotEndTimeUs": int(frame_rows[-1]["timestamp_us"]),
        "preRollMs": 0,
        "postRollMs": 0,
        "triggerReason": "legacy_import",
        "laneLockStateAtShotStart": lane_lock_state,
    }

    artifact_manifest = {
        "schemaVersion": "local_clip_artifact_v1",
        "sessionId": session_id,
        "shotId": shot_id,
        "mediaPath": "video.mp4",
        "sessionMetadataPath": "session_metadata.json",
        "laneLockMetadataPath": "lane_lock_metadata.json",
        "frameMetadataPath": "frame_metadata.jsonl",
        "shotMetadataPath": "shot_metadata.json",
        "legacyImportSource": str(source_run_dir),
        "legacySourceFrameCount": int(len(frame_rows)),
        "legacyImportedVideoFrameCount": int(video_frame_count),
    }

    (artifact_dir / "artifact_manifest.json").write_text(json.dumps(artifact_manifest, indent=2), encoding="utf-8")
    (artifact_dir / "session_metadata.json").write_text(json.dumps(session_metadata, indent=2), encoding="utf-8")
    (artifact_dir / "lane_lock_metadata.json").write_text(json.dumps(lane_lock_metadata, indent=2), encoding="utf-8")
    (artifact_dir / "shot_metadata.json").write_text(json.dumps(shot_metadata, indent=2), encoding="utf-8")

    return artifact_dir


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package a legacy bowling_tests run into the standalone local clip artifact format.")
    parser.add_argument("run_dir", type=Path, help="Path to one legacy bowling_tests run directory")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()
    artifact_dir = import_legacy_bowling_run(args.run_dir, output_root=args.output_root)
    print(artifact_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
