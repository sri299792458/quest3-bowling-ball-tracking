# Quest 3 Bowling Ball Tracking Spec

Last updated: 2026-03-26

## 1. Goal

Build a mixed reality bowling analytics research prototype where:

- the bowler wears a Quest 3
- the headset captures the real throw using its front cameras
- analysis runs quickly enough to return results immediately after the shot
- the user then sees a replay path and metrics anchored to the real lane in mixed reality

This is a research prototype, not a production scoring system.

## 2. User Experience

The user story is the most important part of the project.

### v1 target experience

1. The bowler puts on the Quest 3.
2. The app starts a bowling session and asks for a quick calibration.
3. The bowler faces downlane and confirms the lane direction.
4. The bowler throws normally.
5. During the throw, the system captures frames and tracking data in the background.
6. Immediately after the shot, the user sees:
   - the path of the ball over the real lane
   - release speed
   - a speed curve over the tracked segment
   - breakpoint estimate
   - confidence or loss markers if the track was weak

### What v1 is not

v1 is not:

- a flat video-analysis app
- a cloud service
- a live coaching overlay during the approach
- a spin-analysis product

The mixed reality part matters because the replay should appear attached to the real lane, not just shown on a floating 2D panel.

## 3. Product Definition

This project has two layers:

### Analytics engine

- detect the ball
- track it over time
- estimate path, speed, and breakpoint
- log data for evaluation and debugging

### MR presentation layer

- place the replay back onto the real lane
- show analytics from the bowler's current viewpoint
- keep the replay spatially anchored as the user moves their head

The product is MR because the results are presented in the real bowling environment, not because Quest is merely used as a camera.

## 4. Core Architecture

### 4.1 Sensor source

Sensor input comes from the Quest 3 front cameras through Meta's Passthrough Camera API / Camera2 path.

We should treat this as:

- CV-usable camera data
- headset pose and motion data
- mixed reality display capability

We should not treat it as high-quality cinematic video.

### 4.2 v1 compute split

The v1 architecture is hybrid:

- `Quest`
  - capture camera frames
  - capture timestamps and headset pose
  - control calibration and session flow
  - render the replay in MR

- `PC`
  - run the heavier ball-tracking pipeline
  - compute path and metrics
  - return structured replay data to the headset

### 4.3 Why hybrid is the baseline

This split is the best first product architecture because:

- it preserves the MR user experience
- it avoids overcommitting to Quest-only inference too early
- it leaves room for heavier models and fast iteration on PC
- it still allows us to move more logic onto Quest later if the pipeline proves lightweight enough

## 5. Runtime Data Flow

### Upstream: Quest to PC

During the shot, Quest streams:

- camera frames
- timestamps
- headset pose / motion data
- calibration metadata

The system should stream during capture rather than wait to upload the full video at the end.

### Downstream: PC to Quest

The PC should send back structured replay data, not rendered video frames.

That payload should include:

- trajectory points
- replay timestamps
- release point
- breakpoint point
- speed samples
- confidence values
- failure flags if needed

Quest then renders the replay locally in MR.

This keeps the bandwidth low and preserves true spatial replay instead of turning the result into a flat returned video.

## 6. Timing Target

### v1 timing mode

The target timing mode is:

- `immediate post-shot MR replay`

That means:

- the user bowls normally
- the system processes during capture or near-online
- results appear shortly after the shot ends

### Not the initial target

The initial target is not:

- fully offline video processing minutes later
- fully live analytics during the roll

Live during-roll overlays may be explored later, but the first milestone should be immediate post-shot replay.

## 7. Scope

### In scope for v1

- Quest 3 as the wearable capture and MR device
- PC-side ball-tracking analysis
- single-ball tracking
- immediate post-shot MR replay
- release speed estimate
- speed curve over the tracked segment
- breakpoint estimate
- saved logs for offline debugging and model improvement
- minimal calibration without physical markers
- confidence-aware output

### Out of scope for v1

- spin / rev-rate estimation
- pin impact analytics
- oil-pattern inference
- full cloud architecture
- coach-grade certified accuracy
- guaranteed perfect late-lane tracking

## 8. Main Technical Decisions

### 8.1 Baseline tracker stack

The initial baseline remains:

- custom one-class `YOLOv9t` detector
- single-ball constant-velocity Kalman filter

Why:

- it is the lowest-risk path that matches our current working Unity / Quest prototype work
- the ball class is known in advance
- Kalman tracking is simple, debuggable, and good at bridging short misses

### 8.2 Geometry policy

Depth is optional, not required.

The analytics engine should not fail just because scene depth or scene understanding is noisy.

Use geometry in this priority order:

1. manual lane calibration + known lane geometry
2. headset pose and motion data
3. Depth API / MRUK / scene understanding when helpful
4. stereo / dense geometry experiments as optional enhancements

### 8.3 Headset motion and IMU

Headset motion should be part of the system design.

Use it for:

- egomotion compensation
- tracker prediction
- ROI stabilization
- confidence estimation under rapid head movement

Do not treat headset IMU as if it directly measures the ball.

### 8.4 Benchmark models

These are benchmark candidates, not the initial product baseline:

- TrackNet-style temporal ball tracker
- `RF-DETR-N`
- `SAM 3`

SAM 3 is especially interesting for the PC-side benchmark path because it supports tracking through time, but it is not a blocker for the first spec or first implementation.

## 9. Calibration and MR Alignment

Calibration must stay minimal and understandable to the user.

### v1 assumptions

- the user stands near the foul line
- the user faces downlane during calibration
- regulation lane geometry is a valid prior

### v1 calibration actions

1. face downlane
2. hold still briefly
3. confirm with `A` or pinch

### Outputs

- lane origin near the foul line
- lane forward axis
- approximate lane plane
- handedness setting

### Alignment philosophy

The replay must be anchored to the real lane, but we should not assume perfect reconstruction of the entire alley.

The goal is useful spatial replay, not survey-grade geometric accuracy.

## 10. Algorithms Not Chosen as the Primary v1 Path

### Classical thresholding / Otsu

Not the main detector.

Reason:

- too brittle under reflections, blur, and low-detail passthrough images

### HoughCircles-only detection

Not the main detector.

Reason:

- useful as a classical reference and for offline experiments
- too fragile as the primary production-tracking path for Quest-captured bowling footage

### SAM 3 as the required v1 core

Not the required first implementation path.

Reason:

- gated model access and heavier environment requirements
- PC-side benchmark candidate, but not something the whole project should block on

### Spin estimation

Deferred.

Reason:

- even promising classical bowling spin work still depends on visible ball texture, noisy post-processing, and controlled enough footage
- that makes it a poor first commitment for Quest-based MR analytics

## 11. Verification Strategy

We should not use the bowling alley as the first place we learn whether each algorithm change works.

### 11.1 Offline-first development

Build and maintain an offline evaluation harness that can run the same detector / tracker logic on recorded clips.

Input sources:

- Quest-recorded clips
- public bowling videos
- later, real project data from lane tests

Outputs:

- overlaid videos
- per-frame detections
- filtered trajectories
- speed / breakpoint summaries
- error and failure reports

### 11.2 Labeling strategy

Start with manual ball center-point labels.

Why:

- faster than full segmentation or full-box labeling
- enough to evaluate tracking continuity and center error

### 11.3 Acceptance before alley sessions

A candidate change should pass offline gating if:

- it tracks a useful visible segment of the roll
- the path is visually plausible
- release speed is plausible when the early track is good
- breakpoint is plausible or explicitly marked low-confidence
- logs explain failures clearly

## 12. Dataset Strategy

### Initial data sources

- Quest-captured bowling clips
- public bowling video clips
- small public bowling datasets for bootstrapping only

### Training target

Train a one-class bowling-ball detector first.

The first objective is:

- reliable early-lane acquisition
- useful mid-lane continuity
- enough stability to support replay and release-speed estimation

### Hard examples to collect

- glossy balls
- dark balls
- motion blur
- release occlusion
- low-light lanes
- different handedness
- head motion during the shot

## 13. Planned Modules

### Quest side

- `SessionController`
- `LaneCalibrationController`
- `FrameStreamer`
- `PoseLogger`
- `ReplayPresenter`
- `MetricsHud`

### PC side

- `BallDetector`
- `BallMeasurementSelector`
- `BallKalmanTracker`
- `LaneProjector`
- `RollSegmenter`
- `RollMetricsComputer`
- `ReplayResultBuilder`
- `RollLogger`

## 14. Logging Requirements

Every armed shot should produce a record, even if the result is poor.

Each shot record should include:

- timestamps
- frame references
- headset pose
- calibration data
- raw detections
- selected measurements
- filtered trajectory
- confidence values
- release-speed result
- breakpoint result
- failure reason when applicable

Bad runs are valuable training and debugging data and should not be dropped silently.

## 15. Risks

Highest risks:

- the ball becomes too small downlane for reliable tracking
- headset motion hurts stability
- Quest camera quality is weaker than curated RGB datasets
- lane alignment may be approximate rather than exact
- a bowling-specific dataset will need to be built over time

Mitigations:

- one-class detector training
- Kalman smoothing
- headset-pose-aware prediction
- confidence-aware replay
- hybrid Quest + PC architecture
- offline harness before lane deployment

## 16. Deliverables

### First meaningful deliverable

- Quest captures a real shot
- PC processes the shot during or immediately after capture
- Quest shows an MR replay path on the real lane

### v1 deliverables

- working hybrid Quest + PC prototype
- immediate post-shot MR replay
- release speed and breakpoint estimates
- saved logs
- offline evaluation harness
- first bowling-specific detector baseline

## 17. Final Baseline Decision

If we freeze the starting product plan now, it is:

- Quest 3 as capture device and MR display
- PC as the analytics engine
- upstream streaming during the shot
- downstream structured replay data back to Quest
- immediate post-shot MR replay
- custom one-class `YOLOv9t` + Kalman baseline
- optional depth and scene understanding, not required
- SAM 3, RF-DETR, and TrackNet-style methods reserved for benchmark experiments rather than the first required implementation

That is the clearest version of the project we should build first.
