from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class FrameRecord:
    local_frame_idx: int
    source_frame_id: int
    timestamp_us: int
    shot_id: str
    camera_position: np.ndarray
    camera_rotation: np.ndarray
    head_position: np.ndarray
    head_rotation: np.ndarray
    file_name: str


@dataclass(frozen=True)
class RunData:
    run_dir: Path
    raw_dir: Path
    frames_dir: Path
    frames_jsonl_path: Path
    capture_summary_path: Path
    frame_records: list[FrameRecord]

    @property
    def run_name(self) -> str:
        return self.run_dir.name

    def frame_path(self, record: FrameRecord) -> Path:
        return self.frames_dir / record.file_name

    def get_frame_record(self, local_frame_idx: int) -> FrameRecord:
        for record in self.frame_records:
            if record.local_frame_idx == local_frame_idx:
                return record
        raise KeyError(f"Frame index {local_frame_idx} not found in {self.run_name}")

    def load_frame_bgr(self, local_frame_idx: int) -> np.ndarray:
        import cv2

        record = self.get_frame_record(local_frame_idx)
        frame_path = self.frame_path(record)
        image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Failed to load frame image: {frame_path}")
        return image

    def load_capture_summary(self) -> dict:
        if not self.capture_summary_path.exists():
            return {}
        return json.loads(self.capture_summary_path.read_text(encoding="utf-8"))

    def infer_image_size(self) -> tuple[int, int]:
        manifest_path = self.raw_dir / "manifest.json"
        if manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            width = int(payload["frame_width"])
            height = int(payload["frame_height"])
            return width, height

        if not self.frame_records:
            raise ValueError(f"No frame records found for {self.run_name}")

        frame_path = self.frame_path(self.frame_records[0])
        with Image.open(frame_path) as image:
            width, height = image.size
        return width, height


def default_raw_root(workspace_root: Path | None = None) -> Path:
    base = workspace_root or Path(__file__).resolve().parents[1]
    return base / "data" / "raw_runs"


def list_run_dirs(raw_root: Path) -> list[Path]:
    if not raw_root.exists():
        raise FileNotFoundError(f"Raw run root does not exist: {raw_root}")
    nested_run_dirs = sorted(
        path for path in raw_root.iterdir() if path.is_dir() and (path / "raw" / "frames.jsonl").exists()
    )
    if nested_run_dirs:
        return nested_run_dirs
    return sorted(
        path for path in raw_root.iterdir() if path.is_dir() and (path / "frames.jsonl").exists()
    )


def load_run(run_dir: Path) -> RunData:
    raw_dir_candidates = [
        run_dir / "raw",
        run_dir,
        run_dir / "raw" / "raw",
    ]
    raw_dir = None
    frames_dir = None
    frames_jsonl_path = None
    capture_summary_path = None

    for candidate_raw_dir in raw_dir_candidates:
        candidate_frames_dir = candidate_raw_dir / "frames"
        candidate_frames_jsonl_path = candidate_raw_dir / "frames.jsonl"
        if candidate_frames_dir.exists() and candidate_frames_jsonl_path.exists():
            raw_dir = candidate_raw_dir
            frames_dir = candidate_frames_dir
            frames_jsonl_path = candidate_frames_jsonl_path
            capture_summary_path = candidate_raw_dir / "capture_summary.json"
            break

    if raw_dir is None or frames_dir is None or frames_jsonl_path is None or capture_summary_path is None:
        raise FileNotFoundError(
            f"Could not locate a valid raw run layout under {run_dir}. Expected frames.jsonl plus frames/ in one of: "
            f"{', '.join(str(path) for path in raw_dir_candidates)}"
        )

    frame_records = parse_frame_records(frames_jsonl_path)
    return RunData(
        run_dir=run_dir,
        raw_dir=raw_dir,
        frames_dir=frames_dir,
        frames_jsonl_path=frames_jsonl_path,
        capture_summary_path=capture_summary_path,
        frame_records=frame_records,
    )


def parse_frame_records(frames_jsonl_path: Path) -> list[FrameRecord]:
    records: list[FrameRecord] = []
    with frames_jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            records.append(
                FrameRecord(
                    local_frame_idx=int(payload["local_frame_idx"]),
                    source_frame_id=int(payload["source_frame_id"]),
                    timestamp_us=int(payload["timestamp_us"]),
                    shot_id=str(payload["shot_id"]),
                    camera_position=np.asarray(payload["camera_position"], dtype=np.float64),
                    camera_rotation=np.asarray(payload["camera_rotation"], dtype=np.float64),
                    head_position=np.asarray(payload["head_position"], dtype=np.float64),
                    head_rotation=np.asarray(payload["head_rotation"], dtype=np.float64),
                    file_name=str(payload["file_name"]),
                )
            )
    return records


def iter_all_records(run_dirs: Iterable[Path]) -> Iterable[tuple[Path, FrameRecord]]:
    for run_dir in run_dirs:
        run = load_run(run_dir)
        for record in run.frame_records:
            yield run_dir, record
