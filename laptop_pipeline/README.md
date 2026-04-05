# Laptop Pipeline

This folder contains the current Quest-to-laptop receiver for the bowling MR pipeline.

## What It Does

- accepts a reliable Quest control connection over TCP
- receives Quest JPEG frame payloads over UDP
- records each shot as a JPEG frame sequence on the laptop
- runs the classical seed detector incrementally while the shot is still streaming
- starts a live `SAM2` camera predictor as soon as the seed is confirmed
- falls back to warm batch `SAM2` only if the live path never starts or fails
- sends status and final result JSON back to Quest over the TCP control channel

## Current Analysis Path

The current receiver uses:

- `quest_bowling_server.py`
- `quest_bowling_udp_server.py`
- `sam2_bowling_bridge.py`
- `online_classical_seed.py`
- `live_sam2_camera_tracker.py`
- `warm_sam2_tracker.py`

## Repo-Local Dependencies

This pipeline uses the vendored `SAM2` source in:

- [`../third_party/sam2`](../third_party/sam2)

The setup script downloads the `sam2.1_hiera_tiny.pt` checkpoint into:

- `../third_party/sam2/checkpoints`

## Shot Lifecycle

1. Quest opens a TCP control connection to the laptop.
2. Quest sends session metadata and later shot markers over that control connection.
3. Quest sends JPEG-compressed frame payloads over UDP.
4. Laptop keeps a short pre-roll buffer.
5. On `shot_started`, the laptop begins recording JPEG frames for that shot.
6. The classical seed detector runs online while frames arrive.
7. As soon as the seed is confirmed, live `SAM2` starts.
8. Live `SAM2` catches up through already-saved frames, then tracks new incoming frames.
9. On `shot_ended`, the laptop finalizes outputs and sends a compact result payload back to Quest.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
.\laptop_pipeline\start_quest_bowling_server.cmd
```

If setup fails at the CUDA check, install a CUDA-enabled PyTorch build for that machine and rerun `setup_laptop_env.ps1`.

The setup script verifies:

- repo-local `SAM2`
- CUDA-enabled `torch`
- receiver/runtime Python imports

For a home test that skips real analysis and returns a fake-but-valid result payload, run:

```powershell
.\laptop_pipeline\start_quest_bowling_server_synthetic.cmd
```

For a transport diagnostic that records only raw received frames and reports counts back to Quest, run:

```powershell
.\laptop_pipeline\start_quest_bowling_server_diagnostic.cmd
```

For dataset capture, use the equivalent record-only launcher:

```powershell
.\laptop_pipeline\start_quest_bowling_server_record_only.cmd
```

For an auto-recording smoke-style capture that records the first fixed chunk of UDP frames, run:

```powershell
.\laptop_pipeline\start_quest_bowling_server_smoke.cmd
```

## Oracle Workflow For Recorded Alley Runs

When the heuristic initializer is too brittle, use the oracle workflow:

1. manually place one good initial prompt on each run
2. run exactly one warm `SAM2` pass from that prompt
3. review the resulting previews
4. export only reviewed-good runs into a detector training dataset

The current scripts are:

- `annotate_manual_seeds.py`
- `batch_track_manual_seeds.py`
- `review_oracle_runs.py`
- `review_oracle_previews.py`
- `export_oracle_yolo_dataset.py`

The default input root for this workflow is:

- `laptop_pipeline/runs/bowling_tests`

The manual seed file is:

- `laptop_pipeline/runs/bowling_tests/manual_seeds.json`

The review file is:

- `laptop_pipeline/runs/bowling_tests/oracle_reviews.json`

### 1. Annotate Manual Seeds

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\annotate_manual_seeds.py --only-missing
```

Controls:

- `a/d`: previous / next frame
- `j/l`: jump backward / forward by 10 frames
- drag mouse: draw the seed box
- `g`: jump to the suggested heuristic seed frame
- `r`: clear box
- `s`: save current run
- `n`: save and move to next run
- `p`: previous run
- `q`: quit

The seed schema is box-first:

- `frame_idx`
- `box: [x1, y1, x2, y2]`

It also allows optional future prompt refinement fields:

- `points: [[x, y], ...]`
- `point_labels: [1, 0, ...]`

### 2. Run Oracle SAM2

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\batch_track_manual_seeds.py --overwrite
```

Per run, this writes:

- `analysis_oracle/manual_seed.json`
- `analysis_oracle/manual_seed_preview.jpg`
- `analysis_oracle/sam2/track.csv`
- `analysis_oracle/sam2/summary.txt`
- `analysis_oracle/sam2/preview.mp4`
- `oracle_tracking_result.json`

### 3. Mark Reviewed Runs

For faster review, use the preview browser:

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\review_oracle_previews.py --autoplay
```

Hotkeys:

- `1`: `accepted` and move to next run
- `2`: `needs_work` and move to next run
- `3`: `rejected` and move to next run
- `0`: `pending` and move to next run
- `space`: pause / play
- `a/d`: previous / next frame when paused
- `n/p`: next / previous run
- `r`: restart current preview
- `q`: quit

You can also filter the browser, for example:

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\review_oracle_previews.py --only-status pending --autoplay
```

For non-interactive review bookkeeping from the terminal:

List current review status:

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\review_oracle_runs.py --list
```

Mark a run after reviewing its `analysis_oracle/sam2/preview.mp4`:

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\review_oracle_runs.py --run-name <run_name> --status accepted --notes "good prompt and stable track"
```

Useful statuses are:

- `accepted`
- `needs_work`
- `rejected`
- `pending`

### 4. Export Detector Training Data

After enough runs are marked `accepted`, export a YOLO-style one-class dataset:

```powershell
.\laptop_pipeline\.venv\Scripts\python.exe .\laptop_pipeline\export_oracle_yolo_dataset.py --statuses accepted --overwrite
```

This creates:

- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/dataset.yaml`
- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/images/train`
- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/images/val`
- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/labels/train`
- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/labels/val`
- `laptop_pipeline/datasets/bowling_ball_oracle_yolo/export_summary.json`

The export is biased toward the real runtime problem:

- early tracked positive boxes for initialization
- a few pre-seed empty frames as negatives
- run-level train/val split so neighboring frames from the same shot do not leak across splits

## Train The YOLO Initializer

The current first-pass detector setup is:

- model: `YOLO11s`
- task: `detect`
- dataset: `laptop_pipeline/datasets/bowling_ball_oracle_yolo`
- image size: `1280`
- batch size: `2`

Launch training with:

```powershell
.\laptop_pipeline\start_train_bowling_ball_yolo.cmd
```

Or inspect the resolved training config without starting:

```powershell
.\laptop_pipeline\start_train_bowling_ball_yolo.cmd --dry-run
```

Training outputs go under:

- `laptop_pipeline/runs/yolo_training`

This detector is intended only to provide the one initial ball box that starts `SAM2`.

## Output Layout

Each shot writes a run under:

- `laptop_pipeline/runs/<session>_<shot>_<timestamp>/`

Important outputs include:

- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `raw/manifest.json`
- `raw/capture_summary.json`
- `capture_context.json`
- `session_config.json`
- `lane_calibration.json`
- `quest_tracker_status.jsonl`
- `shot_events.jsonl`
- `analysis/seed.json`
- `analysis/detections.csv`
- `analysis/pipeline_summary.txt`
- `analysis/sam2/track.csv`
- `analysis/sam2/summary.txt`
- `analysis/sam2/preview.mp4` when preview saving is enabled

In diagnostic mode, the important outputs are:

- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `raw/manifest.json`
- `capture_context.json`
- `session_config.json`
- `lane_calibration.json`
- `shot_events.jsonl`
- `diagnostic_result.json`
- `shot_result.json`

In smoke mode, the important outputs are:

- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `raw/manifest.json`
- `smoke_result.json`

## Requirements

- Python `3.10+`
- `laptop_pipeline/.venv`
- NVIDIA GPU with CUDA-enabled `torch`
- vendored `SAM2` source in `third_party/sam2`
- `sam2.1_hiera_tiny.pt` in `third_party/sam2/checkpoints`
