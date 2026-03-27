# Holistic Pipeline Research

Last updated: 2026-03-27

## Executive Conclusion

The project should be treated as a **short-shot mixed reality analytics pipeline**, not as a generic detector demo and not as a fully automatic lane-understanding system from day one.

The most defensible v1 architecture is:

1. `Quest 3` captures short bowling shots and headset pose.
2. A local `PC` performs the heavier vision pipeline during capture or immediately after.
3. `Quest 3` renders a spatial replay back onto the real lane.

The right way to design the CV stack is:

- **lane model first**
- **release-window / motion gate second**
- **automatic seed selection third**
- **video tracking fourth**
- **analytics and MR replay last**

This is the key shift:

- `Grounding DINO` should not be treated as "the detector that decides everything."
- Instead, it should be treated as a **proposal source** inside a tighter bowling-specific pipeline.
- `SAM2` should not be treated as the initializer; it should be treated as the **short-clip propagator** after a good seed exists.

## What Official Quest Capabilities Actually Give Us

Meta's official Passthrough Camera API guidance supports the following on Quest 3 / 3S:

- image capture latency of about `20–40 ms`
- data rate `60 Hz`
- max resolution `1280x1280`
- access to the left and right face cameras
- camera metadata and multi-camera support through the Camera2 path

Meta also states that Unity Inference Engine on Quest currently does **not** use NPU or Quest-specific hardware acceleration, which is why heavy CV on-headset remains compute-constrained.

What this means:

- Quest is a good capture and MR display device.
- Quest is not where we should assume heavyweight promptable tracking will be happiest.
- A hybrid Quest + PC architecture remains the strongest baseline.

## Why Lane Modeling Is Not Optional

Lane geometry is needed twice:

1. **MR replay alignment**
2. **ball initialization and tracking**

Without a lane model, the system is forced to solve the wrong problem:

- "find a bowling ball anywhere in the frame"

With a lane model, the problem becomes:

- "find the earliest plausible bowling-ball tracklet inside the lane corridor"

That is a much better problem.

This does **not** require perfect automatic lane detection on day one.
It only requires a usable lane representation such as:

- left lane edge
- right lane edge
- lane forward direction
- an approximate lane-plane or lane trapezoid

That same representation can later be reused for MR replay anchoring.

## What Sports Tracking Literature Tells Us

Sports-ball tracking is not generic tracking in disguise.

TrackNet and TSFMO both emphasize that small, fast balls are difficult because they are:

- tiny
- plain-looking
- blurry
- prone to abrupt motion
- often weakly represented by generic trackers

This strongly supports a pipeline that uses:

- temporal evidence
- motion cues
- geometry constraints
- earliest plausible tracklet logic

It does **not** support trusting a single best detector box from a broad frame window.

## What Commercial Bowling Systems Tell Us

Commercial systems show that near-live or real-time bowling analytics are possible, but they do it with much easier sensing setups:

- **USBC B.O.L.T.S.**
  - four overhead cameras
  - 60 fps
  - 80–120 data points per shot
  - data shown before the ball is even returned
- **Specto Live / StrikeTrack**
  - real-time or immediate post-shot broadcast-style outputs
  - fixed-camera lane systems

Those systems validate the product value, but they also remind us that:

- a **wearable egocentric Quest** setup is harder than overhead lane cameras
- we need stronger priors and cleaner engineering than a naive single-model approach

## Bowling Geometry Priors We Should Use

USBC specifications give us strong physical priors:

- lane width: `41.5 in ± 0.5 in`
- bowling ball diameter: `8.500–8.595 in`

That means a bowling ball diameter is about `20%` of lane width at the same depth.

This is extremely useful.

Instead of global pixel-size thresholds, we should score candidates using:

- candidate width relative to **local lane width at that image row**

That gives us a size prior that respects perspective.

## Recommended Pipeline

### Stage 1. Quest Capture and Sync

Quest responsibilities:

- capture front-camera frames
- capture timestamps
- capture headset pose / motion
- handle session flow and later replay

Recommended output stream to PC:

- image frames
- timestamps
- headset pose
- session calibration data

We should not send rendered overlays back from the PC.
The PC should return structured replay data only.

### Stage 2. Lane Model

The first lane model should be minimal and reusable:

- a lane trapezoid or left/right lane boundaries in image space
- a lane forward direction
- a mapping into lane-relative coordinates

For v1 this can come from:

- manual or semi-manual calibration
- Quest pose + user confirmation

Automatic lane detection can come later.

### Stage 3. Shot Segmentation / Release Window

Do not run the full initializer across the whole clip uniformly.

Instead, detect a likely release window using:

- motion energy in the lower-middle lane corridor
- headset motion stabilization or compensation
- optional simple temporal rules about when the shot begins

This stage should be allowed to say:

- `no release yet`

### Stage 4. Automatic Initialization

This stage should be redefined as:

- **find the earliest plausible bowling-ball tracklet**

not:

- **find the highest-scoring detector box**

Recommended logic:

1. sample frames from the release window
2. run `Grounding DINO` with:
   - `bowling ball . sports ball .`
3. reject candidates that fail:
   - lane containment
   - ball-vs-lane-width plausibility
   - minimum semantic confidence
   - motion overlap
4. link surviving candidates across nearby sampled frames into short tracklets
5. choose the **earliest confirmed plausible tracklet**
6. seed `SAM2` from that box

This is the correct place to keep a **no-seed** state.

### Stage 5. Short-Clip Tracking

Use `SAM2` as:

- a short-clip propagator
- seeded by a confirmed box

Current practical choice on this laptop:

- `sam2.1_hiera_tiny`

Why:

- much faster than `large`
- not obviously worse on the successful local clip
- better suited to iterative development

`SAM2` should not be asked to invent the seed itself.

### Stage 6. Trajectory Cleanup and Analytics

Once a 2D track exists:

- smooth in image or lane coordinates
- detect loss / confidence collapse
- estimate release speed from early stable segment
- estimate visible path and breakpoint

Important rule:

- do not fabricate path after confidence collapses

### Stage 7. MR Replay

The PC returns:

- trajectory samples
- replay timestamps
- metrics
- confidence values

Quest then renders:

- lane-anchored spline or ghost-ball replay
- release and breakpoint markers
- HUD metrics

This is what makes it an MR project rather than a flat analytics app.

## Why The Current Auto-Init Failed On One Clip

The first `Grounding DINO -> SAM2` pipeline succeeded on `bowling_test_2.mp4` but failed on `bowling_test.mp4`.

That failure happened because we were still too close to:

- broad frame scan
- single-frame box ranking
- forced best-candidate selection

The improved confirmation logic already showed the better failure mode:

- it preferred `no seed found` over a weak false seed

That is correct behavior.

The next improvement should therefore target:

- release-window gating
- lane-constrained scoring
- motion overlap
- tracklet confirmation

not SAM2 propagation.

## Practical Heuristic Stack For The Next Implementation

The next initializer should score:

`tracklet_score = semantic * lane * size * motion * temporal`

Where:

- `semantic`: Grounding DINO score
- `lane`: candidate lies inside the lane corridor
- `size`: candidate width is plausible relative to local lane width
- `motion`: candidate overlaps moving content
- `temporal`: candidate repeats as a coherent short tracklet

Then choose:

- the **earliest tracklet above threshold**

not the global maximum box.

## What Not To Overcommit To Yet

- fully automatic lane detection before proving replay quality
- text-only `SAM2`
- relying on Meta scene semantics to directly detect a bowling lane
- on-Quest heavyweight tracking as the primary architecture
- live during-roll coaching overlays as the first milestone
- spin estimation as a v1 requirement

## Recommended Next Implementation Steps

1. Add a minimal lane corridor representation for each test clip.
2. Add frame-difference motion gating inside that corridor.
3. Change the initializer from box ranking to tracklet ranking.
4. Keep `Grounding DINO -> SAM2` as the backbone.
5. Re-test both bowling clips with the same new policy.

If that works, the pipeline becomes:

- Quest capture
- lane model
- release window
- automatic seed tracklet
- SAM2 propagation
- analytics
- MR replay

That is the cleanest holistic version of the project so far.

## Sources

- Meta Passthrough Camera API Overview:
  - https://developers.meta.com/horizon/documentation/unity/unity-pca-overview/
- Meta Depth API Overview:
  - https://developers.meta.com/horizon/documentation/unity/unity-depthapi-overview/
- Meta Scene Overview:
  - https://developers.meta.com/horizon/documentation/unity/unity-scene-overview/
- Meta Unity Inference Engine on Quest:
  - https://developers.meta.com/horizon/documentation/unity/unity-pca-sentis/
- Unity WebRTC video streaming docs:
  - https://docs.unity.cn/Packages/com.unity.webrtc%402.4/manual/videostreaming.html
- Grounding DINO official repo:
  - https://github.com/IDEA-Research/GroundingDINO
- Grounded-SAM-2 official repo:
  - https://github.com/IDEA-Research/Grounded-SAM-2
- TrackNet:
  - https://arxiv.org/abs/1907.03698
- TSFMO benchmark:
  - https://openaccess.thecvf.com/content/ACCV2022/papers/Zhang_Tracking_Small_and_Fast_Moving_Objects_A_Benchmark_ACCV_2022_paper.pdf
- USBC equipment specifications:
  - https://bowl.com/getmedia/08ef148d-c0e4-4e00-9e0d-855ba4729ad5/equipment-specs-manual.pdf
- USBC B.O.L.T.S.:
  - https://bowl.com/introducing-b-o-l-t-s
- Specto Live:
  - https://www.spectobowling.com/spectolive
- Specto StrikeTrack on FOX:
  - https://www.spectobowling.com/news/2019/1/15/go-bowling-pba-tour-on-fox-introduces-specto-striketrack-technology
