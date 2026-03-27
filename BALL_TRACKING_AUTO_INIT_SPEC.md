# Bowling Ball Auto-Initialization Spec

Last updated: 2026-03-27

## Goal

Remove manual seeding from the PC tracking prototype so a short bowling clip can be processed automatically enough to support immediate post-shot MR replay.

This spec only covers the **PC-side automatic initializer** that chooses the first bowling-ball box and hands it to SAM2. It does not replace the larger project spec in [BALL_TRACKING_SPEC.md](C:/Users/student/Quest3BowlingBallTracking/BALL_TRACKING_SPEC.md).

## Why This Exists

Manual seeding was a useful feasibility check, but it is not a product path. If we want:

- Quest capture
- PC analysis
- Quest replay

then we need the PC side to find the ball on its own at least once per shot.

SAM2 is still useful here, but it needs an initializer. The smallest realistic next step is:

- `Grounding DINO` to find a bowling-ball box on an early frame
- `SAM2` to propagate that box through the short shot clip

## v1 Automatic Route

### Detector

- model family: `Grounding DINO`
- prompt: `bowling ball . sports ball .`
- runtime: local PC GPU
- input: a short early-frame scan window from the bowling clip

### Tracker

- model family: `SAM2.1`
- prompt type: **box-only**
- runtime: local PC GPU
- propagation: forward through the clip from the detected seed frame

## Scope

### In scope

- short bowling clips
- automatic seed selection from a frame window
- selecting one best bowling-ball box
- handing that box to the existing optimized SAM2 runner
- saving detector artifacts and SAM2 outputs in one clean result folder

### Out of scope

- full live Quest integration
- lane-corner estimation
- multi-object identity tracking
- spin estimation
- perfect robustness on every clip

## Detection Strategy

The initializer scans a configurable frame window, for example:

- start frame: `20`
- end frame: `140`
- step: `4`

For each scanned frame:

1. run Grounding DINO with `bowling ball . sports ball .`
2. keep detections over a configurable confidence threshold
3. compute a simple ranking score using:
   - detector confidence
   - box squareness
   - box area plausibility
   - mild position prior favoring the lower half of the frame
4. select the highest-ranked candidate across the scan window

The selected box becomes the SAM2 seed.

## Output Layout

Each automatic-init run should save:

- `pipeline_summary.txt`
- `detections.csv`
- `best_detection.jpg`
- `seed.json`
- `sam2/summary.txt`
- `sam2/track.csv`
- `sam2/preview.mp4`

This keeps detector output and tracker output together.

## Success Criteria

The first implementation is considered successful if:

- Grounding DINO finds a plausible bowling-ball box on at least one test clip
- that box is close enough to a known-good manual seed to start SAM2 correctly
- the resulting SAM2 preview is visibly following the ball for a meaningful segment

## Failure Criteria

The first implementation is considered a failure if:

- no plausible box is found in the scan window
- the selected box lands on the wrong object
- SAM2 starts from the selected box but clearly tracks the wrong thing

## Next Steps After v1

If this automatic route works, the next improvements are:

- smarter frame-window selection
- better candidate ranking
- fallback prompts or re-detection
- later comparison against a trained detector once bowling labels exist
