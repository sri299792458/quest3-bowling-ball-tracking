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
- laptop-side standalone artifact validation now works against a pulled proof clip

The clean next slice after Quest proof is now in place:

- load `artifact_manifest.json`, sidecars, and `video.mp4` as one standalone artifact
- validate decoded video frames against `frame_metadata.jsonl`
- prove timestamp and metadata alignment before porting over more of the old laptop stack
- run standalone causal YOLO seeding directly on a `LocalClipArtifact`
- import one legacy `bowling_tests` run into the standalone artifact shape for real bowling-content validation
- run warm SAM2 from the standalone `yolo_seed.json` contract
- receive a live Quest `H.264` stream plus live metadata on the laptop
- make the landed live session decodable and loadable through the same analysis boundary as offline artifacts

Current validation entry point:

- `py -m pip install -r laptop_receiver/requirements.txt`
- `py -m laptop_receiver.validate_local_clip_artifact <artifact_dir>`
- `py -m laptop_receiver.run_yolo_seed_on_artifact <artifact_dir> --checkpoint <path-to-best.pt>`
- `py -m laptop_receiver.import_legacy_bowling_run <legacy_run_dir>`
- `py -m laptop_receiver.run_sam2_on_artifact <artifact_dir>`
- `py -m laptop_receiver.live_stream_receiver`

Important note:

- the proof diagnostics still show many `passthrough_not_updated` skips
- those skips are now understood as expected render-loop vs camera-source cadence mismatch
- current proof runs show about `72 Hz` render polling against a `~30 FPS` camera source, which matches the observed skip ratio closely

Live transport note:

- the main direction is now live Quest-to-laptop streaming
- Quest proof capture is being extended to stream encoded `H.264` media live while Unity sends frame metadata over a separate TCP side channel
- latest milestone: a real hotspot run now lands as a decodable live `H.264` session on the laptop, with codec config persisted and the shared loader able to open the session as a `LocalClipArtifact`

See [docs/IMPLEMENTATION_PLAN.md](C:/Users/student/QuestBowlingStandalone/docs/IMPLEMENTATION_PLAN.md) for the active build sequence.
See [docs/PORTING_MAP.md](C:/Users/student/QuestBowlingStandalone/docs/PORTING_MAP.md) for the exact archive files we should mine and what to avoid copying.
