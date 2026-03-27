# Quest Laptop Pipeline Spec

Last updated: 2026-03-27

## Goal

Build the lowest-latency practical v1 pipeline for:

- Quest 3 capture
- laptop-side classical seed detection
- laptop-side SAM2 tracking
- Quest-side MR replay

## Transport

Use one persistent full-duplex TCP connection.

Upstream from Quest:

- `Hello`
- `SessionConfig`
- `LaneCalibration`
- `ShotMarker`
- `FramePacket`

Downstream back to Quest:

- `TrackerStatus`
- `ShotResult`

## Upstream frame policy

For v1:

- use left camera only
- JPEG-compress frames on Quest
- bounded latest-frame queue on Quest so backlog does not grow without bound
- send intrinsics once per session
- send lane calibration when available

## Shot lifecycle

1. Quest streams frames continuously once armed.
2. Laptop keeps a short pre-roll buffer.
3. On `shot_started`, laptop begins recording frames for that shot.
4. Laptop runs the classical seed detector incrementally while frames arrive.
5. As soon as the seed is confirmed, laptop starts the live SAM2 camera predictor.
6. Live SAM2 catches up through already-saved frames and keeps tracking new frames during the rest of the shot.
7. On `shot_ended`, laptop finalizes outputs and returns a compact result payload to Quest.

## Why this is the current best architecture

This keeps three expensive things off the post-shot critical path:

- frame transfer
- seed detection
- some of the SAM2 tracking itself

The only remaining post-shot work is finalization and any fallback batch tracking if the live path failed.

## Seed stage

Seed stage is currently:

- classical dark compact motion heuristic
- running online during capture

This is a seed-only stage. It is not the final tracker.

## Tracker stage

Tracker stage is currently:

- live SAM2 camera predictor if seed arrives during capture
- warm batch SAM2 fallback if live tracking never starts or fails

## Outputs returned to Quest

Do not send rendered video back to Quest.

Return:

- tracked path samples
- seed metadata
- timing summary
- any confidence or failure flags

Quest should render the overlay locally.

## Current dependency layout

This repo is now self-contained for development:

- the laptop pipeline lives in `laptop_pipeline`
- the vendored `SAM2` source lives in `third_party/sam2`
- the `SAM2` tiny checkpoint is downloaded by `laptop_pipeline/setup_laptop_env.ps1`

The only required external runtime dependency is a machine with a CUDA-capable NVIDIA GPU and a working driver stack.
