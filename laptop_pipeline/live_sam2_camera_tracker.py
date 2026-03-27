import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    from .path_config import DEFAULT_CHECKPOINTS_ROOT, DEFAULT_SAM2_ROOT
except ImportError:
    from path_config import DEFAULT_CHECKPOINTS_ROOT, DEFAULT_SAM2_ROOT


def bbox_from_mask(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def centroid_from_mask(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def read_jpeg_frame(frame_dir: Path, frame_idx: int) -> np.ndarray:
    frame_path = frame_dir / f"{frame_idx:06d}.jpg"
    frame_bgr = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
    if frame_bgr is None:
        raise RuntimeError(f"Could not read frame {frame_path}")
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


@dataclass
class LiveSam2CameraConfig:
    sam2_root: Path = DEFAULT_SAM2_ROOT
    checkpoint: Path = DEFAULT_CHECKPOINTS_ROOT / "sam2.1_hiera_tiny.pt"
    model_cfg: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    object_id: int = 1
    use_vos_optimized: bool = False

    @property
    def cache_root(self) -> Path:
        return self.sam2_root / "cache"

    @property
    def repo_root(self) -> Path:
        return self.sam2_root


class LiveSam2CameraTracker:
    def __init__(self, config: Optional[LiveSam2CameraConfig] = None):
        self.config = config or LiveSam2CameraConfig()
        self._torch = None
        self._predictor = None
        self._build_seconds = None
        self._device = None
        self.reset_session()

    def reset_session(self):
        self.active = False
        self.seed_frame_idx: Optional[int] = None
        self.next_frame_idx: Optional[int] = None
        self.video_width: Optional[int] = None
        self.video_height: Optional[int] = None
        self.results: dict[int, dict] = {}
        self.init_seconds = 0.0
        self.catchup_seconds = 0.0
        self.live_track_seconds = 0.0
        self.catchup_frames = 0
        self.live_frames = 0

    def _ensure_loaded(self):
        if self._predictor is not None:
            return

        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the live SAM2 camera tracker.")

        self._torch = torch
        self._device = torch.device("cuda")
        if torch.cuda.get_device_properties(0).major >= 8:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

        triton_cache_dir = self.config.cache_root / "t"
        torchinductor_cache_dir = self.config.cache_root / "i"
        triton_cache_dir.mkdir(parents=True, exist_ok=True)
        torchinductor_cache_dir.mkdir(parents=True, exist_ok=True)

        sys.path.insert(0, str(self.config.repo_root))
        os.chdir(self.config.repo_root)
        os.environ.setdefault("TRITON_ALLOWED_BACKENDS", "nvidia")
        os.environ.setdefault("TRITON_CACHE_DIR", str(triton_cache_dir))
        os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(torchinductor_cache_dir))

        build_start = time.perf_counter()
        from sam2.build_sam import build_sam2_camera_predictor

        self._predictor = build_sam2_camera_predictor(
            self.config.model_cfg,
            str(self.config.checkpoint),
            device=self._device,
            vos_optimized=self.config.use_vos_optimized,
        )
        self._build_seconds = time.perf_counter() - build_start

    def start_from_seed(self, seed_frame_idx: int, seed_frame_rgb: np.ndarray, seed: dict):
        self._ensure_loaded()
        self.reset_session()
        self.seed_frame_idx = seed_frame_idx
        self.next_frame_idx = seed_frame_idx + 1
        self.video_height, self.video_width = seed_frame_rgb.shape[:2]
        box = np.array([[seed["box"][0], seed["box"][1]], [seed["box"][2], seed["box"][3]]], dtype=np.float32)

        init_start = time.perf_counter()
        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            self._predictor.load_first_frame(seed_frame_rgb)
            _, obj_ids, mask_logits = self._predictor.add_new_prompt(frame_idx=0, obj_id=self.config.object_id, bbox=box)
        self.init_seconds = time.perf_counter() - init_start
        self.active = True
        self._store_output(seed_frame_idx, obj_ids, mask_logits)

    def catch_up_from_frame_dir(self, frame_dir: Path, end_frame_idx: int):
        if not self.active or self.next_frame_idx is None or end_frame_idx < self.next_frame_idx:
            return
        start = time.perf_counter()
        processed = 0
        for frame_idx in range(self.next_frame_idx, end_frame_idx + 1):
            self.track_frame(frame_idx, read_jpeg_frame(frame_dir, frame_idx), count_as_live=False)
            processed += 1
        self.catchup_seconds += time.perf_counter() - start
        self.catchup_frames += processed

    def track_frame(self, absolute_frame_idx: int, frame_rgb: np.ndarray, count_as_live: bool = True):
        if not self.active:
            raise RuntimeError("Live SAM2 camera tracker has not been started.")
        if absolute_frame_idx < self.next_frame_idx:
            return
        if absolute_frame_idx > self.next_frame_idx:
            raise RuntimeError(f"Live tracker expected frame {self.next_frame_idx} but received {absolute_frame_idx}")

        start = time.perf_counter()
        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            obj_ids, mask_logits = self._predictor.track(frame_rgb)
        elapsed = time.perf_counter() - start
        if count_as_live:
            self.live_track_seconds += elapsed
            self.live_frames += 1
        self._store_output(absolute_frame_idx, obj_ids, mask_logits)
        self.next_frame_idx = absolute_frame_idx + 1

    def _store_output(self, absolute_frame_idx: int, obj_ids, mask_logits):
        if len(obj_ids) == 0:
            self.results[absolute_frame_idx] = {"object_id": self.config.object_id, "bbox": None, "centroid": None, "area": 0, "mask": None}
            return
        mask = (mask_logits[0] > 0.0).permute(1, 2, 0).cpu().numpy().astype(bool)
        mask2d = mask[..., 0]
        self.results[absolute_frame_idx] = {
            "object_id": int(obj_ids[0]),
            "bbox": bbox_from_mask(mask2d),
            "centroid": centroid_from_mask(mask2d),
            "area": int(mask2d.sum()),
            "mask": mask2d,
        }

    def write_outputs(self, output_dir: Path, total_frames: Optional[int] = None, save_preview: bool = False, frame_dir: Optional[Path] = None, preview_fps: float = 30.0):
        if self.seed_frame_idx is None:
            raise RuntimeError("Live tracker was never started from a seed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "track.csv"
        max_frame = max(self.results) if self.results else self.seed_frame_idx
        last_frame = max(total_frames - 1, max_frame) if total_frames is not None else max_frame

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["frame_idx", "object_id", "present", "area", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "centroid_x", "centroid_y"])
            for frame_idx in range(self.seed_frame_idx, last_frame + 1):
                row = self.results.get(frame_idx)
                if row is None or row["bbox"] is None:
                    writer.writerow([frame_idx, self.config.object_id, 0, 0, "", "", "", "", "", ""])
                    continue
                x1, y1, x2, y2 = row["bbox"]
                cx, cy = row["centroid"]
                writer.writerow([frame_idx, row["object_id"], 1, row["area"], x1, y1, x2, y2, f"{cx:.2f}", f"{cy:.2f}"])

        preview_seconds = 0.0
        preview_path = output_dir / "preview.mp4"
        if save_preview and frame_dir is not None and self.video_width and self.video_height:
            preview_start = time.perf_counter()
            writer = cv2.VideoWriter(str(preview_path), cv2.VideoWriter_fourcc(*"mp4v"), preview_fps, (self.video_width, self.video_height))
            if not writer.isOpened():
                raise RuntimeError(f"Could not open preview writer for {preview_path}")
            for frame_idx in range(self.seed_frame_idx, last_frame + 1):
                frame_rgb = read_jpeg_frame(frame_dir, frame_idx)
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                row = self.results.get(frame_idx)
                if row is not None and row["mask"] is not None and row["mask"].any():
                    overlay = np.zeros_like(frame_bgr)
                    overlay[row["mask"]] = (0, 80, 255)
                    frame_bgr = cv2.addWeighted(frame_bgr, 1.0, overlay, 0.3, 0)
                if row is not None and row["bbox"] is not None:
                    x1, y1, x2, y2 = row["bbox"]
                    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (255, 255, 0), 3)
                writer.write(frame_bgr)
            writer.release()
            preview_seconds = time.perf_counter() - preview_start

        found_frames = [frame_idx for frame_idx, row in self.results.items() if row["bbox"] is not None]
        total_seconds = float(self._build_seconds or 0.0) + self.init_seconds + self.catchup_seconds + self.live_track_seconds + preview_seconds
        summary_path = output_dir / "summary.txt"
        with summary_path.open("w", encoding="utf-8") as handle:
            handle.write("mode=live_camera_predictor\n")
            handle.write(f"checkpoint={self.config.checkpoint}\n")
            handle.write(f"model_cfg={self.config.model_cfg}\n")
            handle.write(f"seed_frame={self.seed_frame_idx}\n")
            handle.write(f"vos_optimized={self.config.use_vos_optimized}\n")
            handle.write(f"build_seconds={float(self._build_seconds or 0.0):.3f}\n")
            handle.write(f"init_seconds={self.init_seconds:.3f}\n")
            handle.write(f"catchup_seconds={self.catchup_seconds:.3f}\n")
            handle.write(f"live_track_seconds={self.live_track_seconds:.3f}\n")
            handle.write(f"preview_seconds={preview_seconds:.3f}\n")
            handle.write(f"total_seconds={total_seconds:.3f}\n")
            handle.write(f"catchup_frames={self.catchup_frames}\n")
            handle.write(f"live_frames={self.live_frames}\n")
            handle.write(f"tracked_frames={len(found_frames)}\n")
            if found_frames:
                handle.write(f"first_tracked_frame={min(found_frames)}\n")
                handle.write(f"last_tracked_frame={max(found_frames)}\n")

        return {
            "track_csv": str(csv_path),
            "summary_path": str(summary_path),
            "preview_path": str(preview_path) if save_preview else "",
            "tracked_frames": len(found_frames),
            "first_tracked_frame": min(found_frames) if found_frames else None,
            "last_tracked_frame": max(found_frames) if found_frames else None,
            "build_seconds": float(self._build_seconds or 0.0),
            "init_seconds": self.init_seconds,
            "catchup_seconds": self.catchup_seconds,
            "live_track_seconds": self.live_track_seconds,
            "total_seconds": total_seconds,
        }
