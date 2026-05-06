# Vendored SAM2 Source

This folder contains the repo-local `SAM2` source used by the standalone laptop receiver.

## Origin

- upstream project: `facebookresearch/sam2`
- checkpoint source: `facebook/sam2.1-hiera-tiny` on Hugging Face
- upstream license: [LICENSE](LICENSE)

## Runtime Artifact

The model checkpoint is intentionally not committed. The expected local file is:

```text
third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt
```

Create it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_receiver\setup_laptop_env.ps1
```

The laptop receiver also accepts explicit overrides through `--sam2-root`, `--sam2-checkpoint`, or the `SAM2_REPO_ROOT` and `SAM2_CHECKPOINT_PATH` environment variables.

## How This Project Uses SAM2

The live bowling pipeline uses SAM2 as a tracker, not as the first detector.

Runtime flow:

1. YOLO scans the live Quest H.264 stream for the first high-confidence bowling ball box.
2. That YOLO box becomes the SAM2 prompt.
3. The laptop uses SAM2's camera predictor path through `build_sam2_camera_predictor`.
4. The tracker calls `load_first_frame(...)` on the YOLO seed frame, adds the box prompt, then calls `track(frame)` on each following decoded frame.
5. The mask output is converted into per-frame bbox, centroid, top-mask point, mask quality, and mask contour artifacts.
6. Those mask measurements are projected into lane space and smoothed into the final replay trajectory.

The project code for this wrapper is:

```text
laptop_receiver/live_camera_sam2_tracker.py
```

## Why We Do Not Use The Default Video Predictor For Live Replay

SAM2's standard video predictor API is built around a completed video or image folder:

```text
init_state(video_path)
add prompt
propagate_in_video(...)
```

That is a good offline workflow, and the repo still has a batch wrapper for artifact checks:

```text
laptop_receiver/standalone_warm_sam2_tracker.py
```

For the live Quest pipeline, that shape was too late in the loop. It meant waiting until a clip/window existed, initializing video state over that source, and then propagating through the shot before a replay could be produced.

The camera predictor path lets us treat SAM2 as an online tracker:

```text
load_first_frame(seed_frame)
add_new_prompt(bbox)
track(next_frame)
track(next_frame)
...
```

That matches the live stream better. We can start tracking from the YOLO seed frame and keep feeding decoded frames in order, instead of asking SAM2 to re-open and reason about a whole completed clip.

## Runtime Choices

- Model: `sam2.1_hiera_tiny.pt`.
- Device: CUDA.
- Predictor: `SAM2CameraPredictor`.
- Prompt: YOLO seed bbox.
- Model lifetime: warmed once and reused across shots in the live pipeline.
- Tracking stop: fixed live tracking window or sustained missing-mask frames.
- Output: `analysis_live_pipeline/camera_sam2/<windowId>/`.

Important output files:

```text
camera_sam2_result.json
track.csv
mask_contours.jsonl
seed.json
summary.json
```

`track.csv` is the bridge into trajectory reconstruction. It contains the mask-derived measurement point and timing metadata for every tracked frame.

## Presentation Summary

The short version for the final presentation:

- YOLO gives us fast causal ball discovery.
- SAM2 gives us high-quality mask tracking after the seed.
- We switched from SAM2's completed-video predictor shape to the camera predictor shape.
- This lets the system track frame-by-frame from the live stream instead of waiting for a full clip.
- The model stays warm across shots, so we avoid reloading SAM2 every throw.
- The resulting masks feed the lane-space trajectory and replay stats.
