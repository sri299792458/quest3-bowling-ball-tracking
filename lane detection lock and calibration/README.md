# Lane Detection Lock And Calibration

This folder is the compact handoff bundle for the lane side of the project.

It combines the required `lane-detection V1` runtime pieces with the newer lane-lock and recalibration workflow, without bringing along old milestone outputs, validation artifacts, or unrelated project folders.

## What This Bundle Does

The pipeline is:

1. Read a Quest recording with frames plus pose metadata.
2. Let the operator choose the best frame with visible lane edges.
3. Suggest candidate click points on that frame.
4. Let the operator choose the best two near-lane points.
5. Solve the lane in world coordinates and build a reusable lane lock.
6. Reuse that lane lock across later recordings while metadata stays continuous.
7. Detect a metadata break automatically at recording boundaries.
8. Ask for recalibration when the old lane lock is no longer trustworthy.
9. Save lane-lock artifacts, projected overlays, and per-recording boundary decisions.

Current laptop interaction:

- `c`: recalibrate
- `s`: continue on warning-only boundaries
- `k`: skip recording
- `q`: quit

There is no Quest-side calibration button in this bundle yet. The calibration prompt is laptop-side only.

## Why Srinivas Needs This

This bundle gives Srinivas the lane-space reference needed to align ball trajectory with the lane.

The most important outputs are:

- `lane_lock.json`
- `applied_lane_lock.json`
- `boundary_continuity.json`
- `session_summary.json`

The most important fields for sync are:

- `lane_points_world`
- `world_to_lane_matrix`
- `lane_to_world_matrix`
- `plane_normal_world`
- `lane_width_m`
- `lane_length_m`

If `boundary_continuity.json` says `recalibration_required`, the previous lane lock should not be trusted for new trajectory-to-lane sync until a fresh lock is produced.

## Included Files

- `lane_lock_calibration/`
  The reusable lane-lock, geometry, path, and calibrated-session workflow code.
- `lane_detection_v1_runtime/src/`
  The minimal legacy runtime copied from `lane-detection V1` that the calibration flow depends on.
- `lane_detection_v1_runtime/scripts/run_recording_workflow.py`
  The original frame-selection and 2-click annotation UI reused by the calibrated workflow.
- `config/camera_intrinsics_reference_run.json`
  Camera intrinsics used by the lane solver.
- `config/lane_dimensions.json`
  Lane dimensions used by the project.
- `scripts/run_calibrated_session_workflow.py`
  Main recording-by-recording workflow with calibration detection.
- `scripts/build_lane_lock_from_annotation.py`
  One-off lane-lock builder from a saved annotation.
- `scripts/start_calibrated_session_workflow.ps1`
  Windows PowerShell launcher.
- `requirements.txt`
  Minimal Python dependencies.

## Not Included On Purpose

- raw recording data
- milestone output folders
- previous validation outputs
- simulation-only scripts
- unrelated Quest, UI, or ball-tracking code

This folder is meant to stay focused on lane detection, lane locking, and recalibration.

## Expected Inputs

By default, the scripts look for:

- raw recordings under `data/raw_runs/raw_upload_bundle/`
- saved annotations under `annotations/recordingN/reference_annotation.json`

If your data lives elsewhere, pass explicit paths with:

- `--raw-root`
- `--annotation-root`

## Install

```powershell
pip install -r ".\lane detection lock and calibration\requirements.txt"
```

## Main Manual Workflow

```powershell
python ".\lane detection lock and calibration\scripts\run_calibrated_session_workflow.py" `
  --raw-root "C:\path\to\raw_upload_bundle" `
  --start-recording 1 `
  --end-recording 21
```

PowerShell launcher:

```powershell
& ".\lane detection lock and calibration\scripts\start_calibrated_session_workflow.ps1" `
  --raw-root "C:\path\to\raw_upload_bundle" `
  --start-recording 1 `
  --end-recording 21
```

If you already have saved annotations and want to auto-replay boundaries offline:

```powershell
python ".\lane detection lock and calibration\scripts\run_calibrated_session_workflow.py" `
  --raw-root "C:\path\to\raw_upload_bundle" `
  --annotation-root "C:\path\to\annotations" `
  --auto-use-existing-annotations `
  --auto-recalibrate-required `
  --auto-continue-warnings `
  --start-recording 1 `
  --end-recording 21 `
  --session-name "auto_replay"
```

## Output Layout

Each session writes to:

- `calibration output/<session_name>/`

Each recording folder writes:

- `recording_metadata.json`
- `boundary_continuity.json`
- `boundary_prompt_preview.jpg`
- `applied_lane_lock.json`
- `continuous_reprojection/`

Calibration recordings also write:

- `lane_lock.json`
- `reference_annotation.json`
- `intrinsics_used.json`
- `lane_dimensions_used.json`
- `lane_lock_reference_overlay.jpg`
- `lane_lock_base_geometry.jpg`

## Project Constants

- lane width: `1.0541 m`
- lane length: `18.288 m`
- default metadata warning threshold: `12 deg`
- default metadata recalibration threshold: `20 deg`

## Verified Behavior In The Current Dataset

The calibrated workflow was checked against the existing recordings and behaved as expected:

- initial calibration on `recording1`
- recalibration required on `recording2`
- stable reuse through `recording19`
- recalibration required on `recording20`
- stable reuse again on `recording21`
