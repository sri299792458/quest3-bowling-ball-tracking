from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from laptop_receiver.standalone_yolo_seed import DEFAULT_YOLO_CHECKPOINT, analyze_artifact_with_yolo_seed


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run standalone causal YOLO seeding over a local clip artifact.")
    parser.add_argument("artifact_dir", type=Path, help="Path to the standalone clip_<session>_<shot> artifact directory")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_YOLO_CHECKPOINT if DEFAULT_YOLO_CHECKPOINT.exists() else None,
        help="Path to the YOLO checkpoint to use. Defaults to the YOLO26s checkpoint if present.",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="Optional explicit output directory for yolo seed artifacts")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--device", default="0")
    parser.add_argument("--det-conf", type=float, default=0.05)
    parser.add_argument("--seed-conf", type=float, default=0.8)
    parser.add_argument("--min-box-size", type=float, default=10.0)
    parser.add_argument("--frame-seq-start", type=int, default=None, help="Optional first frameSeq to search.")
    parser.add_argument("--frame-seq-end", type=int, default=None, help="Optional final frameSeq to search.")
    parser.add_argument("--json", action="store_true", dest="emit_json", help="Emit the result document as JSON.")
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()

    checkpoint_path: Path | None = args.checkpoint
    if checkpoint_path is None:
        raise SystemExit("A YOLO checkpoint is required. Pass --checkpoint <path>.")
    checkpoint_path = checkpoint_path.expanduser().resolve()
    if not checkpoint_path.exists():
        raise SystemExit(f"YOLO checkpoint does not exist: {checkpoint_path}")

    result = analyze_artifact_with_yolo_seed(
        args.artifact_dir,
        checkpoint_path=checkpoint_path,
        output_root=args.output_dir,
        imgsz=int(args.imgsz),
        device=str(args.device),
        det_conf=float(args.det_conf),
        seed_conf=float(args.seed_conf),
        min_box_size=float(args.min_box_size),
        frame_seq_start=args.frame_seq_start,
        frame_seq_end=args.frame_seq_end,
    )

    if args.emit_json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.artifact_dir}")
        print(f"analysis_dir: {result.analysis_dir}")
        if result.seed is not None:
            print(
                f"seed: frame={result.seed['frame_idx']} conf={result.seed['detector_confidence']:.4f} "
                f"box={result.seed['box']}"
            )
        else:
            print(f"failure_reason: {result.failure_reason}")
        if result.preview_path:
            print(f"preview: {result.preview_path}")

    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
