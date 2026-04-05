from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from .oracle_review_utils import (
        DEFAULT_ORACLE_REVIEW_PATH,
        VALID_REVIEW_STATUSES,
        get_review_for_run,
        load_oracle_reviews,
        save_oracle_reviews,
        set_review_for_run,
        sync_review_into_result,
    )
    from .oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs
except ImportError:
    from oracle_review_utils import (
        DEFAULT_ORACLE_REVIEW_PATH,
        VALID_REVIEW_STATUSES,
        get_review_for_run,
        load_oracle_reviews,
        save_oracle_reviews,
        set_review_for_run,
        sync_review_into_result,
    )
    from oracle_seed_utils import DEFAULT_INPUT_ROOT, list_run_dirs


WINDOW_NAME = "Oracle Preview Reviewer"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _status_color(status: str) -> tuple[int, int, int]:
    if status == "accepted":
        return (60, 200, 60)
    if status == "needs_work":
        return (0, 200, 255)
    if status == "rejected":
        return (0, 0, 255)
    return (180, 180, 180)


@dataclass
class ReviewRun:
    run_dir: Path
    preview_path: Path | None
    result: dict[str, Any]
    review: dict[str, Any]


class PreviewReviewer:
    def __init__(self, runs: list[ReviewRun], reviews_path: Path, review_doc: dict[str, Any], autoplay: bool):
        self.runs = runs
        self.reviews_path = reviews_path
        self.review_doc = review_doc
        self.autoplay = autoplay
        self.index = 0
        self.capture: cv2.VideoCapture | None = None
        self.current_frame: np.ndarray | None = None
        self.frame_index = 0
        self.frame_count = 0
        self.frame_delay_ms = 33
        self.paused = not autoplay

    def current_run(self) -> ReviewRun:
        return self.runs[self.index]

    def load_run(self, index: int) -> None:
        self.index = max(0, min(index, len(self.runs) - 1))
        self._release_capture()
        self.current_frame = None
        self.frame_index = 0
        self.frame_count = 0
        self.paused = not self.autoplay

        run = self.current_run()
        preview_path = run.preview_path
        if preview_path is not None and preview_path.exists():
            capture = cv2.VideoCapture(str(preview_path))
            if capture.isOpened():
                self.capture = capture
                self.frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                if fps > 0:
                    self.frame_delay_ms = max(10, int(round(1000.0 / fps)))
                self._read_next_frame()
                return
            capture.release()

        self.current_frame = self._build_fallback_frame(run)
        self.frame_delay_ms = 33
        self.paused = True

    def _release_capture(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def _build_fallback_frame(self, run: ReviewRun) -> np.ndarray:
        candidates = [
            run.run_dir / "analysis_oracle" / "manual_seed_preview.jpg",
            run.run_dir / "analysis" / "best_detection.jpg",
            run.run_dir / "raw" / "frames" / "000000.jpg",
        ]
        for path in candidates:
            if not path.exists():
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                return image
        canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.putText(canvas, "No preview available", (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        return canvas

    def _read_next_frame(self) -> None:
        if self.capture is None:
            return
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.frame_index = 0
            ok, frame = self.capture.read()
            if not ok:
                self.current_frame = self._build_fallback_frame(self.current_run())
                self._release_capture()
                self.paused = True
                return
        else:
            self.frame_index += 1
        self.current_frame = frame

    def step_frame(self, delta: int) -> None:
        if self.capture is None:
            return
        current = int(self.capture.get(cv2.CAP_PROP_POS_FRAMES) or 0)
        target = max(0, current + delta)
        if self.frame_count > 0:
            target = min(target, self.frame_count - 1)
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        self.frame_index = target
        ok, frame = self.capture.read()
        if ok:
            self.current_frame = frame

    def restart(self) -> None:
        if self.capture is None:
            return
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.frame_index = 0
        self._read_next_frame()

    def set_status(self, status: str) -> None:
        run = self.current_run()
        existing = get_review_for_run(self.review_doc, run.run_dir.name)
        notes = existing.get("notes", "") if existing else ""
        review_entry = set_review_for_run(self.review_doc, run.run_dir.name, status, notes=notes)
        save_oracle_reviews(self.reviews_path, self.review_doc)
        sync_review_into_result(run.run_dir, review_entry)
        run.review = review_entry

    def overlay_frame(self) -> np.ndarray:
        assert self.current_frame is not None
        frame = self.current_frame.copy()
        run = self.current_run()
        review = run.review
        status = review.get("status", "pending")
        color = _status_color(status)

        lines = [
            f"Run {self.index + 1}/{len(self.runs)}: {run.run_dir.name}",
            f"Status: {status}",
            f"Tracked frames: {int(run.result.get('tracked_frames') or 0)}",
        ]
        failure_reason = run.result.get("failure_reason", "")
        if failure_reason:
            lines.append(f"Failure: {failure_reason}")
        notes = review.get("notes", "")
        if notes:
            lines.append(f"Notes: {notes}")

        controls = [
            "1 accepted | 2 needs_work | 3 rejected | 0 pending",
            "n next | p prev | space pause/play | r restart | a/d step | q quit",
        ]

        y = 32
        for text in lines:
            cv2.putText(frame, text, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color if text.startswith("Status") else (255, 255, 255), 2, cv2.LINE_AA)
            y += 28
        y += 8
        for text in controls:
            cv2.putText(frame, text, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 220), 2, cv2.LINE_AA)
            y += 24

        if self.capture is not None and self.frame_count > 0:
            progress = f"Frame {min(self.frame_index, self.frame_count)}/{self.frame_count}"
            cv2.putText(frame, progress, (18, frame.shape[0] - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2, cv2.LINE_AA)
        return frame

    def maybe_advance(self) -> None:
        if not self.paused:
            self._read_next_frame()

    def next_run(self) -> None:
        if self.index < len(self.runs) - 1:
            self.load_run(self.index + 1)

    def prev_run(self) -> None:
        if self.index > 0:
            self.load_run(self.index - 1)


def parse_args():
    parser = argparse.ArgumentParser(description="Interactive preview reviewer for oracle-seeded SAM2 bowling runs.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--reviews-path", type=Path, default=DEFAULT_ORACLE_REVIEW_PATH)
    parser.add_argument("--start-run", default="")
    parser.add_argument("--only-status", choices=sorted(VALID_REVIEW_STATUSES), default="")
    parser.add_argument("--autoplay", action="store_true")
    return parser.parse_args()


def _build_runs(input_root: Path, review_doc: dict[str, Any], only_status: str) -> list[ReviewRun]:
    rows: list[ReviewRun] = []
    for run_dir in list_run_dirs(input_root):
        result_path = run_dir / "oracle_tracking_result.json"
        if not result_path.exists():
            continue
        result = _load_json(result_path)
        review = get_review_for_run(review_doc, run_dir.name) or {"status": "pending", "notes": ""}
        if only_status and review.get("status") != only_status:
            continue
        preview_path = Path(result.get("preview_path", "")) if result.get("preview_path") else None
        rows.append(ReviewRun(run_dir=run_dir, preview_path=preview_path, result=result, review=review))
    return rows


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    reviews_path = args.reviews_path.resolve()
    review_doc = load_oracle_reviews(reviews_path)
    runs = _build_runs(input_root, review_doc, args.only_status)
    if not runs:
        raise SystemExit("No oracle runs matched the current filter.")

    reviewer = PreviewReviewer(runs, reviews_path, review_doc, autoplay=bool(args.autoplay))
    start_index = 0
    if args.start_run:
        for idx, run in enumerate(runs):
            if run.run_dir.name == args.start_run:
                start_index = idx
                break
    reviewer.load_run(start_index)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    while True:
        reviewer.maybe_advance()
        frame = reviewer.overlay_frame()
        cv2.imshow(WINDOW_NAME, frame)
        key = cv2.waitKeyEx(reviewer.frame_delay_ms if not reviewer.paused else 30)
        if key < 0:
            continue
        normalized = key & 0xFF

        if normalized == ord("q"):
            break
        if normalized == ord(" "):
            reviewer.paused = not reviewer.paused
            continue
        if normalized == ord("n"):
            reviewer.next_run()
            continue
        if normalized == ord("p"):
            reviewer.prev_run()
            continue
        if normalized == ord("r"):
            reviewer.restart()
            continue
        if normalized == ord("a"):
            reviewer.paused = True
            reviewer.step_frame(-1)
            continue
        if normalized == ord("d"):
            reviewer.paused = True
            reviewer.step_frame(1)
            continue
        if normalized == ord("1"):
            reviewer.set_status("accepted")
            reviewer.next_run()
            continue
        if normalized == ord("2"):
            reviewer.set_status("needs_work")
            reviewer.next_run()
            continue
        if normalized == ord("3"):
            reviewer.set_status("rejected")
            reviewer.next_run()
            continue
        if normalized == ord("0"):
            reviewer.set_status("pending")
            reviewer.next_run()
            continue

    reviewer._release_capture()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
