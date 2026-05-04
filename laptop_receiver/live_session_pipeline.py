from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any

from laptop_receiver.laptop_result_types import (
    LaptopResultPublishError,
    build_pipeline_status_envelope,
    build_shot_result_envelope,
    publish_laptop_result,
)
from laptop_receiver.live_shot_boundary_detector import LiveShotBoundaryDetector, LiveShotBoundaryDetectorConfig
from laptop_receiver.live_shot_boundaries import load_shot_boundaries
from laptop_receiver.live_shot_tracking_stage import LiveShotTrackingStageConfig, run_live_shot_tracking_stage
from laptop_receiver.live_stream_receiver import DEFAULT_INCOMING_ROOT
from laptop_receiver.session_state import (
    LANE_CONFIRMED,
    SHOT_ANALYZING,
    SHOT_ARMED,
    SHOT_DISABLED_UNTIL_MEDIA_FRESH,
    SHOT_DISABLED_UNTIL_LANE_CONFIRMED,
    SHOT_OPEN,
    SHOT_RESULT_FAILED,
    SHOT_RESULT_READY,
    SHOT_START_CANDIDATE,
    SHOT_WINDOW_COMPLETE,
    TRANSPORT_DEGRADED,
    TRANSPORT_ENDED,
    load_session_state,
    mark_shot,
    mark_transport,
)


PIPELINE_STATE_SCHEMA_VERSION = "live_session_pipeline_state"
PUBLISH_FAILED_UNKNOWN_STREAM = "failed_unknown_active_stream"
MEDIA_FRESH_TIMEOUT_SECONDS = 2.0


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _now_unix_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class LivePipelineConfig:
    incoming_root: Path = DEFAULT_INCOMING_ROOT
    session_dir: Path | None = None
    publish_result_host: str | None = "127.0.0.1"
    publish_result_port: int = 8770
    poll_interval_seconds: float = 0.5
    idle_log_interval_seconds: float = 5.0
    shot_boundary_detector_config: LiveShotBoundaryDetectorConfig | None = None
    shot_tracking_config: LiveShotTrackingStageConfig | None = None


@dataclass
class PipelineProcessSummary:
    discovered_sessions: int = 0
    auto_shot_boundary_frames_scanned: int = 0
    auto_shot_boundary_yolo_frames: int = 0
    auto_shot_boundary_events_emitted: int = 0
    shot_boundary_events_seen: int = 0
    completed_shot_windows_seen: int = 0
    completed_shot_windows_processed: int = 0
    completed_shot_windows_skipped: int = 0
    open_shot_windows_seen: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "discoveredSessions": self.discovered_sessions,
            "autoShotBoundaryFramesScanned": self.auto_shot_boundary_frames_scanned,
            "autoShotBoundaryYoloFrames": self.auto_shot_boundary_yolo_frames,
            "autoShotBoundaryEventsEmitted": self.auto_shot_boundary_events_emitted,
            "shotBoundaryEventsSeen": self.shot_boundary_events_seen,
            "completedShotWindowsSeen": self.completed_shot_windows_seen,
            "completedShotWindowsProcessed": self.completed_shot_windows_processed,
            "completedShotWindowsSkipped": self.completed_shot_windows_skipped,
            "openShotWindowsSeen": self.open_shot_windows_seen,
            "errors": list(self.errors),
        }


class LiveSessionPipeline:
    def __init__(self, config: LivePipelineConfig) -> None:
        self.config = config
        self._shot_boundary_detector = (
            LiveShotBoundaryDetector(config.shot_boundary_detector_config)
            if config.shot_boundary_detector_config is not None
            else None
        )

    def discover_session_dirs(self) -> list[Path]:
        if self.config.session_dir is not None:
            session_dir = self.config.session_dir.expanduser().resolve()
            return [session_dir] if session_dir.exists() else []

        incoming_root = self.config.incoming_root.expanduser().resolve()
        if not incoming_root.exists():
            return []

        session_dirs = sorted(
            [
                path.resolve()
                for path in incoming_root.iterdir()
                if path.is_dir() and path.name.startswith("live_")
            ],
            key=lambda path: path.stat().st_mtime,
        )
        return session_dirs[-1:] if session_dirs else []

    def process_once(self) -> PipelineProcessSummary:
        summary = PipelineProcessSummary()
        session_dirs = self.discover_session_dirs()
        summary.discovered_sessions = len(session_dirs)
        for session_dir in session_dirs:
            try:
                self._process_session_dir(session_dir, summary)
            except Exception as exc:
                summary.errors.append(f"{session_dir}: {exc.__class__.__name__}: {exc}")
        return summary

    def run_forever(self) -> None:
        last_idle_log_at = 0.0
        while True:
            summary = self.process_once()
            did_work = (
                summary.auto_shot_boundary_events_emitted > 0
                or summary.completed_shot_windows_processed > 0
                or bool(summary.errors)
            )
            if did_work:
                print(json.dumps({"kind": "live_pipeline_tick", **summary.to_dict()}, separators=(",", ":")))
            else:
                now = time.monotonic()
                if now - last_idle_log_at >= max(float(self.config.idle_log_interval_seconds), 0.5):
                    print(json.dumps({"kind": "live_pipeline_idle", **summary.to_dict()}, separators=(",", ":")))
                    last_idle_log_at = now

            time.sleep(max(float(self.config.poll_interval_seconds), 0.05))

    def _process_session_dir(self, session_dir: Path, summary: PipelineProcessSummary) -> None:
        media_ready = self._mark_media_freshness(session_dir)

        if self._shot_boundary_detector is not None and media_ready:
            detector_result = self._shot_boundary_detector.process_session_dir(session_dir)
            summary.auto_shot_boundary_frames_scanned += int(detector_result.scanned_frames)
            summary.auto_shot_boundary_yolo_frames += int(detector_result.yolo_frames)
            summary.auto_shot_boundary_events_emitted += int(detector_result.events_emitted)
            self._mark_shot_from_detector_result(session_dir, detector_result)

        shot_boundaries = load_shot_boundaries(session_dir)
        summary.shot_boundary_events_seen += len(shot_boundaries.events)
        summary.completed_shot_windows_seen += len(shot_boundaries.completed_windows)
        if shot_boundaries.open_start is not None:
            summary.open_shot_windows_seen += 1
            if media_ready:
                mark_shot(
                    session_dir,
                    SHOT_OPEN,
                    openWindowId=f"shot_{shot_boundaries.open_start.frame_seq}",
                    activeLaneLockRequestId=shot_boundaries.open_start.lane_lock_request_id,
                    openFrameSeqStart=shot_boundaries.open_start.frame_seq,
                    openFrameSeqEnd=None,
                    lastFailureReason="",
                    lastReason=shot_boundaries.open_start.reason,
                )
                self._publish_pipeline_status(
                    session_dir,
                    state="shot_open",
                    ready=False,
                    reason="shot_window_open",
                    window_id=f"shot_{shot_boundaries.open_start.frame_seq}",
                )
        for error in shot_boundaries.errors:
            summary.errors.append(f"{session_dir}: {error}")

        if self.config.shot_tracking_config is not None and shot_boundaries.completed_windows:
            state = self._load_pipeline_state(session_dir)
            processed_windows = state.setdefault("processedShotWindows", {})
            if not isinstance(processed_windows, dict):
                raise RuntimeError("pipeline_state processedShotWindows must be an object.")

            for window in shot_boundaries.completed_windows:
                if window.window_id in processed_windows:
                    summary.completed_shot_windows_skipped += 1
                    continue

                mark_shot(
                    session_dir,
                    SHOT_WINDOW_COMPLETE,
                    latestWindowId=window.window_id,
                    activeLaneLockRequestId=window.lane_lock_request_id,
                    openWindowId="",
                    openFrameSeqStart=window.frame_seq_start,
                    openFrameSeqEnd=window.frame_seq_end,
                    completedWindowCount=len(shot_boundaries.completed_windows),
                    lastReason=window.end.reason,
                )
                publish_status = self._process_shot_window(session_dir, window, processed_windows)
                summary.completed_shot_windows_processed += 1
                if publish_status == PUBLISH_FAILED_UNKNOWN_STREAM:
                    processed_windows.pop(window.window_id, None)
                    summary.errors.append(f"{session_dir}: shot_result publish failed: unknown active stream")
                self._save_pipeline_state(session_dir, state)

        self._publish_armed_status_if_idle(session_dir, shot_boundaries, media_ready)

    def _process_shot_window(
        self,
        session_dir: Path,
        window: Any,
        processed_windows: dict[str, Any],
    ) -> str:
        if self.config.shot_tracking_config is None:
            raise RuntimeError("Shot tracking config is required to process shot windows.")

        mark_shot(
            session_dir,
            SHOT_ANALYZING,
            latestWindowId=window.window_id,
            activeLaneLockRequestId=window.lane_lock_request_id,
            openWindowId="",
            openFrameSeqStart=window.frame_seq_start,
            openFrameSeqEnd=window.frame_seq_end,
            lastFailureReason="",
            lastReason="shot_tracking_started",
        )
        self._publish_pipeline_status(
            session_dir,
            state="shot_analyzing",
            ready=False,
            reason="shot_tracking_started",
            window_id=window.window_id,
        )
        stage_output = run_live_shot_tracking_stage(
            session_dir,
            window=window,
            config=self.config.shot_tracking_config,
        )
        sam2_result = stage_output.sam2_result
        published = False
        publish_status = "not_configured"
        publish_error = ""
        if self.config.publish_result_host:
            envelope = build_shot_result_envelope(result=stage_output.shot_result)
            published, publish_status, publish_error = self._publish_laptop_result(envelope)

        processed_windows[window.window_id] = {
            "status": "processed",
            "processedUnixMs": _now_unix_ms(),
            "published": bool(published),
            "publishStatus": publish_status,
            "publishError": publish_error,
            "resultPath": str(stage_output.result_path),
            "shotResultSuccess": bool(stage_output.shot_result.success),
            "shotResultFailureReason": str(stage_output.shot_result.failure_reason),
            "yoloSuccess": bool(stage_output.yolo_result.success),
            "sam2Success": bool(sam2_result.success) if sam2_result is not None else None,
            "success": bool(stage_output.result_document.get("success")),
        }
        mark_shot(
            session_dir,
            SHOT_RESULT_READY if stage_output.shot_result.success else SHOT_RESULT_FAILED,
            latestWindowId=window.window_id,
            activeLaneLockRequestId=stage_output.shot_result.lane_lock_request_id,
            openWindowId="",
            openFrameSeqStart=window.frame_seq_start,
            openFrameSeqEnd=window.frame_seq_end,
            processedWindowCount=len(processed_windows),
            latestResultPath=str(stage_output.result_path),
            lastFailureReason=str(stage_output.shot_result.failure_reason),
            lastReason="shot_result_ready" if stage_output.shot_result.success else "shot_result_failed",
        )
        self._publish_pipeline_status(
            session_dir,
            state="shot_ready",
            ready=True,
            reason="shot_result_ready" if stage_output.shot_result.success else "shot_result_failed",
            window_id=window.window_id,
        )
        return publish_status

    def _publish_laptop_result(self, envelope: dict[str, Any]) -> tuple[bool, str, str]:
        try:
            publish_laptop_result(
                envelope,
                host=str(self.config.publish_result_host),
                port=int(self.config.publish_result_port),
            )
        except LaptopResultPublishError as exc:
            if exc.error_code == "unknown_active_stream":
                return False, PUBLISH_FAILED_UNKNOWN_STREAM, str(exc)
            raise
        return True, "published", ""

    def _publish_pipeline_status(
        self,
        session_dir: Path,
        *,
        state: str,
        ready: bool,
        reason: str,
        window_id: str = "",
    ) -> tuple[bool, str, str]:
        if not self.config.publish_result_host:
            return False, "not_configured", ""

        session_state = load_session_state(session_dir)
        session_id = str(session_state.get("sessionId") or "")
        shot_id = str(session_state.get("streamId") or "")
        if not session_id or not shot_id:
            return False, "session_identity_missing", ""

        envelope = build_pipeline_status_envelope(
            session_id=session_id,
            shot_id=shot_id,
            state=state,
            ready=ready,
            reason=reason,
            window_id=window_id,
        )
        try:
            return self._publish_laptop_result(envelope)
        except LaptopResultPublishError as exc:
            if exc.error_code == "unknown_active_stream":
                return False, PUBLISH_FAILED_UNKNOWN_STREAM, str(exc)
            raise

    def _publish_armed_status_if_idle(self, session_dir: Path, shot_boundaries: Any, media_ready: bool) -> None:
        if not media_ready:
            return

        if self._shot_boundary_detector is None or self.config.shot_tracking_config is None:
            return

        if shot_boundaries.open_start is not None:
            return

        state = self._load_pipeline_state(session_dir)
        processed_windows = state.setdefault("processedShotWindows", {})
        if not isinstance(processed_windows, dict):
            raise RuntimeError("pipeline_state processedShotWindows must be an object.")

        for window in shot_boundaries.completed_windows:
            if window.window_id not in processed_windows:
                return

        session_state = load_session_state(session_dir)
        lane = session_state.get("lane") or {}
        if str(lane.get("state") or "") != LANE_CONFIRMED:
            return

        request_id = str(lane.get("confirmedRequestId") or "")
        if not request_id:
            return

        if state.get("lastPublishedArmedLaneLockRequestId") == request_id:
            return

        published, publish_status, publish_error = self._publish_pipeline_status(
            session_dir,
            state="shot_detection_armed",
            ready=True,
            reason="confirmed_lane_armed",
        )
        if published:
            state["lastPublishedArmedLaneLockRequestId"] = request_id
        state["lastArmedStatusPublished"] = bool(published)
        state["lastArmedStatusPublishStatus"] = publish_status
        state["lastArmedStatusPublishError"] = publish_error
        state["lastArmedStatusPublishedUnixMs"] = _now_unix_ms()
        self._save_pipeline_state(session_dir, state)

    def _mark_shot_from_detector_result(self, session_dir: Path, detector_result: Any) -> None:
        lane_lock_request_id = str(getattr(detector_result, "confirmed_lane_lock_request_id", "") or "")
        detector_mode = str(getattr(detector_result, "detector_mode", "") or "")
        reason = str(getattr(detector_result, "reason", "") or "")

        if reason == "lane_lock_confirm_missing" and not lane_lock_request_id:
            mark_shot(
                session_dir,
                SHOT_DISABLED_UNTIL_LANE_CONFIRMED,
                activeLaneLockRequestId="",
                candidateStartFrameSeq=None,
                openWindowId="",
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason="",
                lastReason=reason,
            )
            return

        if detector_mode == "pending":
            mark_shot(
                session_dir,
                SHOT_START_CANDIDATE,
                activeLaneLockRequestId=lane_lock_request_id,
                candidateStartFrameSeq=getattr(detector_result, "pending_frame_seq", None),
                openWindowId="",
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason="",
                lastReason=reason,
            )
            return

        if detector_mode == "tracking":
            mark_shot(
                session_dir,
                SHOT_OPEN,
                activeLaneLockRequestId=lane_lock_request_id,
                candidateStartFrameSeq=None,
                openWindowId=str(getattr(detector_result, "active_window_id", "") or ""),
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason="",
                lastReason=reason,
            )
            return

        mark_shot(
            session_dir,
            SHOT_ARMED,
            activeLaneLockRequestId=lane_lock_request_id,
            candidateStartFrameSeq=None,
            openWindowId="",
            openFrameSeqStart=None,
            openFrameSeqEnd=None,
            lastFailureReason="",
            lastReason=reason,
        )

    def _mark_media_freshness(self, session_dir: Path) -> bool:
        try:
            state = load_session_state(session_dir)
        except Exception:
            return True

        transport = state.get("transport") or {}
        lane = state.get("lane") or {}
        shot = state.get("shot") or {}
        if bool(transport.get("sessionEndSeen")) or str(transport.get("state") or "") == "Ended":
            mark_transport(
                session_dir,
                TRANSPORT_ENDED,
                sessionEndSeen=True,
                mediaConnected=False,
            )
            return False

        if str(lane.get("state") or "") != "Confirmed":
            return True

        media_connected = bool(transport.get("mediaConnected"))
        last_sample_unix_ms = transport.get("lastMediaSampleUnixMs")
        try:
            last_sample_unix_ms = int(last_sample_unix_ms)
        except Exception:
            last_sample_unix_ms = 0

        stale = True
        if media_connected and last_sample_unix_ms > 0:
            age_seconds = max(0.0, (_now_unix_ms() - last_sample_unix_ms) / 1000.0)
            stale = age_seconds > MEDIA_FRESH_TIMEOUT_SECONDS

        shot_state = str(shot.get("state") or "")
        if stale:
            reason = "media_stale" if media_connected else "media_disconnected"
            mark_transport(
                session_dir,
                TRANSPORT_DEGRADED,
                lastMediaDisconnectReason=reason,
            )
            if shot_state in {
                SHOT_ARMED,
                SHOT_START_CANDIDATE,
                SHOT_OPEN,
                SHOT_DISABLED_UNTIL_MEDIA_FRESH,
            }:
                mark_shot(
                    session_dir,
                    SHOT_DISABLED_UNTIL_MEDIA_FRESH,
                    activeLaneLockRequestId=str(lane.get("confirmedRequestId") or ""),
                    candidateStartFrameSeq=None,
                    openWindowId="",
                    openFrameSeqStart=None,
                    openFrameSeqEnd=None,
                    lastFailureReason=reason,
                    lastReason=reason,
                )
            return False

        if shot_state == SHOT_DISABLED_UNTIL_MEDIA_FRESH:
            mark_shot(
                session_dir,
                SHOT_ARMED,
                activeLaneLockRequestId=str(lane.get("confirmedRequestId") or ""),
                candidateStartFrameSeq=None,
                openWindowId="",
                openFrameSeqStart=None,
                openFrameSeqEnd=None,
                lastFailureReason="",
                lastReason="media_fresh",
            )
        return True

    def _state_dir(self, session_dir: Path) -> Path:
        return session_dir / "analysis_live_pipeline"

    def _state_path(self, session_dir: Path) -> Path:
        return self._state_dir(session_dir) / "pipeline_state.json"

    def _load_pipeline_state(self, session_dir: Path) -> dict[str, Any]:
        state = _load_json(self._state_path(session_dir))
        if not state:
            return {
                "schemaVersion": PIPELINE_STATE_SCHEMA_VERSION,
                "sessionDir": str(session_dir),
                "processedShotWindows": {},
            }
        if state.get("schemaVersion") != PIPELINE_STATE_SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported pipeline state schemaVersion {state.get('schemaVersion')!r}.")
        state.setdefault("processedShotWindows", {})
        if not isinstance(state.get("processedShotWindows"), dict):
            raise RuntimeError("pipeline_state processedShotWindows must be an object.")
        return state

    def _save_pipeline_state(self, session_dir: Path, state: dict[str, Any]) -> None:
        state_dir = self._state_dir(session_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path(session_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")


def build_pipeline_from_paths(
    *,
    incoming_root: Path | None = None,
    session_dir: Path | None = None,
    publish_result_host: str | None = "127.0.0.1",
    publish_result_port: int = 8770,
    poll_interval_seconds: float = 0.5,
    idle_log_interval_seconds: float = 5.0,
    shot_boundary_detector_config: LiveShotBoundaryDetectorConfig | None = None,
    shot_tracking_config: LiveShotTrackingStageConfig | None = None,
) -> LiveSessionPipeline:
    return LiveSessionPipeline(
        LivePipelineConfig(
            incoming_root=incoming_root or DEFAULT_INCOMING_ROOT,
            session_dir=session_dir,
            publish_result_host=publish_result_host,
            publish_result_port=publish_result_port,
            poll_interval_seconds=poll_interval_seconds,
            idle_log_interval_seconds=idle_log_interval_seconds,
            shot_boundary_detector_config=shot_boundary_detector_config,
            shot_tracking_config=shot_tracking_config,
        )
    )
