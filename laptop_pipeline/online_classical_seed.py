import csv
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np

try:
    from . import classical_seed_core as classical_core
except ImportError:
    import classical_seed_core as classical_core


@dataclass
class OnlineClassicalSeedConfig:
    scan_start: int = 0
    scan_step: int = 2
    motion_threshold: float = 18.0
    min_area: float = 80.0
    min_motion_ratio: float = 0.15
    min_darkness: float = 0.32
    min_contrast: float = 0.04
    min_circularity: float = 0.35
    min_fill_ratio: float = 0.25
    min_lane_overlap: float = 0.85
    lane_width_ratio_min: float = 0.045
    lane_width_ratio_max: float = 0.18
    max_candidates_per_frame: int = 6
    max_track_gap: int = 6
    max_center_distance: float = 180.0
    size_ratio_threshold: float = 0.45
    max_y_increase: float = 20.0
    min_track_length: int = 4
    min_track_travel: float = 180.0
    min_start_center_y_ratio: float = 0.55
    min_mean_score: float = 0.62


class OnlineClassicalSeedDetector:
    def __init__(self, frame_width: int, frame_height: int, config: Optional[OnlineClassicalSeedConfig] = None):
        self.config = config or OnlineClassicalSeedConfig()
        self.classical = classical_core
        self.args = SimpleNamespace(
            motion_threshold=self.config.motion_threshold,
            min_area=self.config.min_area,
            min_motion_ratio=self.config.min_motion_ratio,
            min_darkness=self.config.min_darkness,
            min_contrast=self.config.min_contrast,
            min_circularity=self.config.min_circularity,
            min_fill_ratio=self.config.min_fill_ratio,
            min_lane_overlap=self.config.min_lane_overlap,
            lane_width_ratio_min=self.config.lane_width_ratio_min,
            lane_width_ratio_max=self.config.lane_width_ratio_max,
            max_candidates_per_frame=self.config.max_candidates_per_frame,
            max_track_gap=self.config.max_track_gap,
            max_center_distance=self.config.max_center_distance,
            size_ratio_threshold=self.config.size_ratio_threshold,
            max_y_increase=self.config.max_y_increase,
            min_track_length=self.config.min_track_length,
            min_track_travel=self.config.min_track_travel,
            min_start_center_y_ratio=self.config.min_start_center_y_ratio,
            min_mean_score=self.config.min_mean_score,
        )
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.lane_points = self.classical.build_default_bowling_corridor(frame_width, frame_height)
        self.lane_mask = self.classical.build_lane_mask(self.lane_points, frame_width, frame_height)
        self.prev_sampled_frame_rgb: Optional[np.ndarray] = None
        self.candidates = []
        self.sampled_frames = 0
        self.sampled_frame_cache: dict[int, np.ndarray] = {}
        self.best_track = None
        self.seed: Optional[dict[str, Any]] = None
        self.seed_announced = False

    def should_sample(self, frame_idx: int) -> bool:
        return frame_idx >= self.config.scan_start and (frame_idx - self.config.scan_start) % self.config.scan_step == 0

    def process_frame(self, frame_idx: int, frame_rgb: np.ndarray) -> Optional[dict[str, Any]]:
        if not self.should_sample(frame_idx):
            return None

        self.sampled_frames += 1
        self.sampled_frame_cache[frame_idx] = frame_rgb.copy()

        if self.prev_sampled_frame_rgb is None:
            self.prev_sampled_frame_rgb = frame_rgb.copy()
            return None

        motion_mask, gray = self.classical.compute_darkening_mask(
            frame_rgb,
            self.prev_sampled_frame_rgb,
            self.args.motion_threshold,
            self.lane_mask,
        )
        self.candidates.extend(
            self.classical.extract_candidates(frame_idx, motion_mask, gray, self.lane_mask, self.args)
        )

        self.prev_sampled_frame_rgb = frame_rgb.copy()
        track = self.classical.choose_track(self.candidates, self.frame_height, self.args)
        if track is None:
            return None

        self.best_track = track
        seed = self._build_seed_from_track(track)
        if seed is None:
            return None
        self.seed = seed

        if self.seed_announced:
            return None

        self.seed_announced = True
        return {
            "kind": "tracker_status",
            "stage": "seed_confirmed",
            "frame_idx": seed["frame_idx"],
            "seed_center": seed["center"],
            "seed_box": seed["box"],
            "track_length": seed["track_length"],
            "initializer": seed["initializer"],
        }

    def _build_seed_from_track(self, track) -> Optional[dict[str, Any]]:
        coarse_seed = track.first
        seed_frame = self.sampled_frame_cache.get(coarse_seed.frame_idx)
        if seed_frame is None:
            return None

        refined_seed, refined = self.classical.refine_seed_candidate(seed_frame, coarse_seed, self.lane_mask)
        return {
            "frame_idx": refined_seed.frame_idx,
            "box": [refined_seed.x1, refined_seed.y1, refined_seed.x2, refined_seed.y2],
            "center": [refined_seed.cx, refined_seed.cy],
            "initializer": "dark_compact_motion_online",
            "coarse_box": [coarse_seed.x1, coarse_seed.y1, coarse_seed.x2, coarse_seed.y2],
            "coarse_center": [coarse_seed.cx, coarse_seed.cy],
            "refined_seed": refined,
            "track_length": len(track.candidates),
            "score": refined_seed.score,
        }

    def finalize(self) -> Optional[dict[str, Any]]:
        if self.seed is not None:
            return self.seed
        if self.best_track is None:
            self.best_track = self.classical.choose_track(self.candidates, self.frame_height, self.args)
        if self.best_track is None:
            return None
        self.seed = self._build_seed_from_track(self.best_track)
        return self.seed

    def write_outputs(self, output_dir: Path) -> Optional[dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)

        detections_csv = output_dir / "detections.csv"
        with detections_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["frame_idx", "x1", "y1", "x2", "y2", "cx", "cy", "width", "height", "lane_overlap", "lane_width_ratio", "motion_ratio", "darkness", "contrast", "circularity", "fill_ratio", "score"]
            )
            for candidate in sorted(self.candidates, key=lambda row: (row.frame_idx, -row.score)):
                writer.writerow(
                    [candidate.frame_idx, f"{candidate.x1:.2f}", f"{candidate.y1:.2f}", f"{candidate.x2:.2f}", f"{candidate.y2:.2f}", f"{candidate.cx:.2f}", f"{candidate.cy:.2f}", f"{candidate.width:.2f}", f"{candidate.height:.2f}", f"{candidate.lane_overlap:.6f}", f"{candidate.lane_width_ratio:.6f}", f"{candidate.motion_ratio:.6f}", f"{candidate.darkness:.6f}", f"{candidate.contrast:.6f}", f"{candidate.circularity:.6f}", f"{candidate.fill_ratio:.6f}", f"{candidate.score:.6f}"]
                )

        seed = self.finalize()
        track_path = output_dir / "track.json"
        if self.best_track is not None:
            track_path.write_text(
                json.dumps(
                    {
                        "length": len(self.best_track.candidates),
                        "total_score": self.best_track.total_score,
                        "mean_score": self.classical.mean_node_score(self.best_track),
                        "monotonic_fraction": self.classical.monotonic_fraction(self.best_track),
                        "total_y_travel": self.classical.total_y_travel(self.best_track),
                        "frames": [
                            {
                                "frame_idx": candidate.frame_idx,
                                "box": [candidate.x1, candidate.y1, candidate.x2, candidate.y2],
                                "center": [candidate.cx, candidate.cy],
                                "score": candidate.score,
                            }
                            for candidate in self.best_track.candidates
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            track_path.write_text(json.dumps({"length": 0, "frames": []}, indent=2), encoding="utf-8")

        best_detection_path = output_dir / "best_detection.jpg"
        seed_path = output_dir / "seed.json"
        if seed is not None:
            coarse_center = seed["coarse_center"]
            coarse_seed = next(
                (
                    candidate
                    for candidate in self.candidates
                    if candidate.frame_idx == seed["frame_idx"]
                    and abs(candidate.cx - coarse_center[0]) < 1e-3
                    and abs(candidate.cy - coarse_center[1]) < 1e-3
                ),
                None,
            )
            if coarse_seed is None and self.best_track is not None:
                coarse_seed = self.best_track.first
            frame_rgb = self.sampled_frame_cache.get(seed["frame_idx"])
            if frame_rgb is not None and coarse_seed is not None:
                self.classical.annotate_frame(frame_rgb, coarse_seed).save(best_detection_path)
            seed_path.write_text(json.dumps(seed, indent=2), encoding="utf-8")

        pipeline_summary = output_dir / "pipeline_summary.txt"
        with pipeline_summary.open("w", encoding="utf-8") as handle:
            handle.write("initializer=dark_compact_motion_online\n")
            handle.write("lane_model=default_bowling_corridor\n")
            handle.write(f"lane_points={self.lane_points.tolist()}\n")
            handle.write(f"scan_start={self.config.scan_start}\n")
            handle.write(f"scan_step={self.config.scan_step}\n")
            handle.write(f"sampled_frames={self.sampled_frames}\n")
            handle.write(f"candidate_count={len(self.candidates)}\n")
            handle.write(f"seed_found={seed is not None}\n")
            if self.best_track is not None:
                handle.write(f"track_length={len(self.best_track.candidates)}\n")
                handle.write(f"track_total_score={self.best_track.total_score:.6f}\n")
            if seed is not None:
                handle.write(f"seed_frame={seed['frame_idx']}\n")
                handle.write(f"seed_box={seed['box']}\n")
                handle.write(f"seed_center={seed['center']}\n")
                handle.write(f"seed_score={seed['score']:.6f}\n")
                handle.write(f"seed_json={seed_path}\n")
                handle.write(f"best_detection={best_detection_path}\n")
            handle.write(f"detections_csv={detections_csv}\n")
            handle.write(f"track_json={track_path}\n")

        return seed
