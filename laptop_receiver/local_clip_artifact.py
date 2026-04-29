from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator

import cv2


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


def _resolve_artifact_path(root_dir: Path, manifest: dict[str, Any], manifest_key: str, default_name: str) -> Path:
    relative_path = manifest.get(manifest_key) or default_name
    return (root_dir / relative_path).resolve()


def _extract_live_stream_payloads(metadata_stream_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session_start_payload: dict[str, Any] | None = None
    frame_metadata_rows: list[dict[str, Any]] = []
    for row in metadata_stream_rows:
        kind = row.get("kind")
        if kind == "session_start" and session_start_payload is None:
            session_start_payload = row
            continue
        if kind == "frame_metadata":
            frame_payload = row.get("frame_metadata")
            if isinstance(frame_payload, dict):
                frame_metadata_rows.append(frame_payload)

    if session_start_payload is None:
        raise RuntimeError("Live stream metadata is missing a session_start payload.")
    return session_start_payload, frame_metadata_rows


def _fallback_video_info_from_session(
    session_metadata: dict[str, Any],
    frame_metadata: list[dict[str, Any]],
) -> VideoStreamInfo:
    width = int(session_metadata.get("actualWidth") or session_metadata.get("requestedWidth") or 0)
    height = int(session_metadata.get("actualHeight") or session_metadata.get("requestedHeight") or 0)
    fps = float(session_metadata.get("actualSourceFps") or session_metadata.get("requestedFps") or 0.0)
    frame_count = len(frame_metadata)
    duration_seconds = (frame_count / fps) if fps > 0.0 and frame_count > 0 else 0.0
    return VideoStreamInfo(
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=duration_seconds,
    )


@dataclass(frozen=True)
class VideoStreamInfo:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float


@dataclass(frozen=True)
class DecodedFrame:
    frame_index: int
    image_bgr: Any
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LocalClipArtifact:
    root_dir: Path
    manifest: dict[str, Any]
    session_metadata: dict[str, Any]
    lane_lock_metadata: dict[str, Any]
    shot_metadata: dict[str, Any]
    frame_metadata: list[dict[str, Any]]
    video_path: Path
    video_info: VideoStreamInfo

    @property
    def metadata_frame_count(self) -> int:
        return len(self.frame_metadata)

    def iter_frames(self, start_frame_index: int = 0) -> Iterator[DecodedFrame]:
        capture = cv2.VideoCapture(str(self.video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {self.video_path}")

        try:
            frame_index = max(int(start_frame_index), 0)
            if frame_index > 0:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                actual_position = int(capture.get(cv2.CAP_PROP_POS_FRAMES) or 0)
                if actual_position < frame_index:
                    while actual_position < frame_index:
                        ok = capture.grab()
                        if not ok:
                            return
                        actual_position += 1
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                metadata = self.frame_metadata[frame_index] if frame_index < len(self.frame_metadata) else {}
                yield DecodedFrame(frame_index=frame_index, image_bgr=frame, metadata=metadata)
                frame_index += 1
        finally:
            capture.release()


def probe_video(video_path: Path) -> VideoStreamInfo:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        raw_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_count = raw_frame_count if raw_frame_count >= 0 else 0
        duration_seconds = (frame_count / fps) if fps > 0.0 and frame_count > 0 else 0.0
        return VideoStreamInfo(
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            duration_seconds=duration_seconds,
        )
    finally:
        capture.release()


def load_local_clip_artifact(root_dir: Path | str) -> LocalClipArtifact:
    root_path = Path(root_dir).expanduser().resolve()
    manifest_path = root_path / "artifact_manifest.json"

    if not manifest_path.exists():
        return load_live_stream_artifact(root_path)

    manifest = _load_json(manifest_path)
    video_path = _resolve_artifact_path(root_path, manifest, "mediaPath", "video.mp4")
    session_metadata_path = _resolve_artifact_path(root_path, manifest, "sessionMetadataPath", "session_metadata.json")
    lane_lock_metadata_path = _resolve_artifact_path(root_path, manifest, "laneLockMetadataPath", "lane_lock_metadata.json")
    shot_metadata_path = _resolve_artifact_path(root_path, manifest, "shotMetadataPath", "shot_metadata.json")
    frame_metadata_path = _resolve_artifact_path(root_path, manifest, "frameMetadataPath", "frame_metadata.jsonl")

    artifact = LocalClipArtifact(
        root_dir=root_path,
        manifest=manifest,
        session_metadata=_load_json(session_metadata_path),
        lane_lock_metadata=_load_json(lane_lock_metadata_path),
        shot_metadata=_load_json(shot_metadata_path),
        frame_metadata=_load_jsonl(frame_metadata_path),
        video_path=video_path,
        video_info=probe_video(video_path),
    )
    return artifact


def load_live_stream_artifact(root_dir: Path | str) -> LocalClipArtifact:
    root_path = Path(root_dir).expanduser().resolve()
    stream_path = (root_path / "stream.h264").resolve()
    metadata_stream_path = (root_path / "metadata_stream.jsonl").resolve()
    session_start_path = (root_path / "session_start.json").resolve()
    if not stream_path.exists():
        raise RuntimeError(f"Live stream directory is missing stream.h264: {stream_path}")
    if not metadata_stream_path.exists():
        raise RuntimeError(f"Live stream directory is missing metadata_stream.jsonl: {metadata_stream_path}")

    metadata_stream_rows = _load_jsonl(metadata_stream_path)
    session_start_payload, frame_metadata = _extract_live_stream_payloads(metadata_stream_rows)
    session_metadata = session_start_payload.get("session_metadata") or _load_json(session_start_path)
    lane_lock_metadata = session_start_payload.get("lane_lock_metadata") or {}
    shot_metadata = session_start_payload.get("shot_metadata") or {}

    manifest = {
        "kind": "incoming_live_stream_v1",
        "mediaPath": "stream.h264",
        "metadataStreamPath": "metadata_stream.jsonl",
        "sessionStartPath": "session_start.json",
        "frameCount": len(frame_metadata),
    }

    fallback_video_info = _fallback_video_info_from_session(session_metadata, frame_metadata)
    try:
        probed_video_info = probe_video(stream_path)
    except Exception:
        probed_video_info = fallback_video_info

    probed_fps = float(probed_video_info.fps or 0.0)
    requested_fps = float(fallback_video_info.fps or 0.0)
    should_prefer_fallback = (
        probed_video_info.width <= 0
        or probed_video_info.height <= 0
        or probed_video_info.frame_count <= 0
        or requested_fps <= 0.0
        or abs(probed_fps - requested_fps) > 0.5
    )
    video_info = fallback_video_info if should_prefer_fallback else probed_video_info

    return LocalClipArtifact(
        root_dir=root_path,
        manifest=manifest,
        session_metadata=session_metadata,
        lane_lock_metadata=lane_lock_metadata,
        shot_metadata=shot_metadata,
        frame_metadata=frame_metadata,
        video_path=stream_path,
        video_info=video_info,
    )
