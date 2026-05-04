from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
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


@dataclass
class _LiveStreamMetadataCache:
    root_path: Path
    stream_path: Path
    metadata_stream_path: Path
    media_samples_path: Path
    session_start_path: Path
    byte_offset: int = 0
    pending_text: str = ""
    media_sample_byte_offset: int = 0
    media_sample_pending_text: str = ""
    session_start_payload: dict[str, Any] | None = None
    frame_metadata: list[dict[str, Any]] = field(default_factory=list)
    media_samples: list[dict[str, Any]] = field(default_factory=list)

    def refresh(self) -> None:
        if not self.metadata_stream_path.exists():
            raise RuntimeError(f"Live stream directory is missing metadata_stream.jsonl: {self.metadata_stream_path}")

        self._refresh_metadata_stream()
        self._refresh_media_samples()

    def _refresh_metadata_stream(self) -> None:
        current_size = self.metadata_stream_path.stat().st_size
        if current_size < self.byte_offset:
            self.byte_offset = 0
            self.pending_text = ""
            self.session_start_payload = None
            self.frame_metadata.clear()

        with self.metadata_stream_path.open("r", encoding="utf-8") as handle:
            handle.seek(self.byte_offset)
            chunk = handle.read()
            self.byte_offset = handle.tell()

        if not chunk:
            return

        text = self.pending_text + chunk
        self.pending_text = ""
        for line in text.splitlines(keepends=True):
            if not line.endswith(("\n", "\r")):
                self.pending_text = line
                continue
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            kind = row.get("kind")
            if kind == "session_start" and self.session_start_payload is None:
                self.session_start_payload = row
            elif kind == "frame_metadata":
                frame_payload = row.get("frame_metadata")
                if isinstance(frame_payload, dict):
                    self.frame_metadata.append(frame_payload)

    def _refresh_media_samples(self) -> None:
        if not self.media_samples_path.exists():
            self.media_sample_byte_offset = 0
            self.media_sample_pending_text = ""
            self.media_samples.clear()
            return

        current_size = self.media_samples_path.stat().st_size
        if current_size < self.media_sample_byte_offset:
            self.media_sample_byte_offset = 0
            self.media_sample_pending_text = ""
            self.media_samples.clear()

        with self.media_samples_path.open("r", encoding="utf-8") as handle:
            handle.seek(self.media_sample_byte_offset)
            chunk = handle.read()
            self.media_sample_byte_offset = handle.tell()

        if not chunk:
            return

        text = self.media_sample_pending_text + chunk
        self.media_sample_pending_text = ""
        for line in text.splitlines(keepends=True):
            if not line.endswith(("\n", "\r")):
                self.media_sample_pending_text = line
                continue
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                self.media_samples.append(row)


_LIVE_STREAM_METADATA_CACHE_LOCK = threading.RLock()
_LIVE_STREAM_METADATA_CACHE: dict[Path, _LiveStreamMetadataCache] = {}


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


def _int_or_none(value: Any) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(value)
    except Exception:
        return None


def _align_live_frame_metadata_to_media_samples(
    frame_metadata: list[dict[str, Any]],
    media_samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not media_samples:
        return list(frame_metadata), {
            "mode": "metadata_ordinal",
            "rawFrameMetadataCount": len(frame_metadata),
            "mediaSampleCount": 0,
            "missingMetadataForSamples": 0,
            "metadataWithoutMediaSamples": 0,
        }

    metadata_by_pts: dict[int, dict[str, Any]] = {}
    duplicate_metadata_pts = 0
    for metadata in frame_metadata:
        pts_us = _int_or_none(metadata.get("ptsUs"))
        if pts_us is None:
            continue
        if pts_us in metadata_by_pts:
            duplicate_metadata_pts += 1
            continue
        metadata_by_pts[pts_us] = metadata

    sample_pts_seen: set[int] = set()
    aligned: list[dict[str, Any]] = []
    missing_metadata_for_samples = 0
    for sample_index, sample in enumerate(media_samples):
        pts_us = _int_or_none(sample.get("pts_us"))
        if pts_us is None:
            pts_us = _int_or_none(sample.get("ptsUs"))

        metadata = metadata_by_pts.get(pts_us) if pts_us is not None else None
        if pts_us is not None:
            sample_pts_seen.add(pts_us)

        if metadata is None:
            missing_metadata_for_samples += 1
            aligned.append(
                {
                    "frameSeq": int(sample_index),
                    "ptsUs": int(pts_us or 0),
                    "_mediaSampleIndex": int(sample_index),
                    "_mediaSamplePtsUs": int(pts_us or 0),
                    "_mediaSampleMetadataMissing": True,
                }
            )
            continue

        aligned_metadata = dict(metadata)
        aligned_metadata["_mediaSampleIndex"] = int(sample_index)
        aligned_metadata["_mediaSamplePtsUs"] = int(pts_us or 0)
        aligned.append(aligned_metadata)

    metadata_without_samples = sum(
        1
        for metadata in frame_metadata
        if (_int_or_none(metadata.get("ptsUs")) is not None and _int_or_none(metadata.get("ptsUs")) not in sample_pts_seen)
    )
    return aligned, {
        "mode": "media_sample_pts",
        "rawFrameMetadataCount": len(frame_metadata),
        "mediaSampleCount": len(media_samples),
        "alignedFrameMetadataCount": len(aligned),
        "missingMetadataForSamples": int(missing_metadata_for_samples),
        "metadataWithoutMediaSamples": int(metadata_without_samples),
        "duplicateMetadataPts": int(duplicate_metadata_pts),
    }


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
    media_samples_path = (root_path / "media_samples.jsonl").resolve()
    session_start_path = (root_path / "session_start.json").resolve()
    if not stream_path.exists():
        raise RuntimeError(f"Live stream directory is missing stream.h264: {stream_path}")
    if not metadata_stream_path.exists():
        raise RuntimeError(f"Live stream directory is missing metadata_stream.jsonl: {metadata_stream_path}")

    with _LIVE_STREAM_METADATA_CACHE_LOCK:
        cache = _LIVE_STREAM_METADATA_CACHE.get(root_path)
        if (
            cache is None
            or cache.metadata_stream_path != metadata_stream_path
            or cache.media_samples_path != media_samples_path
        ):
            cache = _LiveStreamMetadataCache(
                root_path=root_path,
                stream_path=stream_path,
                metadata_stream_path=metadata_stream_path,
                media_samples_path=media_samples_path,
                session_start_path=session_start_path,
            )
            _LIVE_STREAM_METADATA_CACHE[root_path] = cache
        cache.refresh()
        if cache.session_start_payload is None:
            raise RuntimeError("Live stream metadata is missing a session_start payload.")
        session_start_payload = dict(cache.session_start_payload)
        raw_frame_metadata = list(cache.frame_metadata)
        media_samples = list(cache.media_samples)

    frame_metadata, alignment = _align_live_frame_metadata_to_media_samples(raw_frame_metadata, media_samples)

    session_metadata = session_start_payload.get("session_metadata") or _load_json(session_start_path)
    lane_lock_metadata = session_start_payload.get("lane_lock_metadata") or {}
    shot_metadata = session_start_payload.get("shot_metadata") or {}

    manifest = {
        "kind": "incoming_live_stream_v1",
        "mediaPath": "stream.h264",
        "metadataStreamPath": "metadata_stream.jsonl",
        "sessionStartPath": "session_start.json",
        "mediaSamplesPath": "media_samples.jsonl",
        "frameCount": len(frame_metadata),
        "frameMetadataAlignment": alignment,
    }

    video_info = _fallback_video_info_from_session(session_metadata, frame_metadata)

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
