from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2

try:
    from .oracle_seed_utils import (
        DEFAULT_INPUT_ROOT,
        DEFAULT_MANUAL_SEEDS_PATH,
        get_seed_for_run,
        list_run_dirs,
        load_manual_seeds,
        load_suggested_seed,
        save_manual_seeds,
        set_seed_for_run,
    )
except ImportError:
    from oracle_seed_utils import (
        DEFAULT_INPUT_ROOT,
        DEFAULT_MANUAL_SEEDS_PATH,
        get_seed_for_run,
        list_run_dirs,
        load_manual_seeds,
        load_suggested_seed,
        save_manual_seeds,
        set_seed_for_run,
    )


WINDOW_NAME = "Manual Seed Annotator"


@dataclass
class RunState:
    run_dir: Path
    frame_files: list[Path]
    frame_idx: int
    current_box: Optional[list[float]]
    current_source: str
    suggested_seed: Optional[dict]
    manual_seed: Optional[dict]


class SeedAnnotator:
    def __init__(self, run_dirs: list[Path], seeds_path: Path, document: dict):
        self.run_dirs = run_dirs
        self.seeds_path = seeds_path
        self.document = document
        self.run_index = 0
        self.run_state: Optional[RunState] = None
        self.display_frame = None
        self.dragging = False
        self.drag_start: Optional[tuple[int, int]] = None
        self.preview_box: Optional[list[float]] = None
        self.dirty = False

    def load_run(self, run_index: int) -> None:
        self.run_index = max(0, min(run_index, len(self.run_dirs) - 1))
        run_dir = self.run_dirs[self.run_index]
        frame_files = sorted((run_dir / "raw" / "frames").glob("*.jpg"), key=lambda path: int(path.stem))
        if not frame_files:
            raise RuntimeError(f"No frames found in {run_dir}")

        manual_seed = get_seed_for_run(self.document, run_dir.name)
        suggested_seed = load_suggested_seed(run_dir)
        seed_to_use = manual_seed or suggested_seed
        frame_idx = int(seed_to_use["frame_idx"]) if seed_to_use is not None else 0
        frame_idx = max(0, min(frame_idx, len(frame_files) - 1))
        current_box = [float(v) for v in seed_to_use["box"]] if seed_to_use is not None else None
        current_source = "manual" if manual_seed is not None else ("suggested" if suggested_seed is not None else "none")

        self.run_state = RunState(
            run_dir=run_dir,
            frame_files=frame_files,
            frame_idx=frame_idx,
            current_box=current_box,
            current_source=current_source,
            suggested_seed=suggested_seed,
            manual_seed=manual_seed,
        )
        self.dragging = False
        self.drag_start = None
        self.preview_box = None
        self.dirty = False

    def current_frame_path(self) -> Path:
        assert self.run_state is not None
        return self.run_state.frame_files[self.run_state.frame_idx]

    def load_frame_bgr(self):
        frame_bgr = cv2.imread(str(self.current_frame_path()), cv2.IMREAD_COLOR)
        if frame_bgr is None:
            raise RuntimeError(f"Could not read frame {self.current_frame_path()}")
        return frame_bgr

    def draw(self):
        assert self.run_state is not None
        image = self.load_frame_bgr()
        if self.run_state.suggested_seed is not None:
            suggested_frame = int(self.run_state.suggested_seed["frame_idx"])
            if suggested_frame == self.run_state.frame_idx:
                x1, y1, x2, y2 = (int(round(v)) for v in self.run_state.suggested_seed["box"])
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 140, 255), 2)
                cv2.putText(image, "suggested", (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 140, 255), 2, cv2.LINE_AA)

        box_to_draw = self.preview_box if self.preview_box is not None else self.run_state.current_box
        if box_to_draw is not None:
            x1, y1, x2, y2 = (int(round(v)) for v in box_to_draw)
            cv2.rectangle(image, (x1, y1), (x2, y2), (255, 255, 0), 2)
            label = f"manual seed ({self.run_state.current_source})"
            cv2.putText(image, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2, cv2.LINE_AA)

        header = [
            f"Run {self.run_index + 1}/{len(self.run_dirs)}: {self.run_state.run_dir.name}",
            f"Frame {self.run_state.frame_idx}/{len(self.run_state.frame_files) - 1}",
            "Keys: a/d +/-1 frame, j/l +/-10, r clear, g suggested frame, s save, n save+next, p prev run, q quit",
        ]
        for line_idx, text in enumerate(header):
            cv2.putText(image, text, (18, 28 + 24 * line_idx), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2, cv2.LINE_AA)

        self.display_frame = image
        cv2.imshow(WINDOW_NAME, image)

    def save_current_seed(self) -> None:
        assert self.run_state is not None
        if self.run_state.current_box is None:
            raise RuntimeError("No box is currently selected for this run.")
        set_seed_for_run(
            self.document,
            self.run_state.run_dir.name,
            self.run_state.frame_idx,
            self.run_state.current_box,
            notes="manual_seed",
        )
        save_manual_seeds(self.seeds_path, self.document)
        self.run_state.current_source = "manual"
        self.run_state.manual_seed = get_seed_for_run(self.document, self.run_state.run_dir.name)
        self.dirty = False

    def move_frame(self, delta: int) -> None:
        assert self.run_state is not None
        self.run_state.frame_idx = max(0, min(self.run_state.frame_idx + delta, len(self.run_state.frame_files) - 1))
        self.preview_box = None

    def jump_to_suggested(self) -> None:
        assert self.run_state is not None
        if self.run_state.suggested_seed is None:
            return
        self.run_state.frame_idx = max(
            0,
            min(int(self.run_state.suggested_seed["frame_idx"]), len(self.run_state.frame_files) - 1),
        )

    def handle_mouse(self, event: int, x: int, y: int, _flags: int, _userdata) -> None:
        if self.display_frame is None:
            return
        h, w = self.display_frame.shape[:2]
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.drag_start = (x, y)
            self.preview_box = [float(x), float(y), float(x), float(y)]
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging and self.drag_start is not None:
            x0, y0 = self.drag_start
            self.preview_box = [float(min(x0, x)), float(min(y0, y)), float(max(x0, x)), float(max(y0, y))]
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            self.dragging = False
            x0, y0 = self.drag_start
            x1, y1, x2, y2 = float(min(x0, x)), float(min(y0, y)), float(max(x0, x)), float(max(y0, y))
            self.drag_start = None
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                assert self.run_state is not None
                self.run_state.current_box = [x1, y1, x2, y2]
                self.dirty = True
            self.preview_box = None


def parse_args():
    parser = argparse.ArgumentParser(description="Interactively annotate one initial SAM2 seed box per recorded bowling run.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--seeds-path", type=Path, default=DEFAULT_MANUAL_SEEDS_PATH)
    parser.add_argument("--start-run", default="", help="Optional run name to start from.")
    parser.add_argument("--only-missing", action="store_true", help="Only step through runs that do not already have a manual seed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    seeds_path = args.seeds_path.resolve()
    run_dirs = list_run_dirs(input_root)
    if not run_dirs:
        raise SystemExit(f"No recorded runs found under {input_root}")

    document = load_manual_seeds(seeds_path)
    if args.only_missing:
        run_dirs = [run_dir for run_dir in run_dirs if get_seed_for_run(document, run_dir.name) is None]
        if not run_dirs:
            raise SystemExit("All runs already have manual seeds.")

    annotator = SeedAnnotator(run_dirs, seeds_path, document)

    start_index = 0
    if args.start_run:
        for index, run_dir in enumerate(run_dirs):
            if run_dir.name == args.start_run:
                start_index = index
                break
    annotator.load_run(start_index)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW_NAME, annotator.handle_mouse)

    while True:
        annotator.draw()
        key = cv2.waitKeyEx(30)
        if key < 0:
            continue

        normalized = key & 0xFF
        if normalized == ord("q"):
            break
        if normalized == ord("a"):
            annotator.move_frame(-1)
            continue
        if normalized == ord("d"):
            annotator.move_frame(1)
            continue
        if normalized == ord("j"):
            annotator.move_frame(-10)
            continue
        if normalized == ord("l"):
            annotator.move_frame(10)
            continue
        if normalized == ord("g"):
            annotator.jump_to_suggested()
            continue
        if normalized == ord("r"):
            assert annotator.run_state is not None
            annotator.run_state.current_box = None
            annotator.dirty = True
            continue
        if normalized == ord("s"):
            annotator.save_current_seed()
            continue
        if normalized == ord("n"):
            annotator.save_current_seed()
            if annotator.run_index >= len(run_dirs) - 1:
                break
            annotator.load_run(annotator.run_index + 1)
            continue
        if normalized == ord("p"):
            if annotator.run_index > 0:
                annotator.load_run(annotator.run_index - 1)
            continue
        if key in (13, 10):
            annotator.save_current_seed()
            continue

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
