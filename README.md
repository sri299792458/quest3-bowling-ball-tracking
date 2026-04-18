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

- `docs/`: product definition and supporting design notes
- `data/`: local validation data and other non-source assets
- `running_notes.md`: current execution log so we stay organized

