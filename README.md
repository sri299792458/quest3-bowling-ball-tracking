# Quest Bowling Standalone

This repository is the clean starting point for the standalone bowling replay product.

The active product definition lives in [docs/STANDALONE_PRODUCT_GOAL.md](C:/Users/student/QuestBowlingStandalone/docs/STANDALONE_PRODUCT_GOAL.md).

## Working Rules

- keep the scope centered on the standalone product, not the old experiment stack
- maintain [running_notes.md](C:/Users/student/QuestBowlingStandalone/running_notes.md) as the current build log and decision log
- use the local validation dataset at `C:\Users\student\QuestBowlingStandalone\data\bowling_tests`
- only commit deliberate checkpoints

## Current Baseline

- single camera
- `1280 x 960 @ 30 FPS, H.264`
- lightweight session lane lock
- rolling encoded buffer
- `YOLO -> SAM2`
- true lane-anchored MR replay

## Repository Layout

- `docs/`: product definition and implementation notes
- `unity_proof/`: clean Unity project for Quest-side standalone proof runs
- `quest_app/`: Quest-side standalone product module
- `laptop_receiver/`: laptop-side media, tracking, and replay module
- `protocol/`: shared schemas and message contracts
- `data/`: local validation data and other non-source assets
- `running_notes.md`: current execution log so we stay organized

## Immediate Build Slice

We are starting with one disciplined first slice:

- prove Quest-side local `H.264` encode at `1280 x 960 @ 30 FPS`
- preserve timestamp and pose metadata cleanly
- keep the repo structure ready for the later laptop and protocol pieces

## Current Milestone

Milestone `1` is now proven in the clean Unity proof app:

- local Quest-side `H.264` proof capture works
- a real `video.mp4` is written on-device
- per-frame metadata is written to `frame_metadata.jsonl`
- encoder surface binding and native blit path are working
- `ptsUs` in metadata is now camera-derived and coherent with the shot span

The latest successful proof artifact was pulled from the Quest to:

- `C:\Users\student\QuestBowlingStandalone\unity_proof\Temp\device_pull\standalone_local_clips\clip_2e2890ae03b64ce3b98d37938bf3b199_standalone-proof`

Important note:

- the proof diagnostics still show many `passthrough_not_updated` skips
- those skips are now understood as expected render-loop vs camera-source cadence mismatch
- current proof runs show about `72 Hz` render polling against a `~30 FPS` camera source, which matches the observed skip ratio closely

See [docs/IMPLEMENTATION_PLAN.md](C:/Users/student/QuestBowlingStandalone/docs/IMPLEMENTATION_PLAN.md) for the active build sequence.
See [docs/PORTING_MAP.md](C:/Users/student/QuestBowlingStandalone/docs/PORTING_MAP.md) for the exact archive files we should mine and what to avoid copying.
