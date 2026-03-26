# PC Tracking Prototype

This folder contains the first PC-side prototype for the new mainline plan:

- auto-seed the bowling ball with classical computer vision
- use that seed as the initialization point for a promptable video tracker such as `SAM 2`
- later return structured replay data to Quest for mixed reality rendering

The goal of this first prototype is not to solve the full project. It is to answer a narrower question:

`Can we automatically get a stable first ball seed from a bowling clip without any training data?`

## Current contents

- `seed_bowling_ball.py`
  - classical circle-based bowling-ball seeder
  - produces:
    - a detections CSV
    - a seed JSON with the first stable detection
    - an optional overlay video for debugging

- `requirements.txt`
  - minimal dependencies for the classical seeder

## Outputs

The seeder writes:

- `detections.csv`
  - per-frame circle detections
- `seed.json`
  - the first stable detection for downstream promptable tracking
- `overlay.mp4`
  - optional debug video with the detected circle and ROI

`seed.json` is the key bridge into the later `SAM 2` step. It contains:

- `seed_frame_index`
- `seed_point`
- `seed_box`
- `seed_radius`

## Setup

Create a Python environment in this folder if you want the prototype isolated from the Unity project:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Usage

Run the seeder on a bowling clip:

```powershell
.\.venv\Scripts\python.exe .\seed_bowling_ball.py `
  --input C:\path\to\bowling_clip.mp4 `
  --detections .\outputs\detections.csv `
  --seed .\outputs\seed.json `
  --overlay .\outputs\overlay.mp4
```

If `outputs` does not exist, create it first.

## Notes

- This is inspired by the classical `HoughCircles + adaptive ROI` approach used in the open `bowling-analysis` project, but simplified into a self-contained script.
- The current script is intentionally conservative. It prefers stable initialization over detecting something in every frame.
- The next step after this prototype is to feed the seed into `SAM 2` and evaluate whether the ball can be tracked through the clip without a trained bowling-specific detector.
