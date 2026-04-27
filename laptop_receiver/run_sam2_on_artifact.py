from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from laptop_receiver.standalone_sam2_tracking import run_sam2_on_artifact
from laptop_receiver.standalone_warm_sam2_tracker import (
    DEFAULT_SAM2_CACHE_ROOT,
    DEFAULT_SAM2_CHECKPOINT,
    DEFAULT_SAM2_ROOT,
    StandaloneWarmSam2Config,
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run warm SAM2 on a standalone local clip artifact using a standalone YOLO seed.")
    parser.add_argument("artifact_dir", type=Path, help="Path to the standalone clip_<session>_<shot> artifact directory")
    parser.add_argument("--seed-path", type=Path, default=None, help="Optional explicit path to yolo_seed.json")
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional explicit analysis output directory")
    parser.add_argument("--sam2-root", type=Path, default=DEFAULT_SAM2_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_SAM2_CHECKPOINT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_SAM2_CACHE_ROOT)
    parser.add_argument("--model-cfg", default="configs/sam2.1/sam2.1_hiera_t.yaml")
    parser.add_argument("--frame-limit", type=int, default=0)
    parser.add_argument("--source-frame-idx-start", type=int, default=0)
    parser.add_argument("--source-frame-idx-end", type=int, default=None)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    config = StandaloneWarmSam2Config(
        sam2_root=args.sam2_root.expanduser().resolve(),
        cache_root=args.cache_root.expanduser().resolve(),
        checkpoint=args.checkpoint.expanduser().resolve(),
        model_cfg=str(args.model_cfg),
    )
    result = run_sam2_on_artifact(
        args.artifact_dir,
        seed_path=args.seed_path,
        output_dir=args.output_dir,
        preview=not args.no_preview,
        frame_limit=int(args.frame_limit),
        config=config,
        source_frame_idx_start=int(args.source_frame_idx_start),
        source_frame_idx_end=args.source_frame_idx_end,
    )

    if args.emit_json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.artifact_dir}")
        print(f"sam2_dir: {result.sam2_dir}")
        print(
            f"tracked_frames={result.tracked_frames} first_frame={result.first_frame} "
            f"last_frame={result.last_frame} total_seconds={result.timing['total_seconds']:.3f}"
        )
        if result.preview_path:
            print(f"preview: {result.preview_path}")
        if result.failure_reason:
            print(f"failure_reason: {result.failure_reason}")

    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
