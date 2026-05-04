from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

import cv2
import numpy as np

from laptop_receiver.standalone_warm_sam2_tracker import (
    DEFAULT_SAM2_CACHE_ROOT,
    DEFAULT_SAM2_CHECKPOINT,
    DEFAULT_SAM2_ROOT,
)


MASK_MEASUREMENT_TOP_WEIGHT = 0.74


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


def _bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _centroid_from_mask(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def _mask_quantile_point(mask: np.ndarray, q: float, band_fraction: float = 0.18) -> tuple[float, float] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None

    y_value = float(np.quantile(ys.astype(np.float64), float(q)))
    height = max(float(ys.max() - ys.min() + 1), 1.0)
    band = max(2.0, height * float(band_fraction))
    if float(q) <= 0.5:
        selected = ys.astype(np.float64) <= y_value + band
    else:
        selected = ys.astype(np.float64) >= y_value - band
    if not np.any(selected):
        return float(xs.mean()), y_value
    return float(xs[selected].mean()), y_value


def _largest_contour_from_mask(mask: np.ndarray) -> list[list[int]]:
    mask_u8 = mask.astype(np.uint8) * 255
    contours, _hierarchy = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    contour = max(contours, key=cv2.contourArea)
    return [[int(point[0][0]), int(point[0][1])] for point in contour]


def _equivalent_radius_from_mask(mask: np.ndarray) -> float:
    area = float(mask.sum())
    if area <= 0.0:
        return 0.0
    return float(np.sqrt(area / np.pi))


def _mask_quality_from_area(area: int) -> float:
    if int(area) <= 0:
        return 0.0
    return max(0.25, min(1.0, float(np.sqrt(float(area))) / 45.0))


def _mask_from_logits(mask_logits: Any) -> np.ndarray | None:
    if len(mask_logits) == 0:
        return None
    tensor = mask_logits[0]
    while getattr(tensor, "ndim", 0) > 2:
        tensor = tensor[0]
    return tensor.detach().float().cpu().numpy() > 0.0


@dataclass(frozen=True)
class LiveCameraSam2Config:
    sam2_root: Path = DEFAULT_SAM2_ROOT
    cache_root: Path = DEFAULT_SAM2_CACHE_ROOT
    checkpoint: Path = DEFAULT_SAM2_CHECKPOINT
    model_cfg: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    device: str = "cuda"
    object_id: int = 1
    vos_optimized: bool = False
    max_track_seconds: float = 5.0
    lost_track_grace_frames: int = 5

    @property
    def repo_root(self) -> Path:
        return self.sam2_root


@dataclass(frozen=True)
class LiveCameraSam2TrackResult:
    kind: str
    success: bool
    failure_reason: str
    analysis_dir: str
    seed_path: str
    track_csv_path: str
    mask_contours_path: str
    tracked_frames: int
    first_frame: int | None
    last_frame: int | None
    source_frame_idx_start: int
    source_frame_idx_end: int | None
    first_frame_seq: int | None
    last_frame_seq: int | None
    seed: dict[str, Any] | None
    stop_reason: str
    summary: dict[str, Any]
    timing: dict[str, float | int | None]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LiveCameraSam2TrackResult":
        return cls(
            kind=str(payload.get("kind") or ""),
            success=bool(payload.get("success")),
            failure_reason=str(payload.get("failure_reason") or payload.get("failureReason") or ""),
            analysis_dir=str(payload.get("analysis_dir") or payload.get("analysisDir") or ""),
            seed_path=str(payload.get("seed_path") or payload.get("seedPath") or ""),
            track_csv_path=str(payload.get("track_csv_path") or payload.get("trackCsvPath") or ""),
            mask_contours_path=str(payload.get("mask_contours_path") or payload.get("maskContoursPath") or ""),
            tracked_frames=_int(payload.get("tracked_frames") or payload.get("trackedFrames")),
            first_frame=payload.get("first_frame") if payload.get("first_frame") is not None else payload.get("firstFrame"),
            last_frame=payload.get("last_frame") if payload.get("last_frame") is not None else payload.get("lastFrame"),
            source_frame_idx_start=_int(payload.get("source_frame_idx_start") or payload.get("sourceFrameIdxStart")),
            source_frame_idx_end=(
                _int(payload.get("source_frame_idx_end") or payload.get("sourceFrameIdxEnd"))
                if (payload.get("source_frame_idx_end") is not None or payload.get("sourceFrameIdxEnd") is not None)
                else None
            ),
            first_frame_seq=(
                _int(payload.get("first_frame_seq") or payload.get("firstFrameSeq"))
                if (payload.get("first_frame_seq") is not None or payload.get("firstFrameSeq") is not None)
                else None
            ),
            last_frame_seq=(
                _int(payload.get("last_frame_seq") or payload.get("lastFrameSeq"))
                if (payload.get("last_frame_seq") is not None or payload.get("lastFrameSeq") is not None)
                else None
            ),
            seed=dict(payload.get("seed")) if isinstance(payload.get("seed"), Mapping) else None,
            stop_reason=str(payload.get("stop_reason") or payload.get("stopReason") or ""),
            summary=dict(payload.get("summary")) if isinstance(payload.get("summary"), Mapping) else {},
            timing=dict(payload.get("timing")) if isinstance(payload.get("timing"), Mapping) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveCameraSam2Tracker:
    def __init__(self, config: LiveCameraSam2Config | None = None) -> None:
        self.config = config or LiveCameraSam2Config()
        self._torch: Any | None = None
        self._predictor: Any | None = None
        self._device: Any | None = None
        self._build_seconds: float | None = None
        self._reset_active()

    @property
    def active(self) -> bool:
        return bool(self._active)

    @property
    def seed_frame_index(self) -> int | None:
        return self._seed_frame_index

    def warm(self) -> None:
        self._ensure_loaded()

    def start_from_seed(
        self,
        *,
        frame_index: int,
        frame_seq: int,
        image_bgr: Any,
        seed: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._ensure_loaded()
        self._reset_active()
        self._active = True
        self._seed_frame_index = int(frame_index)
        self._seed_frame_seq = int(frame_seq)
        self._next_frame_index = int(frame_index) + 1
        self._seed = dict(seed)
        self._seed["frame_idx"] = int(frame_index)
        self._seed["frame_seq"] = int(frame_seq)
        self._started_at = time.perf_counter()

        assert self._torch is not None
        assert self._predictor is not None
        init_start = time.perf_counter()
        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            if hasattr(self._predictor, "frame_idx"):
                self._predictor.frame_idx = 0
            self._predictor.load_first_frame(image_bgr)
            _frame_idx, obj_ids, mask_logits = self._predictor.add_new_prompt(
                frame_idx=0,
                obj_id=int(self.config.object_id),
                bbox=[float(value) for value in self._seed["box"]],
            )
        self._init_seconds += time.perf_counter() - init_start
        self._store_output(
            frame_index=int(frame_index),
            frame_seq=int(frame_seq),
            obj_ids=obj_ids,
            mask_logits=mask_logits,
            metadata=metadata or {},
            detector_confidence=_float(self._seed.get("detector_confidence")),
        )

    def track_frame(self, *, frame_index: int, frame_seq: int, image_bgr: Any, metadata: Mapping[str, Any] | None = None) -> None:
        if not self._active:
            raise RuntimeError("Camera SAM2 tracker has not been started from a YOLO seed.")
        if self._next_frame_index is None:
            raise RuntimeError("Camera SAM2 tracker next frame index is missing.")
        if int(frame_index) < int(self._next_frame_index):
            return
        if int(frame_index) > int(self._next_frame_index):
            raise RuntimeError(f"Camera SAM2 expected frame {self._next_frame_index}, received {frame_index}.")

        assert self._torch is not None
        assert self._predictor is not None
        track_start = time.perf_counter()
        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            obj_ids, mask_logits = self._predictor.track(image_bgr)
        self._track_seconds += time.perf_counter() - track_start
        self._track_calls += 1
        self._store_output(
            frame_index=int(frame_index),
            frame_seq=int(frame_seq),
            obj_ids=obj_ids,
            mask_logits=mask_logits,
            metadata=metadata or {},
            detector_confidence=None,
        )
        self._next_frame_index = int(frame_index) + 1

    def stop_reason(self, *, fps: float) -> str:
        if not self._active or self._seed_frame_index is None:
            return ""
        last_frame_index = self._last_frame_index if self._last_frame_index is not None else self._seed_frame_index
        elapsed_frames = int(last_frame_index) - int(self._seed_frame_index)
        max_track_frames = int(round(float(self.config.max_track_seconds) * max(float(fps), 1.0)))
        if max_track_frames > 0 and elapsed_frames >= max_track_frames:
            return "camera_sam2_fixed_duration"
        if (
            int(self.config.lost_track_grace_frames) > 0
            and self._consecutive_missing_frames >= int(self.config.lost_track_grace_frames)
        ):
            return "camera_sam2_lost_tracking"
        return ""

    def finish(
        self,
        *,
        output_dir: Path,
        stop_reason: str,
        source_frame_idx_end: int | None,
    ) -> LiveCameraSam2TrackResult:
        if self._seed_frame_index is None:
            raise RuntimeError("Cannot finish camera SAM2 tracking before it has been seeded.")

        output_dir.mkdir(parents=True, exist_ok=True)
        seed_path = output_dir / "seed.json"
        track_csv_path = output_dir / "track.csv"
        mask_contours_path = output_dir / "mask_contours.jsonl"
        result_path = output_dir / "camera_sam2_result.json"
        summary_path = output_dir / "summary.json"

        seed = dict(self._seed or {})
        seed_path.write_text(json.dumps(seed, indent=2), encoding="utf-8")

        fieldnames = [
            "frame_idx",
            "source_frame_idx",
            "frame_seq",
            "sam_local_frame_idx",
            "object_id",
            "present",
            "area",
            "bbox_x1",
            "bbox_y1",
            "bbox_x2",
            "bbox_y2",
            "centroid_x",
            "centroid_y",
            "mask_top10_x",
            "mask_top10_y",
            "mask_measurement_x",
            "mask_measurement_y",
            "mask_equivalent_radius_px",
            "mask_quality",
            "detector_confidence",
            "camera_timestamp_us",
            "pts_us",
        ]
        with track_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in self._rows:
                writer.writerow(row)

        with mask_contours_path.open("w", encoding="utf-8") as handle:
            for contour_row in self._contour_rows:
                handle.write(json.dumps(contour_row, separators=(",", ":")) + "\n")

        present_rows = [row for row in self._rows if _int(row.get("present")) == 1]
        present_frames = [_int(row.get("frame_idx")) for row in present_rows]
        present_frame_seqs = [_int(row.get("frame_seq")) for row in present_rows]
        tracked_frames = len(present_frames)
        total_seconds = (
            float(self._build_seconds or 0.0)
            + float(self._init_seconds)
            + float(self._track_seconds)
        )
        summary = {
            "mode": "live_camera_predictor",
            "checkpoint": str(self.config.checkpoint),
            "modelCfg": str(self.config.model_cfg),
            "seedFrame": int(self._seed_frame_index),
            "seedFrameSeq": self._seed_frame_seq,
            "stopReason": str(stop_reason),
            "vosOptimized": bool(self.config.vos_optimized),
            "maxTrackSeconds": float(self.config.max_track_seconds),
            "lostTrackGraceFrames": int(self.config.lost_track_grace_frames),
            "trackCalls": int(self._track_calls),
            "maskContourFrames": len(self._contour_rows),
            "maskMeasurementTopWeight": float(MASK_MEASUREMENT_TOP_WEIGHT),
        }
        result = LiveCameraSam2TrackResult(
            kind="live_camera_sam2_track_result",
            success=tracked_frames > 0,
            failure_reason="" if tracked_frames > 0 else "camera_sam2_no_tracked_frames",
            analysis_dir=str(output_dir),
            seed_path=str(seed_path),
            track_csv_path=str(track_csv_path),
            mask_contours_path=str(mask_contours_path),
            tracked_frames=tracked_frames,
            first_frame=min(present_frames) if present_frames else None,
            last_frame=max(present_frames) if present_frames else None,
            source_frame_idx_start=int(self._seed_frame_index),
            source_frame_idx_end=source_frame_idx_end,
            first_frame_seq=min(present_frame_seqs) if present_frame_seqs else None,
            last_frame_seq=max(present_frame_seqs) if present_frame_seqs else None,
            seed=seed,
            stop_reason=str(stop_reason),
            summary=summary,
            timing={
                "build_seconds": round(float(self._build_seconds or 0.0), 3),
                "init_seconds": round(float(self._init_seconds), 3),
                "track_seconds": round(float(self._track_seconds), 3),
                "track_calls": int(self._track_calls),
                "total_seconds": round(total_seconds, 3),
            },
        )
        result_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        summary_path.write_text(json.dumps({"summary": summary, "result": result.to_dict()}, indent=2), encoding="utf-8")
        self._reset_active()
        return result

    def _ensure_loaded(self) -> None:
        if self._predictor is not None:
            return

        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for camera SAM2 tracking.")
        if not self.config.repo_root.exists():
            raise RuntimeError(f"SAM2 repo root does not exist: {self.config.repo_root}")
        if not self.config.checkpoint.exists():
            raise RuntimeError(f"SAM2 checkpoint does not exist: {self.config.checkpoint}")

        self._torch = torch
        self._device = torch.device(str(self.config.device))
        if torch.cuda.get_device_properties(0).major >= 8:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

        triton_cache_dir = self.config.cache_root / "t"
        torchinductor_cache_dir = self.config.cache_root / "i"
        triton_cache_dir.mkdir(parents=True, exist_ok=True)
        torchinductor_cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TRITON_ALLOWED_BACKENDS", "nvidia")
        os.environ.setdefault("TRITON_CACHE_DIR", str(triton_cache_dir))
        os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(torchinductor_cache_dir))

        repo_root = str(self.config.repo_root)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        from sam2.build_sam import build_sam2_camera_predictor

        build_start = time.perf_counter()
        self._predictor = build_sam2_camera_predictor(
            str(self.config.model_cfg),
            str(self.config.checkpoint),
            device=self._device,
            vos_optimized=bool(self.config.vos_optimized),
        )
        self._build_seconds = time.perf_counter() - build_start

    def _store_output(
        self,
        *,
        frame_index: int,
        frame_seq: int,
        obj_ids: Any,
        mask_logits: Any,
        metadata: Mapping[str, Any],
        detector_confidence: float | None,
    ) -> None:
        mask = _mask_from_logits(mask_logits) if len(obj_ids) else None
        bbox = _bbox_from_mask(mask) if mask is not None else None
        centroid = _centroid_from_mask(mask) if mask is not None else None
        top10 = _mask_quantile_point(mask, 0.10) if mask is not None else None
        area = int(mask.sum()) if mask is not None else 0
        equivalent_radius = _equivalent_radius_from_mask(mask) if mask is not None else 0.0
        mask_quality = _mask_quality_from_area(area)
        present = bbox is not None
        if present:
            self._consecutive_missing_frames = 0
        else:
            self._consecutive_missing_frames += 1
        self._last_frame_index = int(frame_index)

        row = {
            "frame_idx": int(frame_index),
            "source_frame_idx": int(frame_index),
            "frame_seq": int(frame_seq),
            "sam_local_frame_idx": int(frame_index) - int(self._seed_frame_index or frame_index),
            "object_id": int(obj_ids[0]) if len(obj_ids) else int(self.config.object_id),
            "present": 1 if present else 0,
            "area": area,
            "bbox_x1": "" if bbox is None else bbox[0],
            "bbox_y1": "" if bbox is None else bbox[1],
            "bbox_x2": "" if bbox is None else bbox[2],
            "bbox_y2": "" if bbox is None else bbox[3],
            "centroid_x": "" if centroid is None else f"{centroid[0]:.2f}",
            "centroid_y": "" if centroid is None else f"{centroid[1]:.2f}",
            "mask_top10_x": "" if top10 is None else f"{top10[0]:.2f}",
            "mask_top10_y": "" if top10 is None else f"{top10[1]:.2f}",
            "mask_measurement_x": (
                ""
                if top10 is None or centroid is None
                else f"{(MASK_MEASUREMENT_TOP_WEIGHT * top10[0] + (1.0 - MASK_MEASUREMENT_TOP_WEIGHT) * centroid[0]):.2f}"
            ),
            "mask_measurement_y": (
                ""
                if top10 is None or centroid is None
                else f"{(MASK_MEASUREMENT_TOP_WEIGHT * top10[1] + (1.0 - MASK_MEASUREMENT_TOP_WEIGHT) * centroid[1]):.2f}"
            ),
            "mask_equivalent_radius_px": f"{equivalent_radius:.3f}",
            "mask_quality": f"{mask_quality:.3f}",
            "detector_confidence": "" if detector_confidence is None else f"{float(detector_confidence):.6f}",
            "camera_timestamp_us": _int(metadata.get("cameraTimestampUs")),
            "pts_us": _int(metadata.get("ptsUs")),
        }
        self._rows.append(row)
        if present and mask is not None:
            self._contour_rows.append(
                {
                    "frame_idx": int(frame_index),
                    "source_frame_idx": int(frame_index),
                    "frame_seq": int(frame_seq),
                    "object_id": int(obj_ids[0]) if len(obj_ids) else int(self.config.object_id),
                    "area": area,
                    "bbox": list(bbox) if bbox is not None else [],
                    "centroid": [] if centroid is None else [round(float(centroid[0]), 3), round(float(centroid[1]), 3)],
                    "mask_top10": [] if top10 is None else [round(float(top10[0]), 3), round(float(top10[1]), 3)],
                    "mask_measurement": (
                        []
                        if top10 is None or centroid is None
                        else [
                            round(
                                float(
                                    MASK_MEASUREMENT_TOP_WEIGHT * top10[0]
                                    + (1.0 - MASK_MEASUREMENT_TOP_WEIGHT) * centroid[0]
                                ),
                                3,
                            ),
                            round(
                                float(
                                    MASK_MEASUREMENT_TOP_WEIGHT * top10[1]
                                    + (1.0 - MASK_MEASUREMENT_TOP_WEIGHT) * centroid[1]
                                ),
                                3,
                            ),
                        ]
                    ),
                    "contour": _largest_contour_from_mask(mask),
                }
            )

    def _reset_active(self) -> None:
        self._active = False
        self._seed_frame_index: int | None = None
        self._seed_frame_seq: int | None = None
        self._next_frame_index: int | None = None
        self._last_frame_index: int | None = None
        self._seed: dict[str, Any] | None = None
        self._rows: list[dict[str, Any]] = []
        self._contour_rows: list[dict[str, Any]] = []
        self._consecutive_missing_frames = 0
        self._init_seconds = 0.0
        self._track_seconds = 0.0
        self._track_calls = 0
        self._started_at: float | None = None
