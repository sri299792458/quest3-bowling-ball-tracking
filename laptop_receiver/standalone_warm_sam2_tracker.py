from __future__ import annotations

import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image


LEGACY_PROJECT_ROOT = Path(r"C:\Users\student\Quest3BowlingBallTracking")
LEGACY_SAM2_ROOT = LEGACY_PROJECT_ROOT / "third_party" / "sam2"
LEGACY_SAM2_CACHE_ROOT = Path.home() / ".sam2_cache"
LEGACY_SAM2_CHECKPOINT = LEGACY_SAM2_ROOT / "checkpoints" / "sam2.1_hiera_tiny.pt"


def bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def centroid_from_mask(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def _list_jpg_frames(source_path: str) -> list[Path]:
    frame_dir = Path(source_path)
    frame_files = [path for path in frame_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg"}]
    frame_files.sort(key=lambda path: int(path.stem))
    return frame_files


def get_source_metadata(source_path: str, preview_fps: Optional[float] = None) -> tuple[int, int, int, float]:
    source = Path(source_path)
    if source.is_dir():
        frame_files = _list_jpg_frames(source_path)
        if not frame_files:
            raise RuntimeError(f"No JPEG frames found in {source_path}")
        with Image.open(frame_files[0]) as image:
            video_width, video_height = image.size
        fps = float(preview_fps or 0.0)
        return len(frame_files), video_width, video_height, fps if fps > 0.0 else 30.0

    capture = cv2.VideoCapture(source_path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        return frame_count, video_width, video_height, fps if fps > 0.0 else float(preview_fps or 30.0)
    finally:
        capture.release()


def iter_source_frames(source_path: str, start_frame: int = 0):
    source = Path(source_path)
    if source.is_dir():
        for frame_idx, frame_path in enumerate(_list_jpg_frames(source_path)[start_frame:], start=start_frame):
            frame_bgr = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if frame_bgr is None:
                raise RuntimeError(f"Could not read frame {frame_path}")
            yield frame_idx, cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return

    capture = cv2.VideoCapture(source_path)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source_path}")
    try:
        if start_frame > 0:
            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_idx = start_frame
        while True:
            ok, frame_bgr = capture.read()
            if not ok:
                break
            yield frame_idx, cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_idx += 1
    finally:
        capture.release()


@dataclass
class StandaloneWarmSam2Config:
    sam2_root: Path = Path(os.environ.get("SAM2_REPO_ROOT", LEGACY_SAM2_ROOT))
    cache_root: Path = Path(os.environ.get("SAM2_CACHE_ROOT", str(LEGACY_SAM2_CACHE_ROOT)))
    checkpoint: Path = Path(os.environ.get("SAM2_CHECKPOINT_PATH", LEGACY_SAM2_CHECKPOINT))
    model_cfg: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    object_id: int = 1
    vos_optimized: bool = True
    offload_video_to_cpu: bool = False
    offload_state_to_cpu: bool = False

    @property
    def repo_root(self) -> Path:
        return self.sam2_root


class StandaloneWarmSam2Tracker:
    def __init__(self, config: Optional[StandaloneWarmSam2Config] = None):
        self.config = config or StandaloneWarmSam2Config()
        self._torch = None
        self._predictor = None
        self._build_seconds: float | None = None
        self._device = None

    def _ensure_loaded(self) -> None:
        if self._predictor is not None:
            return

        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for the warm SAM2 tracker.")

        if not self.config.repo_root.exists():
            raise RuntimeError(f"SAM2 repo root does not exist: {self.config.repo_root}")
        if not self.config.checkpoint.exists():
            raise RuntimeError(f"SAM2 checkpoint does not exist: {self.config.checkpoint}")

        self._torch = torch
        self._device = torch.device("cuda")
        if torch.cuda.get_device_properties(0).major >= 8:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True

        triton_cache_dir = self.config.cache_root / "t"
        torchinductor_cache_dir = self.config.cache_root / "i"
        triton_cache_dir.mkdir(parents=True, exist_ok=True)
        torchinductor_cache_dir.mkdir(parents=True, exist_ok=True)

        repo_root_str = str(self.config.repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)
        os.environ.setdefault("TRITON_ALLOWED_BACKENDS", "nvidia")
        os.environ.setdefault("TRITON_CACHE_DIR", str(triton_cache_dir))
        os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", str(torchinductor_cache_dir))

        if self.config.vos_optimized:
            try:
                import torch._inductor.config as inductor_config

                inductor_config.triton.cudagraphs = False
                inductor_config.triton.cudagraph_trees = False
            except Exception:
                pass

        from sam2.build_sam import build_sam2_video_predictor

        build_start = time.perf_counter()
        self._predictor = build_sam2_video_predictor(
            self.config.model_cfg,
            str(self.config.checkpoint),
            device=self._device,
            vos_optimized=self.config.vos_optimized,
        )
        self._build_seconds = time.perf_counter() - build_start

    def track_from_seed(
        self,
        video_path: str,
        seed: dict[str, object],
        output_dir: Path,
        no_preview: bool = True,
        frame_limit: int = 0,
        preview_fps: Optional[float] = None,
    ) -> dict[str, object]:
        self._ensure_loaded()
        output_dir.mkdir(parents=True, exist_ok=True)

        seed_frame = int(seed["frame_idx"])
        box = [float(v) for v in seed["box"]] if seed.get("box") is not None else None
        seed_points = seed.get("points") or []
        seed_labels = seed.get("point_labels") or []
        frame_count, video_width, video_height, preview_fps = get_source_metadata(video_path, preview_fps=preview_fps)
        if not (0 <= seed_frame < frame_count):
            raise ValueError(f"seed frame {seed_frame} is outside 0..{frame_count - 1}")
        if box is None and not seed_points:
            raise ValueError("Seed must include at least a box or one point prompt.")
        if seed_points and len(seed_points) != len(seed_labels):
            raise ValueError("Seed point_labels must match the number of seed points.")

        init_start = time.perf_counter()
        inference_state = self._predictor.init_state(
            video_path=video_path,
            offload_video_to_cpu=self.config.offload_video_to_cpu,
            offload_state_to_cpu=self.config.offload_state_to_cpu,
        )
        init_seconds = time.perf_counter() - init_start

        box_array = np.array(box, dtype=np.float32) if box is not None else None
        points_array = np.array(seed_points, dtype=np.float32) if seed_points else None
        labels_array = np.array(seed_labels, dtype=np.int32) if seed_labels else None
        results: dict[int, dict[str, object]] = {}
        max_to_track = None if frame_limit <= 0 else frame_limit
        self._torch.cuda.empty_cache()

        propagate_start = time.perf_counter()
        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            self._predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=seed_frame,
                obj_id=self.config.object_id,
                points=points_array,
                labels=labels_array,
                box=box_array,
            )
            for out_frame_idx, out_obj_ids, out_mask_logits in self._predictor.propagate_in_video(
                inference_state,
                start_frame_idx=seed_frame,
                max_frame_num_to_track=max_to_track,
            ):
                for obj_id, mask_logits in zip(out_obj_ids, out_mask_logits):
                    mask = (mask_logits[0] > 0.0).cpu().numpy()
                    results[int(out_frame_idx)] = {
                        "object_id": int(obj_id),
                        "bbox": bbox_from_mask(mask),
                        "centroid": centroid_from_mask(mask),
                        "area": int(mask.sum()),
                    }
        propagate_seconds = time.perf_counter() - propagate_start

        csv_path = output_dir / "track.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["frame_idx", "object_id", "present", "area", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "centroid_x", "centroid_y"]
            )
            for frame_idx in range(seed_frame, frame_count):
                row = results.get(frame_idx)
                if row is None or row["bbox"] is None:
                    writer.writerow([frame_idx, self.config.object_id, 0, 0, "", "", "", "", "", ""])
                    continue
                x1, y1, x2, y2 = row["bbox"]
                cx, cy = row["centroid"]
                writer.writerow([frame_idx, row["object_id"], 1, row["area"], x1, y1, x2, y2, f"{cx:.2f}", f"{cy:.2f}"])

        preview_seconds = 0.0
        if not no_preview:
            mp4_path = output_dir / "preview.mp4"
            preview_start = time.perf_counter()
            writer = cv2.VideoWriter(str(mp4_path), cv2.VideoWriter_fourcc(*"mp4v"), preview_fps, (video_width, video_height))
            if not writer.isOpened():
                raise RuntimeError(f"Could not open preview writer for {mp4_path}")
            try:
                for frame_idx, frame_rgb in iter_source_frames(video_path, start_frame=seed_frame):
                    row = results.get(frame_idx)
                    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                    if row is not None and row["bbox"] is not None:
                        x1, y1, x2, y2 = row["bbox"]
                        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (255, 255, 0), 3)
                    writer.write(frame_bgr)
            finally:
                writer.release()
            preview_seconds = time.perf_counter() - preview_start

        found_frames = [frame_idx for frame_idx, row in results.items() if row["bbox"] is not None]
        total_seconds = float(self._build_seconds or 0.0) + init_seconds + propagate_seconds + preview_seconds
        summary_path = output_dir / "summary.txt"
        with summary_path.open("w", encoding="utf-8") as handle:
            handle.write("mode=batch_video_predictor\n")
            handle.write(f"checkpoint={self.config.checkpoint}\n")
            handle.write(f"model_cfg={self.config.model_cfg}\n")
            handle.write(f"seed_frame={seed_frame}\n")
            handle.write(f"seed_box={box}\n")
            handle.write(f"seed_points={seed_points}\n")
            handle.write(f"seed_point_labels={seed_labels}\n")
            handle.write(f"video_size={video_width}x{video_height}\n")
            handle.write(f"vos_optimized={self.config.vos_optimized}\n")
            handle.write(f"build_seconds={float(self._build_seconds or 0.0):.3f}\n")
            handle.write(f"init_seconds={init_seconds:.3f}\n")
            handle.write(f"propagate_seconds={propagate_seconds:.3f}\n")
            handle.write(f"preview_seconds={preview_seconds:.3f}\n")
            handle.write(f"total_seconds={total_seconds:.3f}\n")
            handle.write(f"tracked_frames={len(found_frames)}\n")
            if found_frames:
                handle.write(f"first_tracked_frame={min(found_frames)}\n")
                handle.write(f"last_tracked_frame={max(found_frames)}\n")

        return {
            "track_csv": str(csv_path),
            "summary_path": str(summary_path),
            "tracked_frames": len(found_frames),
            "first_tracked_frame": min(found_frames) if found_frames else None,
            "last_tracked_frame": max(found_frames) if found_frames else None,
            "build_seconds": float(self._build_seconds or 0.0),
            "init_seconds": init_seconds,
            "propagate_seconds": propagate_seconds,
            "total_seconds": total_seconds,
        }
