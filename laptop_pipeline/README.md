# Laptop Pipeline

This folder contains the current Quest-to-laptop receiver for the bowling MR pipeline.

## What it does

- listens for the Quest TCP stream
- parses the custom binary packet protocol
- receives Quest shot markers
- stores each shot as a JPEG frame sequence
- runs the classical seed heuristics incrementally while the shot is still streaming
- starts a live SAM2 camera predictor as soon as the seed is confirmed
- keeps a warm batch SAM2 path only as fallback
- sends status or result JSON back to Quest

## Current analysis path

The current receiver uses:

- `sam2_bowling_bridge.py`
- `online_classical_seed.py`
- `live_sam2_camera_tracker.py`
- `warm_sam2_tracker.py`

That bridge:

- records Quest shot frames into `laptop_pipeline/runs/.../raw/frames/000000.jpg`
- stores per-frame metadata in `frames.jsonl`
- keeps a small pre-roll buffer and flushes it into the shot when recording starts
- runs the same classical heuristics from the external `sam2_bowling_eval` workspace, but in-process and incrementally
- writes `analysis/seed.json`, `best_detection.jpg`, `detections.csv`, and `pipeline_summary.txt`
- when the seed is confirmed, starts a live SAM2 camera predictor from the seed frame and catches up through already-saved frames
- then keeps tracking each incoming frame during the rest of the shot
- only falls back to the older warm batch SAM2 path if the live path fails or never starts

## External dependency

This repo currently depends on the external SAM2 evaluation workspace at:

- `C:\Users\student\sam2_bowling_eval`

Override that path with:

```powershell
$env:SAM2_BOWLING_EVAL_ROOT='C:\path\to\sam2_bowling_eval'
```

That external workspace currently contains:

- the optimized SAM2 runtime setup
- the classical seed code
- the patched local SAM2 checkout with the live camera predictor

## Shot lifecycle

The receiver expects Quest to send `ShotMarker` packets:

- `shot_started` (`2`)
- `shot_ended` (`3`)

When `shot_started` arrives:

- the server opens a JPEG-frame recorder
- flushes a small pre-roll buffer into the shot folder
- continues appending all incoming shot frames
- samples frames for online seed detection while the shot is still in progress

When the seed is confirmed:

- the server initializes the live SAM2 camera predictor from the seed frame
- catches up through any already-saved post-seed frames
- continues tracking each new frame as it arrives

When `shot_ended` arrives:

- the server closes the frame recorder
- finalizes the already-running seed detector outputs
- if live SAM2 was running, only writes out its accumulated results
- otherwise falls back to warm batch SAM2 against the saved frame folder
- sends the parsed result JSON back to Quest

## Run

```powershell
C:\Users\student\sam2_bowling_eval\.venv\Scripts\python.exe .\laptop_pipeline\quest_bowling_server.py --host 0.0.0.0 --port 5799
```

Or use:

- `start_quest_bowling_server.cmd`

## Dependencies

- Python 3.10+
- `numpy`
- `opencv-python`
- `Pillow`

The actual SAM2 analysis runs through the existing `sam2_bowling_eval` virtual environment.
