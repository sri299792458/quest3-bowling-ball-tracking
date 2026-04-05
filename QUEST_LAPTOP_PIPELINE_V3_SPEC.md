# Quest-Laptop Pipeline V3 Spec

Last updated: 2026-04-05

This document defines the proposed `V3` transport redesign for Quest passthrough capture to the laptop pipeline.

The goal of `V3` is to stop optimizing around the current JPEG bring-up path and instead design around the **actual source ceiling** we measured from the camera API.

## 1. Executive Summary

`V3` should target:

- source camera cadence of about `60 FPS`
- highest practical spatial quality
- hardware video encoding on Quest
- compact side metadata for timestamps and poses
- laptop-side decode into frames for `YOLO -> SAM2`

The key change is:

- replace per-frame CPU JPEG encode with hardware video encode (`H.264` first, `H.265` optional when available)

The current TCP/UDP split remains conceptually correct:

- `TCP` for reliable control and shot/session metadata
- `UDP` for the high-volume media path

## 2. Why V3 Exists

The current v1 path is:

- passthrough frame on Quest
- GPU readback
- `EncodeToJPG(...)`
- UDP fragmentation
- laptop reassembly

That path was useful because it was easy to debug.
But it is not the right final architecture for preserving the maximum camera rate.

The newest probe results show:

- the Quest source camera can actually produce about `60 FPS`
- our current JPEG sender was the bottleneck, not the camera

So `V3` should be designed around preserving a `60 FPS` source, not around defending the current `~17-18 FPS` path.

## 3. Hard Facts We Are Designing Around

### 3.1 Official Meta Source-Camera Characteristics

Meta’s official Passthrough Camera API Overview lists:

- `Data rate: 60Hz`
- `Max resolution: 1280x1280`
- `Internal data format: YUV420`

Source:

- https://developers.meta.com/horizon/documentation/unity/unity-pca-overview/

The local Meta Unity package in this repo also exposes `MaxFramerate` with a default backing value of `60`, and explicitly says actual framerate may vary:

- [PassthroughCameraAccess.cs](C:/Users/student/Quest3BowlingBallTracking/Library/PackageCache/com.meta.xr.mrutilitykit@6d21b459f6d3/Core/Scripts/PassthroughCameraAccess.cs)

### 3.2 Measured Camera Probe Results

We added a probe-only mode to the Quest sender and measured:

- requested `60` -> actual `~60 FPS`
- requested `120` -> still actual `~60 FPS`

Measured runs:

- [60 FPS probe run](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/6d5e6f59b5794cfab87d2d4703b0e479_shot_1775394719626_20260405_081204/quest_tracker_status.jsonl)
- [120 FPS probe run](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/5c053f3ffbb64c5aa689c9331942c2a8_shot_1775395083198_20260405_081807/quest_tracker_status.jsonl)

Conclusion:

- the practical source ceiling for this API path is about `60 FPS`

### 3.3 Current Stream Profile

The current active JPEG transport profile has been:

- output size: `960 x 720`
- target send FPS: `30`
- JPEG quality: `65`

Representative run:

- [session_config.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bde10c4a8df14b08ae1e7be025680f71_shot_1774832987893_20260329_200946/session_config.json)

### 3.4 Measured Current JPEG Payload Size

In that representative run, the saved JPGs averaged about:

- `42,335.6 bytes` per frame

From:

- [raw frames](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bde10c4a8df14b08ae1e7be025680f71_shot_1774832987893_20260329_200946/raw/frames)
- [manifest.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bde10c4a8df14b08ae1e7be025680f71_shot_1774832987893_20260329_200946/raw/manifest.json)

## 4. Quantitative Budgets

All numbers below use `960 x 720` unless stated otherwise.

### 4.1 Raw Frame Size

At `960 x 720`:

- raw RGB frame = `960 * 720 * 3 = 2,073,600 bytes` = `1.978 MiB`
- raw RGBA frame = `2,764,800 bytes`
- raw YUV420 frame = `1,036,800 bytes` = `0.989 MiB`

At `60 FPS`, this means:

- raw RGB source rate = `118.65 MiB/s`
- raw YUV420 source rate = `59.33 MiB/s`

Interpretation:

- buffering raw RGB aggressively on Quest is expensive
- buffering encoded video is far more attractive

### 4.2 Current JPEG Wire Budget

Current UDP chunk payload size is:

- `1400 - 26 = 1374 bytes`

with:

- `1400` = configured datagram max
- `26` = current app-level UDP header size

For the average current JPEG size of `42,335.6 bytes`:

- chunks per frame = `31`
- app+UDP+IP overhead per frame = about `1,674 bytes`

Approximate bitrate:

- `30 FPS` payload only = `9.69 Mbps`
- `30 FPS` on-wire with headers = `10.07 Mbps`
- `60 FPS` payload only = `19.38 Mbps`
- `60 FPS` on-wire with headers = `20.15 Mbps`

Interpretation:

- the local network is not the primary reason we were capped around `17-18 FPS`
- the Quest-side JPEG path was the primary bottleneck

### 4.3 5-Second Shot Buffer Budget At 60 FPS

A `5 second` shot at `60 FPS` means:

- `300 frames`

Equivalent buffer sizes:

- current JPEG average: `12.11 MiB`
- raw RGB: `593.26 MiB`
- raw YUV420: `296.63 MiB`
- `H.264 @ 8 Mbps`: `4.77 MiB`
- `H.264 @ 12 Mbps`: `7.15 MiB`
- `H.265 @ 6 Mbps`: `3.58 MiB`
- `H.265 @ 8 Mbps`: `4.77 MiB`

Interpretation:

- buffering raw frames is costly
- buffering compressed video is entirely manageable

This is one of the strongest quantitative arguments for `V3`.

## 5. V3 Design Principles

1. Treat `60 FPS` as the source budget.
2. Keep the capture path as close to the camera rate as possible.
3. Compress early using hardware video encode, not CPU JPEG.
4. Preserve timestamps and poses with every frame or access unit.
5. Keep control and session correctness on TCP.
6. Keep the media path on UDP.
7. Prefer a bounded queue with explicit drop policy over hidden stalls.

## 6. Proposed V3 Architecture

## 6.1 Control Plane

Keep:

- `TCP`

Keep the same kind of reliable messages:

- `hello`
- `session_config`
- `lane_calibration`
- `shot_started`
- `shot_ended`
- `tracker_status`
- `shot_result`

Reason:

- these messages are correctness-critical
- they are tiny compared to video
- TCP is the right choice for them

## 6.2 Video Plane

Replace:

- per-frame JPEG payloads

With:

- hardware-encoded video access units or NAL units

Transport:

- `UDP`

Default codec target:

- `H.264/AVC`

Optional fast path:

- `H.265/HEVC` if the Quest runtime reports encoder support

Why `H.264` first:

- Android documentation clearly supports AVC encoding broadly
- it is the safest first implementation target

Why `HEVC` is optional:

- Android supports HEVC in the media stack, but encoder availability and behavior should still be runtime-probed on device

Sources:

- https://developer.android.com/reference/android/media/MediaCodec
- https://developer.android.com/media/platform/supported-formats

## 6.3 Metadata Side Channel

Video compression alone is not enough for the bowling problem because we also need:

- `frame_seq`
- `timestamp_us`
- `camera_pose`
- `head_pose`
- `shot_id`

V3 should send compact per-frame metadata as a side stream.

Recommended design:

- keep session-level metadata on `TCP`
- send per-frame metadata in a compact ordered metadata stream over `UDP`

Each metadata packet should include:

- `session_id`
- `shot_id`
- `frame_seq`
- `timestamp_us`
- `camera_position`
- `camera_rotation`
- `head_position`
- `head_rotation`
- `is_keyframe_hint`
- `video_pts_us` or equivalent codec timestamp

This lets the laptop:

- decode video
- map decoded frames back to the correct motion and timing metadata

## 6.4 Shot Buffer

V3 should buffer **encoded video output**, not raw frames.

That means:

- Quest records compressed video chunks during the shot
- after `shot_ended`, Quest continues flushing the encoded backlog to the laptop

This is the key product insight:

- for our replay workflow, preserving the full shot is more important than forcing every frame to arrive in strict real time

## 7. Why Hardware Video Encode Is The Right Move

The current JPEG path does:

- GPU readback
- CPU `EncodeToJPG(...)`

That is expensive and frame-oriented.

A hardware encoder is better because:

- it is built exactly for video compression
- it avoids per-frame CPU JPEG work
- it produces a compact continuous bitstream
- it makes high-FPS buffering practical

In other words:

- `V1` was image transport
- `V3` should be video transport

## 8. Codec Decision

This is now the project decision for `V3`:

- **Required baseline codec:** `H.264/AVC`
- **Optional higher-efficiency codec:** `H.265/HEVC`

This is not just a preference. It is the implementation policy.

### 8.1 Why AVC Is The Required Baseline

Use `H.264/AVC` first because it is the safest codec to build the first real `V3` around:

- broad Android ecosystem support
- well-understood encode/decode path
- easiest codec to assume on both Quest and laptop
- enough compression improvement to remove CPU JPEG from the hot path

In Android's official supported media formats table, `H.264 AVC Baseline Profile` encoding support is listed broadly, while the table is less definitive about HEVC encoding guarantees across device classes.

Source:

- https://developer.android.com/media/platform/supported-formats

### 8.2 Why HEVC Is Optional, Not The Baseline

Use `H.265/HEVC` only when runtime capability checks say it is available and healthy on the actual Quest device.

Reasons:

- better compression efficiency than AVC
- smaller shot backlog for the same quality
- but more risk than AVC as a first implementation dependency

So the rule is:

- do not block `V3` on HEVC
- do not design the first milestone assuming HEVC is always available

### 8.3 Runtime Policy

At runtime, Quest should probe encoder support in this order:

1. `H.264/AVC`
2. `H.265/HEVC`

And then select:

- `HEVC` only if the runtime probe passes
- otherwise `AVC`

That means:

- AVC is the guaranteed path we build and test first
- HEVC is an optimization path, not the foundation

## 9. Recommended Resolution / Bitrate Ladder

Because the true source ceiling is `60 FPS`, the first V3 test matrix should be:

### Tier A: Safer First V3

- `960 x 720 @ 60 FPS, H.264, 8 Mbps`
- `960 x 720 @ 60 FPS, H.264, 10 Mbps`
- `960 x 720 @ 60 FPS, H.264, 12 Mbps`

### Tier B: Higher Quality

- `1280 x 960 @ 60 FPS, H.264, 12 Mbps`
- `1280 x 960 @ 60 FPS, H.264, 16 Mbps`

### Tier C: Optional HEVC

- `960 x 720 @ 60 FPS, H.265, 6 Mbps`
- `960 x 720 @ 60 FPS, H.265, 8 Mbps`
- `1280 x 960 @ 60 FPS, H.265, 8 Mbps`
- `1280 x 960 @ 60 FPS, H.265, 10 Mbps`

These are not proven-good values yet.
They are the first principled sweep to run.

## 10. Recommended Packetization

`V3` should not send one packet per frame in the old JPEG sense.

Instead:

1. Quest encoder emits encoded output chunks.
2. The transport groups them into access units.
3. Each access unit is packetized into UDP chunks if needed.

Recommended app-level UDP media header:

- `magic`
- `version`
- `stream_type`
- `session_id_hash` or compact session reference
- `shot_id_hash` or compact shot reference
- `access_unit_seq`
- `chunk_index`
- `chunk_count`
- `payload_length`
- `flags`

Important flags:

- keyframe
- codec config packet
- end-of-shot flush marker

The exact binary layout can be decided later.
The important change is:

- packetize **encoded video units**
- not JPEG image frames

## 11. Recommended Port Layout

For `V3`, I recommend separating ports:

- `5799/TCP` control
- `5800/UDP` media
- optional `5801/UDP` per-frame metadata if we decide not to multiplex it with media

Why separate from the current single-port style:

- simpler Wireshark traces
- simpler server logging
- easier future evolution
- easier to reason about control vs media failures

## 12. Laptop-Side V3 Responsibilities

The laptop should:

1. accept TCP control
2. receive UDP media chunks
3. reassemble encoded access units
4. decode video back into frames
5. join decoded frames with per-frame metadata
6. write the run to disk
7. feed decoded frames into `YOLO -> SAM2`
8. send compact results back to Quest over TCP

This keeps the analysis side conceptually the same.

The main transport change is only:

- encoded video in
- not per-frame JPEG in

## 13. What Stays The Same From The Current Pipeline

V3 does **not** mean rewriting the whole product.

Keep:

- `TCP` control concepts
- run folder structure
- `session_config.json`
- `lane_calibration.json`
- `shot_events.jsonl`
- Quest-side status reporting
- laptop-side `YOLO -> SAM2`

Replace:

- Quest per-frame JPEG encode
- current frame UDP payload format
- current laptop JPEG reassembly path

## 14. What We Should Measure In V3

For every V3 test run, capture:

- requested source FPS
- measured source FPS
- encoder output bitrate
- access units per second
- packet loss rate
- decode success rate
- end-to-end shot flush delay
- `YOLO` seed success
- `SAM2` tracking success
- replay-ready latency after `shot_ended`

These become the real success criteria.

## 15. Proposed Milestones

### Milestone 1: Capability Probe

Implement Quest-side runtime probe for:

- AVC encoder availability
- HEVC encoder availability
- supported resolution / framerate combinations if queryable

Deliverable:

- a capability report written to log and saved with the run

### Milestone 2: AVC Recording Transport

Implement:

- `H.264` hardware encode on Quest
- UDP media transport
- laptop-side decode

Success criterion:

- preserve near-60-FPS capture at `960 x 720`
- produce decodable runs on the laptop

### Milestone 3: Metadata Join

Implement:

- per-frame timestamp + pose side stream
- deterministic alignment between decoded frames and metadata

Success criterion:

- saved laptop run preserves frame timing and pose cleanly

### Milestone 4: YOLO -> SAM2 On V3

Feed decoded V3 frames into the existing tracking stack.

Success criterion:

- equivalent or better tracking than the current JPEG path

### Milestone 5: HEVC Optional Path

If Quest encoder support is solid, add:

- `H.265` mode

Success criterion:

- lower bitrate / smaller backlog at similar tracking quality

## 16. Main Risks

1. Encoder API complexity on Quest/Unity.
2. Mapping encoded video timestamps cleanly to metadata.
3. Laptop-side decode latency and buffering behavior.
4. HEVC support variability.
5. Maintaining deterministic shot boundaries when video is buffered and flushed after the shot.

These are real risks, but they are better risks than continuing to spend time on CPU JPEG transport.

## 17. Final Recommendation

`V3` should be the new target architecture.

The key reason is quantitative:

- source camera ceiling is about `60 FPS`
- buffering raw frames for a `5s` shot would cost roughly `593 MiB` in RGB or `297 MiB` in YUV420
- buffering compressed video for the same shot can be under `5-8 MiB`

That is exactly why hardware video encoding is the right redesign.

So the first concrete implementation target should be:

- `960 x 720 @ 60 FPS`
- `H.264`
- encoded-video shot buffer on Quest
- UDP media transport
- laptop decode to frames
- preserve timestamps and poses alongside the media

## 18. Quest Data Inventory And Capture Policy

We should collect as much low-overhead metadata as the Quest runtime exposes, because metadata is cheap compared to video.

The important distinction is:

- video data is the expensive part
- metadata is usually tiny

So `V3` should be conservative about media and generous about metadata.

### 18.1 Data Available From The Current Passthrough Camera API Path

From the Meta `PassthroughCameraAccess` package we are already using, the following are available:

- `Timestamp`
- `CurrentResolution`
- `RequestedResolution`
- `CameraPosition` (`Left` / `Right`)
- `Intrinsics`
  - `FocalLength`
  - `PrincipalPoint`
  - `SensorResolution`
  - `LensOffset`
- `GetCameraPose()`
- `IsUpdatedThisFrame`
- supported resolutions via `GetSupportedResolutions(...)`

Repo-local source:

- [PassthroughCameraAccess.cs](C:/Users/student/Quest3BowlingBallTracking/Library/PackageCache/com.meta.xr.mrutilitykit@6d21b459f6d3/Core/Scripts/PassthroughCameraAccess.cs)

The current package comments are especially important:

- `Timestamp` is associated with the latest camera image
- `GetCameraPose()` returns the camera’s world-space pose at that timestamp

That means the API already gives us the core camera-time alignment we want.

### 18.2 Data We Already Capture In This Repo

The current transport already saves:

Session-level:

- `session_id`
- `camera_eye`
- `width`
- `height`
- `fx`
- `fy`
- `cx`
- `cy`
- `sensor_width`
- `sensor_height`
- `lens_position`
- `lens_rotation`
- `target_send_fps`
- `transport`
- `video_codec`
- `target_bitrate_kbps`
- `lane_calibration`

Per-frame:

- `source_frame_id`
- `timestamp_us`
- `camera_position`
- `camera_rotation`
- `head_position`
- `head_rotation`

Stored in:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)
- [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)
- [sam2_bowling_bridge.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/sam2_bowling_bridge.py)

### 18.3 Important Current Gap

Right now the sender uses `DateTime.UtcNow` when building the frame payload, not the camera API’s own `Timestamp`.

That means:

- we are already saving a timestamp
- but it is not yet the strongest available camera-native timestamp source

For `V3`, this should be corrected:

- use the actual camera image timestamp from `PassthroughCameraAccess.Timestamp`
- not a generic wall-clock send-time

This is a low-overhead but high-value improvement.

### 18.4 Data We Should Always Capture In V3

This should be the default `V3` metadata schema.

#### Session-level

Save once per session or when it changes:

- `session_id`
- headset model / app version / OS version
- camera side (`left` / `right`)
- requested camera resolution
- actual camera resolution
- requested max framerate
- actual probed source framerate
- intrinsics:
  - focal length
  - principal point
  - sensor resolution
  - lens offset pose
- selected codec
- selected bitrate
- lane calibration

#### Per-frame

Save for every frame or access unit:

- `frame_seq`
- `shot_id`
- camera image timestamp
- codec PTS / decode timestamp mapping
- camera world pose
- head world pose
- frame dimensions
- keyframe flag
- dropped-frame counters or discontinuity flag if relevant

This is the minimum high-value metadata set.

### 18.5 Data We Should Strongly Consider Capturing Too

These are also useful and generally still cheap compared to video:

- left controller pose
- right controller pose
- controller tracking validity flags
- active input mode:
  - controllers
  - hands
  - mixed
- hand tracking validity flags
- per-shot calibration resend count / calibration version

These are especially useful if later analytics care about:

- release timing
- user stance
- which controller/hand was active

### 18.6 Data We Can Consider Later

These are potentially useful but should be treated as optional extensions:

- hand joint skeleton data
- raw or semi-raw IMU samples
- eye tracking data
- body tracking data
- exposure / gain / white balance if exposed in a future API

Why later:

- some of these may not be available in this exact API path
- some require extra permissions or device support
- some need careful synchronization logic

So they are good to investigate, but not required for the first `V3` milestone.

### 18.7 Why “Collect Everything” Mostly Makes Sense

For the metadata above, the overhead is tiny compared to media.

Rough order of magnitude:

- essential per-frame pose/timestamp metadata is on the order of tens to low hundreds of bytes per frame
- at `60 FPS`, that is only a few KB/s
- even controller poses are still tiny relative to multi-megabit video

By contrast:

- `960 x 720 @ 60 FPS` video is on the order of megabits per second

So the design rule should be:

- aggressively collect metadata
- aggressively optimize media

### 18.8 Practical Capture Policy

For `V3`, the repo should adopt this simple policy:

1. If the data is already exposed by the active Quest API path and is small, save it.
2. If it is session-static, save it once.
3. If it is frame-aligned and cheap, save it per frame.
4. If it is high-rate and harder to align, add it only after the first `V3` transport milestone is stable.

## 19. References

- Meta Passthrough Camera API Overview:
  - https://developers.meta.com/horizon/documentation/unity/unity-pca-overview/
- Android `MediaCodec` reference:
  - https://developer.android.com/reference/android/media/MediaCodec
- Android supported media formats:
  - https://developer.android.com/media/platform/supported-formats

Repo-local references:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)
- [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)
- [QUEST_LAPTOP_PIPELINE_SPEC.md](C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_PIPELINE_SPEC.md)
- [QUEST_LAPTOP_TRANSPORT_README.md](C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_TRANSPORT_README.md)
