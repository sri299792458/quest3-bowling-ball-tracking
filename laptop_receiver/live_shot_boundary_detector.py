from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from laptop_receiver.lane_geometry import bottom_center_from_box, project_ball_image_point_to_lane_space
from laptop_receiver.lane_lock_types import CameraIntrinsics, FrameCameraState, LaneLockResult
from laptop_receiver.live_lane_lock_results import load_confirmed_lane_lock
from laptop_receiver.live_camera_sam2_tracker import LiveCameraSam2Config, LiveCameraSam2Tracker
from laptop_receiver.live_shot_boundaries import (
    SHOT_BOUNDARY_END,
    SHOT_BOUNDARY_START,
    ShotBoundaryEvent,
    load_shot_boundaries,
)
from laptop_receiver.local_clip_artifact import DecodedFrame, LocalClipArtifact, load_local_clip_artifact
from laptop_receiver.standalone_yolo_seed import detect_yolo_seed_for_image


SHOT_BOUNDARY_DETECTOR_STATE_SCHEMA_VERSION = "live_shot_boundary_detector_state"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


@dataclass(frozen=True)
class LiveShotBoundaryDetectorConfig:
    yolo_checkpoint_path: Path
    yolo_imgsz: int = 1280
    yolo_device: str = "0"
    yolo_det_conf: float = 0.05
    yolo_start_conf: float = 0.8
    yolo_track_conf: float = 0.25
    yolo_min_box_size: float = 10.0
    scan_stride_frames: int = 1
    sam2_config: LiveCameraSam2Config | None = None
    require_sam2_tracking: bool = False
    warm_models_on_start: bool = True
    pre_roll_seconds: float = 0.5
    post_roll_seconds: float = 0.75
    start_confirm_seconds: float = 0.8
    min_confirm_downlane_delta_meters: float = 0.10
    release_lateral_margin_meters: float = 0.10
    release_downlane_margin_meters: float = 0.35
    min_projection_confidence: float = 0.30
    tracking_lost_grace_seconds: float = 1.25
    min_shot_duration_seconds: float = 0.8
    max_shot_duration_seconds: float = 8.0
    terminal_downlane_margin_meters: float = 0.50
    shot_cooldown_seconds: float = 2.0


@dataclass(frozen=True)
class LiveShotBoundaryDetectorResult:
    session_dir: Path
    state_path: Path
    status: str
    reason: str
    scanned_frames: int
    yolo_frames: int
    events_emitted: int
    start_events_emitted: int
    end_events_emitted: int
    latest_scanned_frame_seq: int
    detector_mode: str
    confirmed_lane_lock_request_id: str
    pending_frame_seq: int | None
    active_window_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionDir": str(self.session_dir),
            "statePath": str(self.state_path),
            "status": self.status,
            "reason": self.reason,
            "scannedFrames": self.scanned_frames,
            "yoloFrames": self.yolo_frames,
            "eventsEmitted": self.events_emitted,
            "startEventsEmitted": self.start_events_emitted,
            "endEventsEmitted": self.end_events_emitted,
            "latestScannedFrameSeq": self.latest_scanned_frame_seq,
            "detectorMode": self.detector_mode,
            "confirmedLaneLockRequestId": self.confirmed_lane_lock_request_id,
            "pendingFrameSeq": self.pending_frame_seq,
            "activeWindowId": self.active_window_id,
        }


@dataclass(frozen=True)
class _ProjectedCandidate:
    frame_index: int
    frame_seq: int
    camera_timestamp_us: int
    pts_us: int
    detector_confidence: float
    box: list[float]
    box_width: float
    box_height: float
    lane_x_meters: float
    lane_s_meters: float
    lane_h_meters: float
    is_on_locked_lane: bool
    projection_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frameIndex": int(self.frame_index),
            "frameSeq": int(self.frame_seq),
            "cameraTimestampUs": int(self.camera_timestamp_us),
            "ptsUs": int(self.pts_us),
            "detectorConfidence": float(self.detector_confidence),
            "box": [float(value) for value in self.box],
            "boxWidth": float(self.box_width),
            "boxHeight": float(self.box_height),
            "lanePoint": {
                "xMeters": float(self.lane_x_meters),
                "sMeters": float(self.lane_s_meters),
                "hMeters": float(self.lane_h_meters),
            },
            "isOnLockedLane": bool(self.is_on_locked_lane),
            "projectionConfidence": float(self.projection_confidence),
        }


class LiveShotBoundaryDetector:
    def __init__(self, config: LiveShotBoundaryDetectorConfig) -> None:
        self.config = config
        self._model: Any | None = None
        self._sam2_tracker = LiveCameraSam2Tracker(config.sam2_config) if config.sam2_config is not None else None
        if bool(config.require_sam2_tracking) and self._sam2_tracker is None:
            raise RuntimeError("Camera SAM2 tracking is required, but no SAM2 config was provided.")
        if bool(config.warm_models_on_start):
            self._load_model()
            if self._sam2_tracker is not None:
                self._sam2_tracker.warm()

    def process_session_dir(self, session_dir: Path | str) -> LiveShotBoundaryDetectorResult:
        root = Path(session_dir).expanduser().resolve()
        state = self._load_state(root)
        state_path = self._state_path(root)

        lane_lock = load_confirmed_lane_lock(root)
        if lane_lock is None:
            state["mode"] = "idle"
            state["pendingCandidate"] = None
            state["activeShot"] = None
            state["lastReason"] = "lane_lock_confirm_missing"
            self._save_state(root, state)
            return self._result(
                root,
                state_path,
                state,
                status="waiting",
                reason="lane_lock_confirm_missing",
                confirmed_lane_lock_request_id="",
            )

        if state.get("lastReason") == "lane_lock_confirm_missing":
            state["lastReason"] = "lane_lock_confirmed_waiting_for_ball"

        shot_boundaries = load_shot_boundaries(root)
        if shot_boundaries.errors:
            raise RuntimeError(
                "Refusing automatic shot-boundary detection because "
                f"shot_boundaries.jsonl is invalid: {'; '.join(shot_boundaries.errors)}"
            )

        self._sync_state_with_boundaries(state, shot_boundaries.events, shot_boundaries.open_start)
        artifact = load_local_clip_artifact(root)
        if not artifact.frame_metadata:
            self._save_state(root, state)
            return self._result(
                root,
                state_path,
                state,
                status="waiting",
                reason="frame_metadata_missing",
                confirmed_lane_lock_request_id=lane_lock.request_id,
            )

        session_id, stream_shot_id = self._session_identity(artifact)
        intrinsics = CameraIntrinsics.from_session_metadata(artifact.session_metadata)
        fps = self._fps_for_artifact(artifact)

        scanned_frames = 0
        yolo_frames = 0
        start_events_emitted = 0
        end_events_emitted = 0
        last_reason = "no_new_frames"

        for decoded_frame in artifact.iter_frames():
            metadata = decoded_frame.metadata or {}
            frame_seq = self._frame_seq(metadata, decoded_frame.frame_index)
            if frame_seq <= _int(state.get("lastScannedFrameSeq"), -1):
                continue

            scanned_frames += 1
            state["lastScannedFrameSeq"] = int(frame_seq)
            state["lastScannedFrameIndex"] = int(decoded_frame.frame_index)

            candidate = None
            if self._should_run_yolo(decoded_frame, state):
                yolo_frames += 1
                candidate = self._projected_candidate_for_frame(
                    artifact=artifact,
                    decoded_frame=decoded_frame,
                    lane_lock=lane_lock,
                    intrinsics=intrinsics,
                    session_id=session_id,
                    shot_id=stream_shot_id,
                )

            emitted = self._advance_state_for_frame(
                root=root,
                state=state,
                artifact=artifact,
                lane_lock=lane_lock,
                fps=fps,
                session_id=session_id,
                shot_id=stream_shot_id,
                decoded_frame=decoded_frame,
                candidate=candidate,
            )
            for event in emitted:
                last_reason = str(event.get("reason") or "shot_boundary_emitted")
                if event.get("boundary_type") == SHOT_BOUNDARY_START:
                    start_events_emitted += 1
                elif event.get("boundary_type") == SHOT_BOUNDARY_END:
                    end_events_emitted += 1

        if scanned_frames > 0:
            last_reason = str(state.get("lastReason") or last_reason)
        state["lastDetectorRun"] = {
            "scannedFrames": int(scanned_frames),
            "yoloFrames": int(yolo_frames),
            "startEventsEmitted": int(start_events_emitted),
            "endEventsEmitted": int(end_events_emitted),
            "reason": last_reason,
        }
        self._save_state(root, state)
        return LiveShotBoundaryDetectorResult(
            session_dir=root,
            state_path=state_path,
            status=str(state.get("mode") or "idle"),
            reason=last_reason,
            scanned_frames=int(scanned_frames),
            yolo_frames=int(yolo_frames),
            events_emitted=int(start_events_emitted + end_events_emitted),
            start_events_emitted=int(start_events_emitted),
            end_events_emitted=int(end_events_emitted),
            latest_scanned_frame_seq=_int(state.get("lastScannedFrameSeq"), -1),
            detector_mode=str(state.get("mode") or "idle"),
            confirmed_lane_lock_request_id=str(lane_lock.request_id),
            pending_frame_seq=self._pending_frame_seq(state),
            active_window_id=self._active_window_id(state),
        )

    def _advance_state_for_frame(
        self,
        *,
        root: Path,
        state: dict[str, Any],
        artifact: LocalClipArtifact,
        lane_lock: LaneLockResult,
        fps: float,
        session_id: str,
        shot_id: str,
        decoded_frame: DecodedFrame,
        candidate: _ProjectedCandidate | None,
    ) -> list[dict[str, Any]]:
        frame_metadata = decoded_frame.metadata or {}
        frame_seq = self._frame_seq(frame_metadata, decoded_frame.frame_index)
        mode = str(state.get("mode") or "idle")

        if mode == "idle":
            if frame_seq < _int(state.get("cooldownUntilFrameSeq"), -1):
                state["lastReason"] = "shot_cooldown"
                return []
            if candidate is None:
                state["lastReason"] = "no_yolo_candidate"
                return []
            if self._is_release_candidate(candidate, lane_lock):
                state["mode"] = "pending"
                state["pendingCandidate"] = candidate.to_dict()
                state["lastReason"] = "pending_release_candidate"
            else:
                state["lastReason"] = "yolo_candidate_not_release"
            return []

        if mode == "pending":
            pending = state.get("pendingCandidate")
            if not isinstance(pending, Mapping):
                state["mode"] = "idle"
                state["pendingCandidate"] = None
                state["lastReason"] = "pending_candidate_missing"
                return []

            if candidate is not None and self._is_track_candidate(candidate):
                if self._candidate_confirms_release(pending, candidate, fps):
                    start_event, active_shot = self._build_start_event(
                        artifact=artifact,
                        pending=pending,
                        session_id=session_id,
                        shot_id=shot_id,
                        lane_lock_request_id=lane_lock.request_id,
                    )
                    active_shot["confirmingDetection"] = candidate.to_dict()
                    active_shot["lastDetection"] = candidate.to_dict()
                    active_shot["lastDetectionFrameSeq"] = int(candidate.frame_seq)
                    active_shot["lastDetectionPtsUs"] = int(candidate.pts_us)
                    active_shot["lastLaneSMeters"] = float(candidate.lane_s_meters)
                    self._start_camera_sam2_tracking(
                        active_shot=active_shot,
                        decoded_frame=decoded_frame,
                        candidate=candidate,
                    )
                    self._append_boundary_event(root, start_event)
                    state["mode"] = "tracking"
                    state["pendingCandidate"] = None
                    state["activeShot"] = active_shot
                    state["lastReason"] = str(start_event["reason"])
                    return [start_event]

            if self._elapsed_since_candidate_seconds(pending, frame_metadata, frame_seq, fps) > float(
                self.config.start_confirm_seconds
            ):
                if candidate is not None and self._is_release_candidate(candidate, lane_lock):
                    state["pendingCandidate"] = candidate.to_dict()
                    state["lastReason"] = "pending_release_candidate_refreshed"
                else:
                    state["mode"] = "idle"
                    state["pendingCandidate"] = None
                    state["lastReason"] = "pending_release_candidate_expired"
            return []

        if mode == "tracking":
            active_shot = state.get("activeShot")
            if not isinstance(active_shot, dict):
                state["mode"] = "idle"
                state["activeShot"] = None
                state["lastReason"] = "active_shot_missing"
                return []

            if self._sam2_tracker is not None:
                return self._advance_camera_sam2_tracking_for_frame(
                    root=root,
                    state=state,
                    active_shot=active_shot,
                    artifact=artifact,
                    lane_lock=lane_lock,
                    fps=fps,
                    session_id=session_id,
                    shot_id=shot_id,
                    decoded_frame=decoded_frame,
                )
            if bool(self.config.require_sam2_tracking):
                raise RuntimeError("Camera SAM2 tracking is required, but the tracker is not available.")

            if candidate is not None and self._is_track_candidate(candidate):
                active_shot["lastDetection"] = candidate.to_dict()
                active_shot["lastDetectionFrameSeq"] = int(candidate.frame_seq)
                active_shot["lastDetectionPtsUs"] = int(candidate.pts_us)
                active_shot["lastLaneSMeters"] = float(candidate.lane_s_meters)
                active_shot["lastReason"] = "tracking_yolo_candidate"
                if self._candidate_reached_terminal(candidate, lane_lock):
                    active_shot.setdefault(
                        "terminalCandidate",
                        {
                            "frameSeq": int(candidate.frame_seq),
                            "ptsUs": int(candidate.pts_us),
                            "laneSMeters": float(candidate.lane_s_meters),
                        },
                    )

            end_reason = self._shot_end_reason(
                active_shot=active_shot,
                current_metadata=frame_metadata,
                current_frame_seq=frame_seq,
                lane_lock=lane_lock,
                fps=fps,
            )
            if not end_reason:
                state["lastReason"] = str(active_shot.get("lastReason") or "tracking")
                return []

            end_event = self._build_boundary_event(
                boundary_type=SHOT_BOUNDARY_END,
                session_id=str(active_shot.get("sessionId") or session_id),
                shot_id=str(active_shot.get("shotId") or shot_id),
                lane_lock_request_id=str(active_shot.get("laneLockRequestId") or lane_lock.request_id),
                metadata=frame_metadata,
                frame_seq=frame_seq,
                reason=end_reason,
            )
            self._append_boundary_event(root, end_event)
            cooldown_frames = int(round(float(self.config.shot_cooldown_seconds) * fps))
            state["mode"] = "idle"
            state["pendingCandidate"] = None
            state["activeShot"] = None
            state["cooldownUntilFrameSeq"] = int(frame_seq + max(cooldown_frames, 0))
            state["lastReason"] = end_reason
            return [end_event]

        state["mode"] = "idle"
        state["pendingCandidate"] = None
        state["activeShot"] = None
        state["lastReason"] = f"unknown_detector_mode:{mode}"
        return []

    def _start_camera_sam2_tracking(
        self,
        *,
        active_shot: dict[str, Any],
        decoded_frame: DecodedFrame,
        candidate: _ProjectedCandidate,
    ) -> None:
        if self._sam2_tracker is None:
            if bool(self.config.require_sam2_tracking):
                raise RuntimeError("Camera SAM2 tracking is required, but no tracker is configured.")
            return
        if self._sam2_tracker.active:
            raise RuntimeError("Camera SAM2 tracker is already active for another shot.")

        metadata = decoded_frame.metadata or {}
        seed = candidate.to_dict()
        seed["seedMode"] = "live_yolo_release_confirming_frame"
        self._sam2_tracker.start_from_seed(
            frame_index=int(decoded_frame.frame_index),
            frame_seq=self._frame_seq(metadata, decoded_frame.frame_index),
            image_bgr=decoded_frame.image_bgr,
            seed=seed,
            metadata=metadata,
        )
        active_shot["cameraSam2"] = {
            "status": "tracking",
            "seedFrameIndex": int(decoded_frame.frame_index),
            "seedFrameSeq": self._frame_seq(metadata, decoded_frame.frame_index),
            "seedDetectorConfidence": float(candidate.detector_confidence),
        }
        active_shot["lastReason"] = "camera_sam2_tracking_started"

    def _advance_camera_sam2_tracking_for_frame(
        self,
        *,
        root: Path,
        state: dict[str, Any],
        active_shot: dict[str, Any],
        artifact: LocalClipArtifact,
        lane_lock: LaneLockResult,
        fps: float,
        session_id: str,
        shot_id: str,
        decoded_frame: DecodedFrame,
    ) -> list[dict[str, Any]]:
        del artifact
        if self._sam2_tracker is None:
            raise RuntimeError("Camera SAM2 tracker is not configured.")
        if not self._sam2_tracker.active:
            raise RuntimeError("Camera SAM2 tracker cannot resume an already-open shot after process restart.")

        frame_metadata = decoded_frame.metadata or {}
        frame_seq = self._frame_seq(frame_metadata, decoded_frame.frame_index)
        self._sam2_tracker.track_frame(
            frame_index=int(decoded_frame.frame_index),
            frame_seq=frame_seq,
            image_bgr=decoded_frame.image_bgr,
            metadata=frame_metadata,
        )
        active_shot["lastDetectionFrameSeq"] = int(frame_seq)
        active_shot["lastDetectionPtsUs"] = self._time_us(frame_metadata)
        active_shot["lastReason"] = "camera_sam2_tracking"

        end_reason = self._sam2_tracker.stop_reason(fps=fps)
        if not end_reason:
            state["lastReason"] = "camera_sam2_tracking"
            return []

        end_event = self._build_boundary_event(
            boundary_type=SHOT_BOUNDARY_END,
            session_id=str(active_shot.get("sessionId") or session_id),
            shot_id=str(active_shot.get("shotId") or shot_id),
            lane_lock_request_id=str(active_shot.get("laneLockRequestId") or lane_lock.request_id),
            metadata=frame_metadata,
            frame_seq=frame_seq,
            reason=end_reason,
        )
        output_dir = (
            root
            / "analysis_live_pipeline"
            / "camera_sam2"
            / f"shot_{_int(active_shot.get('startFrameSeq'), frame_seq)}_{frame_seq}"
        )
        track_result = self._sam2_tracker.finish(
            output_dir=output_dir,
            stop_reason=end_reason,
            source_frame_idx_end=int(decoded_frame.frame_index),
        )
        self._append_boundary_event(root, end_event)

        cooldown_frames = int(round(float(self.config.shot_cooldown_seconds) * fps))
        state["mode"] = "idle"
        state["pendingCandidate"] = None
        state["activeShot"] = None
        state["cooldownUntilFrameSeq"] = int(frame_seq + max(cooldown_frames, 0))
        state["lastReason"] = end_reason
        state["lastCameraSam2Result"] = track_result.to_dict()
        return [end_event]

    def _projected_candidate_for_frame(
        self,
        *,
        artifact: LocalClipArtifact,
        decoded_frame: DecodedFrame,
        lane_lock: LaneLockResult,
        intrinsics: CameraIntrinsics,
        session_id: str,
        shot_id: str,
    ) -> _ProjectedCandidate | None:
        detection = detect_yolo_seed_for_image(
            self._load_model(),
            decoded_frame.image_bgr,
            decoded_frame.frame_index,
            imgsz=int(self.config.yolo_imgsz),
            device=str(self.config.yolo_device),
            det_conf=float(self.config.yolo_det_conf),
        )
        if detection is None:
            return None

        box = [float(value) for value in detection["box"]]
        x1, y1, x2, y2 = box
        box_width = max(0.0, x2 - x1)
        box_height = max(0.0, y2 - y1)
        if box_width < float(self.config.yolo_min_box_size) or box_height < float(self.config.yolo_min_box_size):
            return None

        metadata = decoded_frame.metadata or {}
        frame_state = FrameCameraState.from_frame_metadata(metadata)
        try:
            lane_space_point = project_ball_image_point_to_lane_space(
                session_id=session_id,
                shot_id=shot_id,
                image_point_px=bottom_center_from_box(box),
                frame_camera_state=frame_state,
                intrinsics=intrinsics,
                lane_lock=lane_lock,
                point_definition="auto_yolo_bbox_bottom_contact_proxy",
            )
        except Exception:
            return None

        return _ProjectedCandidate(
            frame_index=int(decoded_frame.frame_index),
            frame_seq=self._frame_seq(metadata, decoded_frame.frame_index),
            camera_timestamp_us=_int(metadata.get("cameraTimestampUs")),
            pts_us=_int(metadata.get("ptsUs")),
            detector_confidence=float(detection["detector_confidence"]),
            box=box,
            box_width=box_width,
            box_height=box_height,
            lane_x_meters=float(lane_space_point.lane_point.x_meters),
            lane_s_meters=float(lane_space_point.lane_point.s_meters),
            lane_h_meters=float(lane_space_point.lane_point.h_meters),
            is_on_locked_lane=bool(lane_space_point.is_on_locked_lane),
            projection_confidence=float(lane_space_point.projection_confidence),
        )

    def _is_release_candidate(self, candidate: _ProjectedCandidate, lane_lock: LaneLockResult) -> bool:
        if float(candidate.detector_confidence) < float(self.config.yolo_start_conf):
            return False
        if not self._is_track_candidate(candidate):
            return False

        corridor = lane_lock.release_corridor
        s_start = float(corridor.s_start_meters) - float(self.config.release_downlane_margin_meters)
        s_end = float(corridor.s_end_meters)
        if s_end <= s_start:
            s_end = min(2.5, max(float(lane_lock.visible_downlane_meters), 0.0))
        s_end += float(self.config.release_downlane_margin_meters)

        half_width = float(corridor.half_width_meters)
        if half_width <= 0.0:
            half_width = float(lane_lock.lane_width_meters) * 0.5
        half_width += float(self.config.release_lateral_margin_meters)

        return (
            abs(float(candidate.lane_x_meters)) <= half_width
            and float(candidate.lane_s_meters) >= s_start
            and float(candidate.lane_s_meters) <= s_end
        )

    def _is_track_candidate(self, candidate: _ProjectedCandidate) -> bool:
        return (
            bool(candidate.is_on_locked_lane)
            and float(candidate.detector_confidence) >= float(self.config.yolo_track_conf)
            and float(candidate.projection_confidence) >= float(self.config.min_projection_confidence)
        )

    def _candidate_confirms_release(
        self,
        pending: Mapping[str, Any],
        candidate: _ProjectedCandidate,
        fps: float,
    ) -> bool:
        elapsed_seconds = self._elapsed_since_candidate_seconds(
            pending,
            {
                "ptsUs": candidate.pts_us,
                "cameraTimestampUs": candidate.camera_timestamp_us,
            },
            int(candidate.frame_seq),
            fps,
        )
        if elapsed_seconds <= 0.0 or elapsed_seconds > float(self.config.start_confirm_seconds):
            return False
        pending_lane_point = pending.get("lanePoint") if isinstance(pending.get("lanePoint"), Mapping) else {}
        pending_s = _float(pending_lane_point.get("sMeters") if isinstance(pending_lane_point, Mapping) else None)
        delta_s = float(candidate.lane_s_meters) - pending_s
        return delta_s >= float(self.config.min_confirm_downlane_delta_meters)

    def _candidate_reached_terminal(self, candidate: _ProjectedCandidate, lane_lock: LaneLockResult) -> bool:
        visible_limit = float(lane_lock.visible_downlane_meters or lane_lock.lane_length_meters)
        terminal_s = max(
            float(lane_lock.release_corridor.s_end_meters),
            visible_limit - float(self.config.terminal_downlane_margin_meters),
        )
        return float(candidate.lane_s_meters) >= terminal_s

    def _shot_end_reason(
        self,
        *,
        active_shot: Mapping[str, Any],
        current_metadata: Mapping[str, Any],
        current_frame_seq: int,
        lane_lock: LaneLockResult,
        fps: float,
    ) -> str:
        del lane_lock
        duration_seconds = self._elapsed_since_active_seconds(
            active_shot,
            current_metadata,
            current_frame_seq,
            fps,
        )
        if duration_seconds >= float(self.config.max_shot_duration_seconds):
            return "auto_yolo_max_shot_duration"

        if duration_seconds < float(self.config.min_shot_duration_seconds):
            return ""

        terminal = active_shot.get("terminalCandidate")
        if isinstance(terminal, Mapping):
            terminal_elapsed = self._elapsed_since_candidate_seconds(
                terminal,
                current_metadata,
                current_frame_seq,
                fps,
            )
            if terminal_elapsed >= float(self.config.post_roll_seconds):
                return "auto_yolo_terminal_downlane_postroll"

        last_detection = active_shot.get("lastDetection")
        if isinstance(last_detection, Mapping):
            lost_seconds = self._elapsed_since_candidate_seconds(
                last_detection,
                current_metadata,
                current_frame_seq,
                fps,
            )
            if lost_seconds >= float(self.config.tracking_lost_grace_seconds):
                return "auto_yolo_tracking_lost_grace"

        return ""

    def _build_start_event(
        self,
        *,
        artifact: LocalClipArtifact,
        pending: Mapping[str, Any],
        session_id: str,
        shot_id: str,
        lane_lock_request_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        fps = self._fps_for_artifact(artifact)
        pre_roll_frames = int(round(float(self.config.pre_roll_seconds) * fps))
        seed_frame_seq = _int(pending.get("frameSeq"))
        target_frame_seq = max(0, seed_frame_seq - max(pre_roll_frames, 0))
        start_metadata = self._metadata_at_or_after_frame_seq(artifact.frame_metadata, target_frame_seq)
        if start_metadata is None or self._frame_seq(start_metadata, seed_frame_seq) > seed_frame_seq:
            start_metadata = {
                "frameSeq": seed_frame_seq,
                "cameraTimestampUs": _int(pending.get("cameraTimestampUs")),
                "ptsUs": _int(pending.get("ptsUs")),
            }
        start_frame_seq = self._frame_seq(start_metadata, target_frame_seq)
        event = self._build_boundary_event(
            boundary_type=SHOT_BOUNDARY_START,
            session_id=session_id,
            shot_id=shot_id,
            lane_lock_request_id=lane_lock_request_id,
            metadata=start_metadata,
            frame_seq=start_frame_seq,
            reason="auto_yolo_release_corridor_confirmed",
        )
        active_shot = {
            "sessionId": session_id,
            "shotId": shot_id,
            "laneLockRequestId": lane_lock_request_id,
            "startFrameSeq": int(start_frame_seq),
            "startPtsUs": _int(start_metadata.get("ptsUs")),
            "startCameraTimestampUs": _int(start_metadata.get("cameraTimestampUs")),
            "seedCandidate": dict(pending),
            "lastDetection": dict(pending),
            "lastDetectionFrameSeq": seed_frame_seq,
            "lastDetectionPtsUs": _int(pending.get("ptsUs")),
            "lastLaneSMeters": _float(
                pending.get("lanePoint", {}).get("sMeters")
                if isinstance(pending.get("lanePoint"), Mapping)
                else None
            ),
        }
        return event, active_shot

    def _build_boundary_event(
        self,
        *,
        boundary_type: str,
        session_id: str,
        shot_id: str,
        lane_lock_request_id: str,
        metadata: Mapping[str, Any],
        frame_seq: int,
        reason: str,
    ) -> dict[str, Any]:
        event = {
            "kind": "shot_boundary",
            "session_id": str(session_id),
            "shot_id": str(shot_id),
            "laneLockRequestId": str(lane_lock_request_id),
            "boundary_type": str(boundary_type),
            "frame_seq": int(frame_seq),
            "camera_timestamp_us": _int(metadata.get("cameraTimestampUs")),
            "pts_us": _int(metadata.get("ptsUs")),
            "reason": str(reason),
        }
        ShotBoundaryEvent.from_envelope(event, envelope_index=-1)
        return event

    def _append_boundary_event(self, root: Path, event: Mapping[str, Any]) -> None:
        path = root / "shot_boundaries.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), separators=(",", ":")) + "\n")

    def _sync_state_with_boundaries(
        self,
        state: dict[str, Any],
        events: list[ShotBoundaryEvent],
        open_start: ShotBoundaryEvent | None,
    ) -> None:
        if events:
            max_boundary_frame_seq = max(int(event.frame_seq) for event in events)
            if _int(state.get("lastScannedFrameSeq"), -1) < max_boundary_frame_seq:
                state["lastScannedFrameSeq"] = int(max_boundary_frame_seq)

        if open_start is not None:
            active_shot = state.get("activeShot")
            if not isinstance(active_shot, Mapping) or _int(active_shot.get("startFrameSeq"), -1) != int(
                open_start.frame_seq
            ):
                state["mode"] = "tracking"
                state["pendingCandidate"] = None
                state["activeShot"] = {
                    "sessionId": open_start.session_id,
                    "shotId": open_start.shot_id,
                    "laneLockRequestId": open_start.lane_lock_request_id,
                    "startFrameSeq": int(open_start.frame_seq),
                    "startPtsUs": int(open_start.pts_us),
                    "startCameraTimestampUs": int(open_start.camera_timestamp_us),
                    "lastDetectionFrameSeq": int(open_start.frame_seq),
                    "lastDetectionPtsUs": int(open_start.pts_us),
                    "lastDetection": {
                        "frameSeq": int(open_start.frame_seq),
                        "ptsUs": int(open_start.pts_us),
                        "cameraTimestampUs": int(open_start.camera_timestamp_us),
                    },
                }
            return

        if str(state.get("mode") or "idle") == "tracking":
            state["mode"] = "idle"
            state["activeShot"] = None
            state["lastReason"] = "tracking_state_closed_by_existing_boundaries"

    def _should_run_yolo(self, decoded_frame: DecodedFrame, state: Mapping[str, Any]) -> bool:
        if self._sam2_tracker is not None and str(state.get("mode") or "idle") == "tracking":
            return False
        stride = max(int(self.config.scan_stride_frames), 1)
        return int(decoded_frame.frame_index) % stride == 0

    def _load_model(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(str(self.config.yolo_checkpoint_path.expanduser().resolve()))
        return self._model

    def _load_state(self, root: Path) -> dict[str, Any]:
        path = self._state_path(root)
        if not path.exists():
            return {
                "schemaVersion": SHOT_BOUNDARY_DETECTOR_STATE_SCHEMA_VERSION,
                "sessionDir": str(root),
                "mode": "idle",
                "lastScannedFrameSeq": -1,
                "lastScannedFrameIndex": -1,
                "cooldownUntilFrameSeq": -1,
                "pendingCandidate": None,
                "activeShot": None,
                "lastReason": "not_started",
            }
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schemaVersion") != SHOT_BOUNDARY_DETECTOR_STATE_SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported shot boundary detector state schemaVersion {state.get('schemaVersion')!r}.")
        state.setdefault("mode", "idle")
        state.setdefault("lastScannedFrameSeq", -1)
        state.setdefault("lastScannedFrameIndex", -1)
        state.setdefault("cooldownUntilFrameSeq", -1)
        state.setdefault("pendingCandidate", None)
        state.setdefault("activeShot", None)
        return state

    def _save_state(self, root: Path, state: Mapping[str, Any]) -> None:
        self._state_dir(root).mkdir(parents=True, exist_ok=True)
        self._state_path(root).write_text(json.dumps(dict(state), indent=2), encoding="utf-8")

    def _state_dir(self, root: Path) -> Path:
        return root / "analysis_live_pipeline"

    def _state_path(self, root: Path) -> Path:
        return self._state_dir(root) / "shot_boundary_detector_state.json"

    def _result(
        self,
        root: Path,
        state_path: Path,
        state: Mapping[str, Any],
        *,
        status: str,
        reason: str,
        confirmed_lane_lock_request_id: str = "",
    ) -> LiveShotBoundaryDetectorResult:
        return LiveShotBoundaryDetectorResult(
            session_dir=root,
            state_path=state_path,
            status=status,
            reason=reason,
            scanned_frames=0,
            yolo_frames=0,
            events_emitted=0,
            start_events_emitted=0,
            end_events_emitted=0,
            latest_scanned_frame_seq=_int(state.get("lastScannedFrameSeq"), -1),
            detector_mode=str(state.get("mode") or "idle"),
            confirmed_lane_lock_request_id=confirmed_lane_lock_request_id,
            pending_frame_seq=self._pending_frame_seq(state),
            active_window_id=self._active_window_id(state),
        )

    def _pending_frame_seq(self, state: Mapping[str, Any]) -> int | None:
        pending = state.get("pendingCandidate")
        if not isinstance(pending, Mapping):
            return None
        return _int(pending.get("frameSeq"), -1)

    def _active_window_id(self, state: Mapping[str, Any]) -> str:
        active_shot = state.get("activeShot")
        if not isinstance(active_shot, Mapping):
            return ""
        start_frame_seq = _int(active_shot.get("startFrameSeq"), -1)
        return f"shot_{start_frame_seq}" if start_frame_seq >= 0 else ""

    def _session_identity(self, artifact: LocalClipArtifact) -> tuple[str, str]:
        session_id = str(
            artifact.session_metadata.get("sessionId")
            or artifact.session_metadata.get("session_id")
            or artifact.manifest.get("sessionId")
            or artifact.manifest.get("session_id")
            or ""
        ).strip()
        shot_id = str(
            artifact.shot_metadata.get("shotId")
            or artifact.shot_metadata.get("shot_id")
            or artifact.session_metadata.get("shotId")
            or artifact.session_metadata.get("shot_id")
            or artifact.manifest.get("shotId")
            or artifact.manifest.get("shot_id")
            or ""
        ).strip()
        if not session_id:
            raise RuntimeError("Cannot auto-detect shot boundaries without a session id.")
        if not shot_id:
            raise RuntimeError("Cannot auto-detect shot boundaries without a stream shot id.")
        return session_id, shot_id

    def _fps_for_artifact(self, artifact: LocalClipArtifact) -> float:
        fps = float(artifact.video_info.fps or 0.0)
        if fps <= 0.0:
            fps = _float(
                artifact.session_metadata.get("actualSourceFps")
                or artifact.session_metadata.get("requestedFps")
                or artifact.session_metadata.get("fps"),
                30.0,
            )
        return max(fps, 1.0)

    def _metadata_at_or_after_frame_seq(
        self,
        frame_metadata: list[dict[str, Any]],
        target_frame_seq: int,
    ) -> dict[str, Any] | None:
        for metadata in frame_metadata:
            if self._frame_seq(metadata, -1) >= int(target_frame_seq):
                return metadata
        return frame_metadata[-1] if frame_metadata else None

    def _frame_seq(self, metadata: Mapping[str, Any], fallback: int) -> int:
        return _int(metadata.get("frameSeq"), int(fallback))

    def _time_us(self, metadata: Mapping[str, Any]) -> int:
        if "ptsUs" in metadata:
            return _int(metadata.get("ptsUs"))
        return _int(metadata.get("cameraTimestampUs"))

    def _elapsed_since_candidate_seconds(
        self,
        candidate: Mapping[str, Any],
        current_metadata: Mapping[str, Any],
        current_frame_seq: int,
        fps: float,
    ) -> float:
        candidate_time_us = _int(candidate.get("ptsUs"), -1)
        current_time_us = self._time_us(current_metadata)
        if candidate_time_us >= 0 and current_time_us >= candidate_time_us:
            return (current_time_us - candidate_time_us) / 1_000_000.0
        return max(0.0, (int(current_frame_seq) - _int(candidate.get("frameSeq"))) / max(float(fps), 1.0))

    def _elapsed_since_active_seconds(
        self,
        active_shot: Mapping[str, Any],
        current_metadata: Mapping[str, Any],
        current_frame_seq: int,
        fps: float,
    ) -> float:
        start_time_us = _int(active_shot.get("startPtsUs"), -1)
        current_time_us = self._time_us(current_metadata)
        if start_time_us >= 0 and current_time_us >= start_time_us:
            return (current_time_us - start_time_us) / 1_000_000.0
        return max(0.0, (int(current_frame_seq) - _int(active_shot.get("startFrameSeq"))) / max(float(fps), 1.0))
