from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from laptop_receiver.local_clip_artifact import LocalClipArtifact


LEGACY_DEFAULT_CHECKPOINT = Path(
    r"C:\Users\student\Quest3BowlingBallTracking\laptop_pipeline\runs\yolo_hillclimb\20260329_165618\training_runs\e02_yolo11s_img1280_lightaug\weights\best.pt"
)


@dataclass(frozen=True)
class YoloSeedSearchInfo:
    search_mode: str
    search_seconds: float
    searched_frames: int
    seed_conf_threshold: float
    det_conf_floor: float
    min_box_size: float
    best_candidate_conf: float | None
    best_candidate_frame: int | None
    frame_seq_start: int | None = None
    frame_seq_end: int | None = None


@dataclass(frozen=True)
class StandaloneYoloSeedResult:
    kind: str
    success: bool
    artifact_dir: str
    analysis_dir: str
    preview_path: str
    failure_reason: str
    seed: dict[str, Any] | None
    seed_search: dict[str, Any]


def _draw_box(image: Any, box: list[float], color: tuple[int, int, int], label: str) -> None:
    import cv2

    x1, y1, x2, y2 = (int(round(v)) for v in box)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(image, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)


def _analysis_dir_for_artifact(artifact: LocalClipArtifact, output_root: Path | None) -> Path:
    if output_root is None:
        return artifact.root_dir / "analysis_yolo_seed"
    return output_root.expanduser().resolve()


def detect_yolo_seed_for_image(
    model: Any,
    image_bgr: Any,
    frame_idx: int,
    imgsz: int,
    device: str,
    det_conf: float,
) -> dict[str, Any] | None:
    results = model.predict(
        source=[image_bgr],
        imgsz=int(imgsz),
        conf=float(det_conf),
        device=device,
        verbose=False,
    )
    if not results:
        return None

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None

    xyxy = boxes.xyxy.cpu().numpy()
    confs = boxes.conf.cpu().numpy()
    best_idx = int(confs.argmax())
    x1, y1, x2, y2 = (float(v) for v in xyxy[best_idx])
    return {
        "frame_idx": int(frame_idx),
        "box": [x1, y1, x2, y2],
        "center": [float((x1 + x2) * 0.5), float((y1 + y2) * 0.5)],
        "source": "yolo",
        "detector_confidence": float(confs[best_idx]),
    }


def _detect_seed_for_image(model: Any, image_bgr: Any, frame_idx: int, imgsz: int, device: str, det_conf: float) -> dict[str, Any] | None:
    return detect_yolo_seed_for_image(
        model=model,
        image_bgr=image_bgr,
        frame_idx=frame_idx,
        imgsz=imgsz,
        device=device,
        det_conf=det_conf,
    )


def detect_seed_causally_from_artifact(
    artifact: LocalClipArtifact,
    model: Any,
    imgsz: int,
    device: str,
    det_conf: float,
    seed_conf: float,
    min_box_size: float,
    frame_seq_start: int | None = None,
    frame_seq_end: int | None = None,
) -> tuple[dict[str, Any] | None, YoloSeedSearchInfo]:
    started = time.perf_counter()
    searched_frames = 0
    best_candidate: dict[str, Any] | None = None
    search_mode = "causal_frame_seq_window" if frame_seq_start is not None or frame_seq_end is not None else "causal"

    def build_search_info() -> YoloSeedSearchInfo:
        return YoloSeedSearchInfo(
            search_mode=search_mode,
            search_seconds=round(time.perf_counter() - started, 3),
            searched_frames=searched_frames,
            seed_conf_threshold=float(seed_conf),
            det_conf_floor=float(det_conf),
            min_box_size=float(min_box_size),
            best_candidate_conf=float(best_candidate["detector_confidence"]) if best_candidate is not None else None,
            best_candidate_frame=int(best_candidate["frame_idx"]) if best_candidate is not None else None,
            frame_seq_start=frame_seq_start,
            frame_seq_end=frame_seq_end,
        )

    for decoded_frame in artifact.iter_frames():
        frame_metadata = decoded_frame.metadata or {}
        frame_seq = int(frame_metadata.get("frameSeq", decoded_frame.frame_index))
        if frame_seq_start is not None and frame_seq < int(frame_seq_start):
            continue
        if frame_seq_end is not None and frame_seq > int(frame_seq_end):
            break

        searched_frames += 1
        candidate = _detect_seed_for_image(
            model,
            decoded_frame.image_bgr,
            decoded_frame.frame_index,
            imgsz=imgsz,
            device=device,
            det_conf=det_conf,
        )
        if candidate is None:
            continue

        x1, y1, x2, y2 = candidate["box"]
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        candidate["box_width"] = width
        candidate["box_height"] = height
        candidate["frame_seq"] = frame_seq

        if frame_metadata:
            candidate["frame_metadata"] = frame_metadata
            candidate["camera_timestamp_us"] = frame_metadata.get("cameraTimestampUs")
            candidate["pts_us"] = frame_metadata.get("ptsUs")

        if best_candidate is None or float(candidate["detector_confidence"]) > float(best_candidate["detector_confidence"]):
            best_candidate = dict(candidate)

        if width >= float(min_box_size) and height >= float(min_box_size) and float(candidate["detector_confidence"]) >= float(seed_conf):
            candidate["seed_mode"] = "causal_first_confident"
            return candidate, build_search_info()

    return None, build_search_info()


def analyze_artifact_with_yolo_seed(
    artifact_dir: Path | str,
    checkpoint_path: Path,
    output_root: Path | None = None,
    imgsz: int = 1280,
    device: str = "0",
    det_conf: float = 0.05,
    seed_conf: float = 0.8,
    min_box_size: float = 10.0,
    frame_seq_start: int | None = None,
    frame_seq_end: int | None = None,
) -> StandaloneYoloSeedResult:
    from laptop_receiver.local_clip_artifact import load_local_clip_artifact

    artifact = load_local_clip_artifact(artifact_dir)
    analysis_dir = _analysis_dir_for_artifact(artifact, output_root)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    from ultralytics import YOLO

    model = YOLO(str(checkpoint_path.resolve()))
    seed, search_info = detect_seed_causally_from_artifact(
        artifact,
        model,
        imgsz=imgsz,
        device=device,
        det_conf=det_conf,
        seed_conf=seed_conf,
        min_box_size=min_box_size,
        frame_seq_start=frame_seq_start,
        frame_seq_end=frame_seq_end,
    )

    preview_path = analysis_dir / "yolo_seed_preview.jpg"
    result_path = analysis_dir / "yolo_seed_result.json"
    seed_path = analysis_dir / "yolo_seed.json"

    if seed is None:
        result = StandaloneYoloSeedResult(
            kind="standalone_yolo_seed_result",
            success=False,
            artifact_dir=str(artifact.root_dir),
            analysis_dir=str(analysis_dir),
            preview_path="",
            failure_reason="yolo_detection_failed",
            seed=None,
            seed_search=asdict(search_info),
        )
        result_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        return result

    seed["checkpoint"] = str(checkpoint_path.resolve())
    seed["seed_search"] = asdict(search_info)
    seed["artifact_dir"] = str(artifact.root_dir)
    seed["video_path"] = str(artifact.video_path)

    import cv2

    frame_idx = int(seed["frame_idx"])
    capture = cv2.VideoCapture(str(artifact.video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video for preview: {artifact.video_path}")

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, image = capture.read()
    finally:
        capture.release()

    if ok and image is not None:
        _draw_box(image, seed["box"], (255, 255, 0), f"yolo seed f{frame_idx}")
        cv2.imwrite(str(preview_path), image)

    seed_path.write_text(json.dumps(seed, indent=2), encoding="utf-8")
    result = StandaloneYoloSeedResult(
        kind="standalone_yolo_seed_result",
        success=True,
        artifact_dir=str(artifact.root_dir),
        analysis_dir=str(analysis_dir),
        preview_path=str(preview_path) if preview_path.exists() else "",
        failure_reason="",
        seed=seed,
        seed_search=asdict(search_info),
    )
    result_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    return result
