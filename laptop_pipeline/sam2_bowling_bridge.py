import asyncio
import csv
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    from .live_sam2_camera_tracker import LiveSam2CameraTracker
    from .online_classical_seed import OnlineClassicalSeedConfig, OnlineClassicalSeedDetector
    from .path_config import LAPTOP_PIPELINE_ROOT
    from .warm_sam2_tracker import WarmSam2Tracker
except ImportError:
    from live_sam2_camera_tracker import LiveSam2CameraTracker
    from online_classical_seed import OnlineClassicalSeedConfig, OnlineClassicalSeedDetector
    from path_config import LAPTOP_PIPELINE_ROOT
    from warm_sam2_tracker import WarmSam2Tracker


@dataclass
class Sam2BridgeConfig:
    runs_root: Path = LAPTOP_PIPELINE_ROOT / "runs"
    save_preview: bool = False
    pre_roll_frames: int = 12
    analysis_mode: str = "live"
    seed_config: OnlineClassicalSeedConfig = field(default_factory=OnlineClassicalSeedConfig)


class JpegShotRecorder:
    def __init__(self, output_dir: Path, fps: float, frame_size: tuple[int, int]):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.output_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.output_dir / "frames.jsonl"
        self.manifest_path = self.output_dir / "manifest.json"
        self.metadata_handle = self.metadata_path.open("w", encoding="utf-8")
        self.frame_count = 0
        self.fps = float(max(fps, 1.0))
        self.frame_size = frame_size

    def write_frame(self, frame_packet) -> int:
        local_frame_idx = self.frame_count
        frame_path = self.frames_dir / f"{local_frame_idx:06d}.jpg"
        frame_path.write_bytes(frame_packet.encoded_bytes)
        self.metadata_handle.write(
            json.dumps(
                {
                    "local_frame_idx": local_frame_idx,
                    "source_frame_id": frame_packet.frame_id,
                    "timestamp_us": frame_packet.timestamp_us,
                    "shot_id": frame_packet.shot_id,
                    "camera_position": frame_packet.camera_position,
                    "camera_rotation": frame_packet.camera_rotation,
                    "file_name": frame_path.name,
                }
            )
            + "\n"
        )
        self.frame_count += 1
        return local_frame_idx

    def close(self):
        if self.metadata_handle is not None:
            self.metadata_handle.close()
            self.metadata_handle = None
        self.manifest_path.write_text(
            json.dumps(
                {
                    "fps": self.fps,
                    "frame_width": self.frame_size[0],
                    "frame_height": self.frame_size[1],
                    "frame_count": self.frame_count,
                    "frames_dir": str(self.frames_dir),
                    "metadata_path": str(self.metadata_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class Sam2BowlingBridge:
    def __init__(self, config: Optional[Sam2BridgeConfig] = None):
        self.config = config or Sam2BridgeConfig()
        self.warm_tracker = WarmSam2Tracker()
        self.live_tracker = LiveSam2CameraTracker()
        self.active_recorder: Optional[JpegShotRecorder] = None
        self.active_seed_detector: Optional[OnlineClassicalSeedDetector] = None
        self.active_shot_id: Optional[str] = None
        self.active_session_id: Optional[str] = None
        self.active_shot_dir: Optional[Path] = None
        self.active_fps = 30.0
        self.live_tracking_started = False
        self.live_tracking_failed = False
        self.pre_roll = deque(maxlen=self.config.pre_roll_frames)
        self.analysis_task: Optional[asyncio.Task] = None
        self.status_events: list[dict] = []

    def _emit_status(self, stage: str, **payload):
        event = {"kind": "tracker_status", "stage": stage}
        event.update(payload)
        self.status_events.append(event)

    def drain_status_events(self):
        events = list(self.status_events)
        self.status_events.clear()
        return events

    def buffer_frame(self, frame_packet):
        self.pre_roll.append(frame_packet)

    def start_shot(self, session_id: str, shot_id: str, fps: float, frame_size: tuple[int, int], decode_frame: Callable):
        self.finish_active_recorder()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_dir = self.config.runs_root / f"{session_id}_{shot_id}_{timestamp}"
        raw_dir = shot_dir / "raw"

        self.active_recorder = JpegShotRecorder(raw_dir, fps=fps, frame_size=frame_size)
        self.active_seed_detector = OnlineClassicalSeedDetector(frame_width=frame_size[0], frame_height=frame_size[1], config=self.config.seed_config)
        self.active_shot_id = shot_id
        self.active_session_id = session_id
        self.active_shot_dir = shot_dir
        self.active_fps = float(max(fps, 1.0))
        self.live_tracker.reset_session()
        self.live_tracking_started = False
        self.live_tracking_failed = False
        self._emit_status("recording_shot", shot_id=shot_id)

        for buffered in list(self.pre_roll):
            self._ingest_active_frame(buffered, decode_frame)

    def add_frame(self, frame_packet, decode_frame: Callable):
        if self.active_recorder is None:
            return
        self._ingest_active_frame(frame_packet, decode_frame)

    def _ingest_active_frame(self, frame_packet, decode_frame: Callable):
        local_frame_idx = self.active_recorder.write_frame(frame_packet)
        frame_rgb = None
        if self.active_seed_detector is None:
            return

        if self.active_seed_detector.should_sample(local_frame_idx):
            image_bgr = decode_frame(frame_packet)
            frame_rgb = image_bgr[:, :, ::-1]
            event = self.active_seed_detector.process_frame(local_frame_idx, frame_rgb)
            if event is not None:
                event.update({"shot_id": self.active_shot_id, "local_frame_idx": local_frame_idx})
                self.status_events.append(event)
                self._maybe_start_live_tracker(local_frame_idx)

        if self.live_tracking_started and not self.live_tracking_failed and self.live_tracker.next_frame_idx is not None and local_frame_idx >= self.live_tracker.next_frame_idx:
            if frame_rgb is None:
                image_bgr = decode_frame(frame_packet)
                frame_rgb = image_bgr[:, :, ::-1]
            try:
                self.live_tracker.track_frame(local_frame_idx, frame_rgb, count_as_live=True)
            except Exception as exc:
                self.live_tracking_failed = True
                self._emit_status("live_tracking_failed", shot_id=self.active_shot_id, message=str(exc))

    def _maybe_start_live_tracker(self, local_frame_idx: int):
        if self.live_tracking_started or self.live_tracking_failed:
            return
        if self.active_seed_detector is None or self.active_recorder is None:
            return
        seed = self.active_seed_detector.seed
        if seed is None:
            return
        seed_frame_idx = int(seed["frame_idx"])
        seed_frame_rgb = self.active_seed_detector.sampled_frame_cache.get(seed_frame_idx)
        if seed_frame_rgb is None:
            self.live_tracking_failed = True
            self._emit_status("live_tracking_failed", shot_id=self.active_shot_id, message=f"seed frame {seed_frame_idx} not cached")
            return
        try:
            self.live_tracker.start_from_seed(seed_frame_idx, seed_frame_rgb, seed)
            self.live_tracker.catch_up_from_frame_dir(self.active_recorder.frames_dir, local_frame_idx)
            self.live_tracking_started = True
            self._emit_status("live_tracking_started", shot_id=self.active_shot_id, seed_frame=seed_frame_idx, current_frame=local_frame_idx)
        except Exception as exc:
            self.live_tracking_failed = True
            self._emit_status("live_tracking_failed", shot_id=self.active_shot_id, message=str(exc))

    def finish_active_recorder(self):
        if self.active_recorder is not None:
            self.active_recorder.close()
            self.active_recorder = None

    async def end_shot_and_launch(self):
        if self.active_recorder is None or self.active_shot_dir is None:
            return None

        recorder = self.active_recorder
        self.finish_active_recorder()
        shot_dir = self.active_shot_dir
        session_id = self.active_session_id
        shot_id = self.active_shot_id
        seed_detector = self.active_seed_detector
        fps = self.active_fps
        total_frames = recorder.frame_count

        self.active_shot_dir = None
        self.active_session_id = None
        self.active_shot_id = None
        self.active_seed_detector = None
        self._emit_status("analyzing_shot", shot_id=shot_id)

        self.analysis_task = asyncio.create_task(self._run_pipeline(session_id, shot_id, shot_dir, seed_detector, fps, total_frames))
        return self.analysis_task

    async def _run_pipeline(self, session_id: str, shot_id: str, shot_dir: Path, seed_detector: Optional[OnlineClassicalSeedDetector], fps: float, total_frames: int):
        analysis_dir = shot_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        raw_frames_dir = shot_dir / "raw" / "frames"

        if self.config.analysis_mode == "synthetic":
            synthetic_result = self._build_synthetic_result(session_id, shot_id, shot_dir, analysis_dir, raw_frames_dir, fps, total_frames)
            (shot_dir / "synthetic_result.json").write_text(json.dumps(synthetic_result, indent=2), encoding="utf-8")
            return synthetic_result

        if seed_detector is None:
            return {"kind": "shot_result", "success": False, "session_id": session_id, "shot_id": shot_id, "failure_reason": "seed_detector_missing"}

        seed = await asyncio.to_thread(seed_detector.write_outputs, analysis_dir)
        if seed is None:
            return {"kind": "shot_result", "success": False, "session_id": session_id, "shot_id": shot_id, "failure_reason": "no_seed_found", "analysis_dir": str(analysis_dir), "raw_frames_dir": str(raw_frames_dir)}

        sam2_output_dir = analysis_dir / "sam2"
        if self.live_tracking_started and not self.live_tracking_failed and self.live_tracker.seed_frame_idx is not None:
            live_summary = await asyncio.to_thread(self.live_tracker.write_outputs, sam2_output_dir, total_frames, self.config.save_preview, raw_frames_dir, fps)
            (shot_dir / "live_sam2_summary.json").write_text(json.dumps(live_summary, indent=2), encoding="utf-8")
        else:
            warm_summary = await asyncio.to_thread(self.warm_tracker.track_from_seed, str(raw_frames_dir), seed, sam2_output_dir, not self.config.save_preview, 0, fps)
            (shot_dir / "warm_sam2_summary.json").write_text(json.dumps(warm_summary, indent=2), encoding="utf-8")
        return self._build_result(session_id, shot_id, shot_dir, analysis_dir)

    def _build_result(self, session_id: str, shot_id: str, shot_dir: Path, analysis_dir: Path):
        seed_path = analysis_dir / "seed.json"
        track_path = analysis_dir / "sam2" / "track.csv"
        summary_path = analysis_dir / "sam2" / "summary.txt"
        preview_path = analysis_dir / "sam2" / "preview.mp4"
        seed = json.loads(seed_path.read_text(encoding="utf-8")) if seed_path.exists() else None
        summary = parse_summary(summary_path) if summary_path.exists() else {}
        path_samples = parse_track_csv(track_path) if track_path.exists() else []
        raw_frames_dir = shot_dir / "raw" / "frames"
        return {
            "kind": "shot_result",
            "success": len(path_samples) > 0,
            "session_id": session_id,
            "shot_id": shot_id,
            "raw_source": str(raw_frames_dir),
            "raw_frames_dir": str(raw_frames_dir),
            "analysis_dir": str(analysis_dir),
            "warm_sam2_summary": str(shot_dir / "warm_sam2_summary.json") if (shot_dir / "warm_sam2_summary.json").exists() else "",
            "live_sam2_summary": str(shot_dir / "live_sam2_summary.json") if (shot_dir / "live_sam2_summary.json").exists() else "",
            "preview_path": str(preview_path) if preview_path.exists() else "",
            "seed": seed,
            "summary": summary,
            "path_samples": path_samples,
            "tracked_frames": len(path_samples),
            "first_frame": path_samples[0]["frame_idx"] if path_samples else None,
            "last_frame": path_samples[-1]["frame_idx"] if path_samples else None,
        }

    def _build_synthetic_result(self, session_id: str, shot_id: str, shot_dir: Path, analysis_dir: Path, raw_frames_dir: Path, fps: float, total_frames: int):
        sample_count = max(12, min(36, total_frames if total_frames > 0 else 24))
        path_samples = []
        for index in range(sample_count):
            t = index / float(max(sample_count - 1, 1))
            centroid_x = 640.0 + 180.0 * (t - 0.5)
            centroid_y = 760.0 - 420.0 * t + 55.0 * (t * (1.0 - t))
            half_size = 52.0 - 18.0 * t
            path_samples.append(
                {
                    "frame_idx": index,
                    "centroid_x": centroid_x,
                    "centroid_y": centroid_y,
                    "bbox_x1": centroid_x - half_size,
                    "bbox_y1": centroid_y - half_size,
                    "bbox_x2": centroid_x + half_size,
                    "bbox_y2": centroid_y + half_size,
                    "area": float((half_size * 2.0) ** 2),
                }
            )

        summary = {
            "mode": "synthetic",
            "fps": f"{fps:.3f}",
            "total_frames": str(total_frames),
            "tracked_frames": str(len(path_samples)),
        }

        return {
            "kind": "shot_result",
            "success": True,
            "session_id": session_id,
            "shot_id": shot_id,
            "raw_source": str(raw_frames_dir),
            "raw_frames_dir": str(raw_frames_dir),
            "analysis_dir": str(analysis_dir),
            "warm_sam2_summary": "",
            "live_sam2_summary": "",
            "preview_path": "",
            "seed": {
                "frame_idx": 0,
                "box": [
                    path_samples[0]["bbox_x1"],
                    path_samples[0]["bbox_y1"],
                    path_samples[0]["bbox_x2"],
                    path_samples[0]["bbox_y2"],
                ],
                "center": [path_samples[0]["centroid_x"], path_samples[0]["centroid_y"]],
                "initializer": "synthetic",
            },
            "summary": summary,
            "path_samples": path_samples,
            "tracked_frames": len(path_samples),
            "first_frame": path_samples[0]["frame_idx"],
            "last_frame": path_samples[-1]["frame_idx"],
        }


def parse_summary(path: Path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def parse_track_csv(path: Path):
    samples = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("present") != "1":
                continue
            samples.append(
                {
                    "frame_idx": int(row["frame_idx"]),
                    "centroid_x": float(row["centroid_x"]),
                    "centroid_y": float(row["centroid_y"]),
                    "bbox_x1": float(row["bbox_x1"]),
                    "bbox_y1": float(row["bbox_y1"]),
                    "bbox_x2": float(row["bbox_x2"]),
                    "bbox_y2": float(row["bbox_y2"]),
                    "area": float(row["area"]),
                }
            )
    return samples
