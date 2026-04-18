# Standalone Product Goal And Architecture Decisions

Last updated: 2026-04-18

This document is the clean starting point for the standalone bowling project.

It is intentionally short and opinionated.

## Product Goal

The product goal is:

- capture a bowling shot on Quest
- preserve enough visual quality, timing accuracy, and geometry to recover a trustworthy ball trajectory
- compute replay plus analytics shortly after the shot ends
- render that replay anchored to the real bowling lane in mixed reality

This is **not** a generic camera streaming project.
This is a bowling replay and analytics product.

## Primary Success Criteria

A successful system should:

- capture the full shot at the product target of `30 FPS`
- use the media baseline `1280 x 960 @ 30 FPS, H.264`
- preserve correct timestamps and poses for every frame
- recover a stable bowling-ball track on the laptop
- return replay and analytics with low post-shot latency
- align the replay to the recovered real lane

## Locked Architecture Decisions

These are the current decisions for the standalone build.

### 1. Single Camera First

Use one passthrough camera feed first.

Reason:

- it is enough to build a full end-to-end product
- it keeps transport, synchronization, and tracking complexity manageable
- lane geometry and calibration already give us strong structure priors

### 2. Hardware H.264 First

Use hardware `H.264 / AVC` as the baseline media codec at `1280 x 960 @ 30 FPS`.

Reason:

- it is the safest practical Android baseline
- it removes CPU JPEG encoding from the critical path
- it supports buffering compressed shots efficiently on Quest

The first product target is `1280 x 960 @ 30 FPS, H.264`, not maximum possible source FPS.

### 3. Lightweight Session Lane Registration

The system must recover lane geometry once per session, but the workflow should stay lightweight and natural.

Reason:

- true world-anchored replay requires a stable lane-to-world transform
- manual clicking or physical calibration targets are not acceptable defaults
- a completely invisible fully automatic solve is likely too brittle
- Quest scene APIs give us useful spatial context, but they do not directly give us a bowling-lane model
- bowling lanes still have strong known geometry, so lane structure should remain a core prior

Practical meaning:

- user naturally looks down the target lane before bowling
- app captures a short burst of ordinary lane-view frames and fits the lane model automatically
- app explicitly confirms success, e.g. `lane locked`
- the solved lane model is then cached for the session
- re-registration happens only if confidence later becomes invalid

The lane plane should still be treated as the world frame for replay and analytics.
This is a small explicit product step, not a manual calibration workflow.

### 4. YOLO Seed + SAM2 Tracking

The current tracking hypothesis for the standalone product is:

- `YOLO` for first acquisition of the ball
- `SAM2` for robust temporal tracking after acquisition

Reason:

- `YOLO` is good for the initialization problem
- `SAM2` is good for object continuity over time
- this is the best proven combination we currently have

This is the working default until a better approach is shown with evidence.

### 5. Kalman Filter Is Optional Post-Processing

Do not use a Kalman filter as the primary tracker.

Use it later only if it improves:

- smoothing
- short-gap filling
- velocity estimation
- lane-space trajectory fitting

### 6. Transport Exists To Serve Replay, Not The Other Way Around

The transport goal is:

- preserve the shot faithfully
- deliver it to the laptop quickly enough for replay after the shot

The transport does **not** need to prioritize perfect real-time live streaming during the shot if that hurts shot fidelity.

### 7. Session-Level Rolling Capture With Automatic Shot Boundaries

The app should not depend on a manual record button for every shot.

Reason:

- fixed-duration shot recordings waste time and storage on useless lead-in footage
- the user may hold the ball with both hands during approach
- continuous session capture fits hardware `H.264` better than frequent start/stop encoder churn

Practical meaning:

- Quest keeps a rolling encoded buffer during the session
- a shot is saved by marking `shot_start_time` and `shot_end_time` inside that stream
- the saved clip includes a small pre-roll and post-roll
- shot boundaries should be driven by ball/release evidence, not button presses

The goal is to save the useful shot window, not an arbitrary fixed 5-second clip.

## Data We Must Capture

### Session-Level

- session id
- shot id
- camera intrinsics
- camera side
- requested and actual camera resolution
- requested and actual source framerate
- selected codec and bitrate
- lane registration state / solved lane model
- last lane-lock confidence / timestamp

### Per-Frame

- frame sequence id
- camera timestamp
- camera pose
- head pose
- frame dimensions
- codec timestamp / PTS mapping
- keyframe flag or equivalent decode metadata

Metadata is cheap compared to video and should be captured aggressively.

### Shot-Level

- shot start marker / `shot_start_time`
- shot end marker / `shot_end_time`
- lane-lock state at shot start
- pre-roll and post-roll duration used for export
- shot trigger reason

## What The Standalone System Should Contain

The standalone project should contain only the pieces needed for the real product:

- Quest app
- laptop receiver
- transport/protocol definitions
- lightweight lane registration flow
- replay + analytics pipeline
- minimal docs

It should not start by copying:

- old JPEG transport experiments
- WebRTC experiments
- classical seeding experiments
- oracle labeling tools
- YOLO hillclimb and training utilities

Those can be copied in later only if they are still justified.

## Session Flow

The default standalone flow should be:

1. user looks down the target lane naturally
2. Quest fits lane geometry and confirms `lane locked`
3. Quest keeps a rolling encoded session buffer in the background
4. shot trigger fires automatically when a real release event is detected
5. the useful shot span is cut from the rolling buffer using `shot_start_time` and `shot_end_time`
6. laptop decodes the clip and reconstructs frames plus metadata
7. `YOLO` finds the initial ball seed
8. `SAM2` tracks the ball through the shot
9. the track is projected into the registered lane frame
10. anchored replay and analytics are returned to Quest

### Shot Trigger Principle

The shot trigger should be based on release evidence, not a manual button press.

Good trigger evidence includes:

- first confident ball appearance in the expected release corridor
- immediately plausible downlane motion
- agreement with the current lane registration

### Shot End Principle

The shot should end automatically when the ball is no longer useful for replay and analytics.

Good stop conditions include:

- the tracked ball leaves the useful downlane region
- the track is lost for a sustained short window while the lane is still visible and no reacquisition occurs
- a reasonable maximum shot duration is reached
- a small post-roll has been captured

Track loss alone is not enough to end the shot immediately.

If the user briefly looks away from the lane after release:

- keep the shot open for a short grace window
- try to reacquire the ball when the lane comes back into view
- only close the shot if reacquisition fails or the ball had already reached the terminal useful lane region

This avoids ending the shot too early just because the headset view dipped away from the lane for a moment.

## Recommended First Milestones

1. Quest-side local `H.264` encode proof-of-life from the passthrough/render path
2. lightweight session lane registration with explicit `lane locked` confirmation
3. rolling encoded session buffer with automatic shot start/end markers
4. encoded shot transport from Quest to laptop
5. decoded frame + metadata reconstruction on laptop
6. `YOLO -> SAM2` on the standalone pipeline
7. lane-space replay and analytics

## First Validation Dataset

The first end-to-end validation set for the standalone pipeline should be the real Quest-captured [bowling_tests](C:/Users/student/QuestBowlingStandalone/data/bowling_tests) collection.

This dataset should be used first to validate:

- lane lock workflow
- shot trigger logic
- shot end / grace / reacquire logic
- `YOLO -> SAM2` behavior on real Quest captures
- replay timing and clip-boundary quality

Only after the pipeline is behaving well on `bowling_tests` should we treat external clips as the next generalization check.

## Non-Goals For The First Standalone Version

- dual-camera stereo
- HEVC as a required dependency
- perfect during-shot real-time overlay
- detector training infrastructure
- legacy compatibility with every experiment in the old repo

## Final Principle

The standalone project should be judged by one question:

> Does it produce a trustworthy, lane-aligned bowling replay with analytics from real Quest shots?

If a component does not help that outcome, it should not be in the first standalone build.
