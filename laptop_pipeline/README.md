# Laptop Pipeline

This folder contains the current Quest-to-laptop receiver for the bowling MR pipeline.

## What It Does

- accepts Quest WebRTC signaling over HTTP
- receives Quest video over WebRTC
- receives control and result messages over a WebRTC data channel
- records each shot as a JPEG frame sequence on the laptop
- runs the classical seed detector incrementally while the shot is still streaming
- starts a live `SAM2` camera predictor as soon as the seed is confirmed
- falls back to warm batch `SAM2` only if the live path never starts or fails
- sends status and final result JSON back to Quest

## Current Analysis Path

The current receiver uses:

- `quest_bowling_server.py`
- `sam2_bowling_bridge.py`
- `online_classical_seed.py`
- `live_sam2_camera_tracker.py`
- `warm_sam2_tracker.py`

The receiver is now a WebRTC endpoint backed by:

- `aiohttp`
- `aiortc`

## Repo-Local Dependencies

This pipeline uses the vendored `SAM2` source in:

- [`../third_party/sam2`](../third_party/sam2)

The setup script downloads the `sam2.1_hiera_tiny.pt` checkpoint into:

- `../third_party/sam2/checkpoints`

## Shot Lifecycle

1. Quest negotiates WebRTC with the laptop.
2. Quest sends the camera stream as a WebRTC video track.
3. Laptop keeps a short pre-roll buffer.
4. On `shot_started`, the laptop begins recording JPEG frames for that shot.
5. The classical seed detector runs online while frames arrive.
6. As soon as the seed is confirmed, live `SAM2` starts.
7. Live `SAM2` catches up through already-saved frames, then tracks new incoming frames.
8. On `shot_ended`, the laptop finalizes outputs and sends a compact result payload back to Quest over the data channel.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
.\laptop_pipeline\start_quest_bowling_server.cmd
```

If setup fails at the CUDA check, install a CUDA-enabled PyTorch build for that machine and rerun `setup_laptop_env.ps1`.

The setup script now also verifies:

- `aiohttp`
- `aiortc`
- repo-local `SAM2`
- CUDA-enabled `torch`

For a home test that skips real analysis and returns a fake-but-valid result payload, run:

```powershell
.\laptop_pipeline\start_quest_bowling_server_synthetic.cmd
```

## Output Layout

Each shot writes a run under:

- `laptop_pipeline/runs/<session>_<shot>_<timestamp>/`

Important outputs include:

- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `analysis/seed.json`
- `analysis/detections.csv`
- `analysis/pipeline_summary.txt`
- `analysis/sam2/track.csv`
- `analysis/sam2/summary.txt`
- `analysis/sam2/preview.mp4` when preview saving is enabled

## Requirements

- Python `3.10+`
- `laptop_pipeline/.venv`
- NVIDIA GPU with CUDA-enabled `torch`
- `aiohttp`
- `aiortc`
- vendored `SAM2` source in `third_party/sam2`
- `sam2.1_hiera_tiny.pt` in `third_party/sam2/checkpoints`
