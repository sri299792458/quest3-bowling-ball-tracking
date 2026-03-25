# Quest 3 Bowling Ball Tracking Spec

Last updated: 2026-03-25

## 1. Goal

Build a Quest 3 mixed reality research prototype that turns a real bowling lane into a live analytics system. The bowler wears the headset, rolls a real ball, and then sees a post-shot replay that visualizes:

- visible ball path
- release speed
- continuous speed estimate over the tracked segment
- breakpoint estimate
- confidence / loss markers when tracking becomes weak

This is a research prototype, not a production scorer.

## 2. Product Scope

### In scope for v1

- Quest 3 local-only runtime
- passthrough-camera-based ball detection on device
- single-ball tracking
- post-shot replay
- saved logs for offline analysis
- minimal lane setup without physical markers
- explicit confidence and failure reporting

### Out of scope for v1

- spin / rev-rate estimation
- pin impact analytics
- exact oil-pattern inference
- cloud inference
- multi-camera external tracking
- coach-grade certified accuracy

## 3. Hard Constraints

- Platform: Meta Quest 3
- Runtime processing: fully local on headset
- Camera source: Quest passthrough camera API
- Unity runtime path: Unity Inference Engine
- Current working backend: `GPUCompute`
- UX mode: post-shot replay, not live overlay during approach
- Camera setup: headset worn by the bowler

## 4. Runtime Success Criteria

The runtime pipeline is considered successful for v1 if:

1. The app starts reliably on Quest 3.
2. The user can enter the bowling tracking scene and start inference on device.
3. The system can track a bowling ball for a useful portion of the roll under at least some real lane conditions.
4. The app can render a replay path and compute a release-speed estimate when tracking is stable early in the shot.
5. The app records enough data to debug misses and improve the detector offline.
6. When tracking is weak, the UI shows uncertainty instead of silently pretending the estimate is exact.

## 5. Problem Characterization

This is a difficult small-fast-object tracking problem with extra constraints:

- the ball is small relative to the full lane view
- the ball can be glossy and reflective
- the ball can blur after release
- the camera is egocentric and moving with the wearer
- the ball may be partially occluded by the body at release
- the lane is long, so the ball becomes very small downlane
- Quest passthrough image quality is worse than curated RGB datasets

The literature and prior product work suggest that this should be treated as a structured sports-tracking problem, not a generic object-detection demo.

## 6. Chosen Baseline Algorithm

### 6.1 Detector

Baseline detector: custom one-class `YOLOv9t`

Why this is the baseline:

- Meta's official Quest sample path already uses a quantized `YOLOv9t`-style model
- the current project already has a working Quest inference path for this family
- the model class is known in advance: bowling ball
- a small one-class detector is a better fit than a general segmentation model on Quest

Runtime requirements:

- export through ONNX into Unity Inference Engine format
- quantize to `uint8`
- run at `640x640` first unless profiling forces a change
- use `GPUCompute`

### 6.2 Tracker

Baseline tracker: single-ball constant-velocity Kalman filter

Why:

- only one ball matters
- the ball may briefly disappear because of blur or missed detections
- Kalman filtering gives a clean way to smooth position and bridge short misses
- it is simple enough to debug and tune on-device

The tracker state should include at minimum:

- lane-frame position
- lane-frame velocity
- track confidence
- frames since last accepted detection

### 6.3 Geometry Layer

The detector alone is not enough. We need a geometry layer that maps image detections into bowling-lane coordinates.

v1 mapping policy:

- use Depth API / MRUK raycast when available and stable
- otherwise intersect the camera ray with the estimated lane plane
- represent the ball trajectory in lane coordinates:
  - lateral position
  - downlane distance
  - height

### 6.4 Shot Segmentation

The runtime flow should be:

- `Idle`
- `Calibrating`
- `Armed`
- `Capturing`
- `Replay`
- `Review`

Shot start:

- first stable ball observation inside a near-foul-line release region after the session is armed

Shot end:

- tracking lost past timeout
- ball reaches a downlane distance limit
- max shot duration exceeded

### 6.5 Metrics

Compute:

- release speed from the earliest stable tracked segment
- continuous speed curve from filtered 3D points over time
- breakpoint as the largest lateral excursion before the path turns back inward

All metrics must carry confidence or quality flags.

## 7. Algorithms Explicitly Not Chosen for v1

### Otsu / classical thresholding

Not chosen as the primary detector.

Reason:

- bowling-lane lighting, reflections, shadows, and passthrough image noise make simple global thresholding too brittle
- the ball is often too small and reflective for a threshold-first approach to be reliable

Classical CV can still be used offline as a sanity baseline, but not as the main runtime method.

### SAM / promptable segmentation

Not chosen as the primary runtime model.

Reason:

- Quest local compute budget is tight
- the model class is known already
- detector-plus-tracker is a better fit than general promptable segmentation

SAM-style tools may still help with offline labeling or dataset bootstrapping.

### Spin estimation

Deferred out of v1.

Reason:

- the literature suggests spin estimation usually needs stronger cues such as marked balls, event cameras, or specialized capture
- a plain glossy bowling ball in Quest passthrough is not a good first target for robust spin estimation

## 8. Benchmark Algorithm

The main literature-informed benchmark path is a TrackNet-style temporal ball tracker.

Why benchmark it:

- sports literature consistently shows that tiny, fast, blurry balls benefit from temporal heatmap localization
- it may outperform a detector-only pipeline on downlane tracking

Why it is not the first runtime baseline:

- it is less aligned with the current working Quest repo and sample conversion path
- it adds more integration risk before we have a solid bowling-specific detector baseline

Decision:

- baseline runtime implementation: `YOLOv9t + Kalman`
- benchmark / later experiment: TrackNet-style multi-frame tracker

## 9. Calibration and Lane Frame

Calibration must stay minimal.

v1 assumptions:

- the wearer stands near the foul line and faces downlane during calibration
- the floor / lane plane can be estimated from Depth API or MRUK
- a standard lane geometry prior is acceptable for v1

Calibration actions:

1. user faces downlane
2. user holds still briefly
3. user confirms with `A` or pinch

Outputs:

- lane origin near foul line
- lane forward axis
- lane plane estimate
- handedness setting

## 10. Verification Strategy

We should not wait for a bowling alley to test every change.

### 10.1 Offline-first verification

Build an offline evaluation harness that reuses the detector + tracker logic on recorded video.

Input sources:

- public bowling videos, including YouTube
- Quest-recorded passthrough clips

Outputs:

- overlay video with detections and filtered path
- per-frame JSON or CSV
- summary report with success / failure reasons

### 10.2 Labeling strategy

Start with manual ball center-point labels.

Why:

- cheaper than full-box labeling
- enough for tracking evaluation and path quality checks
- enough to judge center error and continuity

### 10.3 Acceptance gate before alley testing

Do not treat the alley as the first real test.

A candidate build should pass offline gating if:

- it keeps track through a useful segment of the roll on the offline clip set
- the estimated path is visually plausible
- release speed is plausible when early tracking is good
- breakpoint is either plausible or clearly marked low-confidence
- failure cases produce interpretable logs

### 10.4 What offline video can and cannot validate

Useful for:

- detector sanity
- tracker tuning
- replay logic
- failure analysis

Not sufficient for:

- final Quest passthrough quality
- exact MR alignment
- headset-motion effects during real wear
- final on-lane UX

## 11. Runtime Architecture

Planned modules:

- `BallDetector`
  - camera frame -> bounding boxes / scores
- `BallMeasurementSelector`
  - select the most plausible one-ball measurement for this frame
- `LaneProjector`
  - 2D detection -> 3D lane-frame point
- `BallKalmanTracker`
  - filtered state, prediction, confidence
- `RollSegmenter`
  - shot start / end logic
- `RollMetricsComputer`
  - release speed, speed curve, breakpoint
- `ReplayPresenter`
  - post-shot visualization and HUD
- `RollLogger`
  - save raw and derived data for offline analysis

## 12. Logging Requirements

Every armed shot should produce a saved record, even if the run is bad.

Each shot record should include:

- timestamps
- camera resolution and model version
- detector thresholds
- raw detections
- selected measurement
- filtered trajectory
- confidence values
- release speed result
- breakpoint result
- termination reason

Bad runs are useful training data. They should not be dropped silently.

## 13. Dataset Strategy

### 13.1 Initial data sources

- public bowling clips for early prototyping
- Quest passthrough captures for domain adaptation
- real-lane clips from the team once collection is practical

### 13.2 Training target

Train a one-class bowling-ball detector first.

The first training objective is not perfect late-lane tracking. It is:

- reliable early-lane acquisition
- useful mid-lane continuity
- stable measurements for release speed and visible path

### 13.3 Hard examples to collect

- dark balls
- reflective balls
- motion blur
- occlusion at release
- low-light lanes
- different handedness
- different camera head poses

## 14. UX Spec

### 14.1 During setup

Show:

- headset readiness
- permissions state
- calibration prompt
- handedness setting

### 14.2 During capture

Show very little:

- capturing status
- optional subtle confidence indicator

Do not clutter the user's view during approach and release.

### 14.3 During replay

Show:

- lane-anchored visible path
- release speed
- speed curve
- breakpoint marker
- confidence / truncation marker if tracking was incomplete

## 15. Risks

Highest risks:

- late-lane ball size becomes too small for reliable detection
- head motion hurts image stability and projection quality
- depth / MRUK lane mapping may be noisy or incomplete
- bowling-ball appearance differs significantly from common object-detection training data

Planned mitigations:

- one-class detector training
- Kalman smoothing
- lane ROI gating
- offline harness and hard-example collection
- confidence-aware UI rather than pretending the estimate is exact

## 16. v1 Deliverables

- working Quest 3 on-device prototype
- bowling tracking scene with post-shot replay
- logged shot records
- offline evaluation harness
- first custom bowling-ball detector baseline
- written evaluation on what works, what fails, and why

## 17. Literature and Product Guidance Used

The spec is informed by:

- Meta Quest passthrough camera and Depth API documentation
- Meta's Unity Inference Engine sample path
- sports ball tracking literature such as TrackNet, TrackNetV4, TTNet, MonoTrack, and monocular 3D ball localization work
- commercial bowling tracking systems such as USBC B.O.L.T.S., Specto Bowling, and Ruby

These sources strongly suggest:

- small fast balls need temporal reasoning
- monocular geometry matters
- bowling is commercially valuable
- Quest-side runtime must stay lightweight

## 18. Final Baseline Decision

If we had to freeze the starting implementation now, it would be:

- Quest 3 local-only
- custom one-class `YOLOv9t`
- `GPUCompute`
- single-ball Kalman filter
- lane-plane / depth-based projection
- post-shot replay
- offline verification gate before alley testing

That is the baseline we should build first before trying more ambitious alternatives.
