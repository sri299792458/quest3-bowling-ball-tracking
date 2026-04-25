# LIVE_H264_STREAM_V1

Last updated: 2026-04-25

This document defines the first live Quest-to-laptop streaming slice for the standalone bowling project.

The goal of this protocol is not to solve the entire final product at once.

The goal is:

- Quest continuously sends encoded `H.264` samples for the whole bowling session
- Quest sends per-frame metadata on a separate lightweight side channel
- lane lock and shot boundaries are represented as metadata events inside that same live session
- laptop sends compact analysis results back to Quest on one result channel
- laptop persists the whole stream in one session directory
- laptop can later decode, align, lane-lock, and run `YOLO -> SAM2`

## Scope

This protocol is intentionally simple:

- `TCP` for live media samples
- `TCP` for live metadata JSON lines
- `TCP` for laptop-to-Quest result JSON lines
- no packet loss logic yet
- no retransmission logic yet
- no packet-loss recovery yet

This is the first real live streaming path, not the final optimized transport.

## Ports

Default port layout:

- media stream: `8766`
- metadata stream: `8767`
- health HTTP: `8768`
- Quest result channel: `8769`
- local result publish endpoint: `8770`

## Media Channel

The media channel is a binary packet stream over a dedicated TCP connection.

### Packet Header

Each packet begins with:

- magic: 4 bytes ASCII `QBLS`
- version: 1 byte, currently `1`
- packet type: 1 byte
- payload length: 4 bytes little-endian unsigned

Header size: `10` bytes

### Media Packet Types

- `1`: `session_start`
- `2`: `sample`
- `3`: `session_end`
- `4`: `codec_config`

### `session_start` Payload

UTF-8 JSON object with:

- `session_id`
- `shot_id`
- `width`
- `height`
- `fps`
- `bitrate_kbps`
- `codec`

### `sample` Payload

Fixed sample header followed by raw encoded bytes.

Sample header:

- `pts_us`: `uint64`
- `flags`: `uint32`
- `sample_size`: `uint32`

Then exactly `sample_size` bytes of encoded `H.264` sample payload.

Flag bits:

- bit `0`: keyframe

### `codec_config` Payload

Raw Annex B `H.264` codec configuration bytes.

Expected contents:

- SPS NAL units
- PPS NAL units

The laptop receiver writes these bytes ahead of media samples in `stream.h264` so desktop decoders can open the live bytestream directly.

### `session_end` Payload

UTF-8 JSON object with:

- `session_id`
- `shot_id`
- `reason`

## Metadata Channel

The metadata channel is newline-delimited UTF-8 JSON over a dedicated TCP connection.

Each line must contain:

- `kind`
- `session_id`
- `shot_id`

Expected message kinds for the first slice:

- `session_start`
- `frame_metadata`
- `lane_lock_request`
- `lane_lock_confirm`
- `shot_boundary`
- `session_end`

`frame_metadata` should include the fields already captured by the standalone Quest proof path, especially:

- `frameSeq`
- `cameraTimestampUs`
- `ptsUs`
- `isKeyframe`
- `width`
- `height`
- `timestampSource`
- `cameraPosition`
- `cameraRotation`
- `headPosition`
- `headRotation`
- `laneLockState`

`lane_lock_request` should include:

- `requestId`
- `frameSeqStart`
- `frameSeqEnd`
- `frameCount`
- `captureDurationSeconds`
- `selectionFrameSeq`
- `leftFoulLinePointNorm`
- `rightFoulLinePointNorm`
- `laneWidthMeters`
- `laneLengthMeters`
- `fx`
- `fy`
- `cx`
- `cy`
- `imageWidth`
- `imageHeight`
- `floorPlanePointWorld`
- `floorPlaneNormalWorld`
- `cameraSide`

The foul-line points are required. They are normalized image coordinates for the user-selected left and right lane edges at the foul line. The receiver must reject a lane-lock request that does not include them.

`shot_boundary` should include:

- `boundary_type`
- `frame_seq`
- `camera_timestamp_us`
- `pts_us`
- `reason`

`boundary_type` must be one of:

- `shot_start`
- `shot_end`

The laptop pairs one `shot_start` with the next valid `shot_end` from the same `session_id` and `shot_id`. Nested starts, unmatched ends, and end frames earlier than their start frames are invalid.

`lane_lock_confirm` should include:

- `requestId`
- `accepted`
- optional `reason`

## Result Channel

The result channel is newline-delimited UTF-8 JSON over TCP.

Quest opens one long-lived client connection to the laptop result channel and reads result envelopes. The laptop writes compact result messages on that connection.

Every result line must contain:

- `schemaVersion`, exactly `laptop_result_envelope`
- `kind`
- `session_id`
- `shot_id`
- `message_id`
- `created_unix_ms`

Supported result kinds:

- `lane_lock_result`
- `shot_result`
- `replay_path`
- `pipeline_error`

`lane_lock_result` envelopes must include:

- `lane_lock_result`, with `schemaVersion` exactly `lane_lock_result`

The envelope `session_id` must match `lane_lock_result.sessionId`.

`shot_result` envelopes must include:

- `shot_result`, with `schemaVersion` exactly `shot_result`

The envelope `session_id` must match `shot_result.sessionId`.

The envelope `shot_id` must match `shot_result.shotId`.

`shot_result` contains:

- `sessionId`
- `shotId`
- `windowId`
- `success`
- `failureReason`
- `laneLockRequestId`
- `sourceFrameRange`
- `trackingSummary`
- `trajectory`

`trajectory` is an ordered list of `lane_space_ball_point` entries. Each point contains the source frame identity, image point, projected world point, lane coordinates, on-lane flag, and projection confidence. A successful replayable shot result requires a successful lane lock; if no lane lock is available, the laptop may send a failed `shot_result` with an empty trajectory and `failureReason = lane_lock_result_missing`.

The local result publish endpoint is laptop-local producer input for analysis stages. Producers send the same strict result envelope to `127.0.0.1:8770`; the live receiver validates it, persists it, then forwards it to connected Quest result clients.

## Laptop Persistence Shape

The laptop receiver should create one directory per live stream session and persist:

- `stream.h264`
- `codec_config.h264`
- `media_samples.jsonl`
- `metadata_stream.jsonl`
- `lane_lock_requests.jsonl`
- `shot_boundaries.jsonl`
- `outbound_results.jsonl`
- `session_start.json`
- `session_end.json`
- `stream_receipt.json`

This live directory is not yet the final standalone artifact.

It is the first live intake boundary.

## Alignment Rule

`pts_us` is the join key between:

- encoded `H.264` media samples
- Quest frame metadata

The current expectation is:

- the Quest encoder output `pts_us`
- and Quest metadata `ptsUs`

should match exactly for emitted frames.

## Why Two Channels

Media samples are generated inside the Android encoder plugin.

Frame metadata is generated inside Unity/C# at render time.

Keeping them on separate TCP channels is the cleanest first live slice because it avoids forcing Java and C# to share one socket writer.

## Session Model

This stream is session-level.

The intended product shape is:

- one continuous stream for a bowling session, e.g. `30` minutes
- one lane-lock request near the start of the session, with optional relock later
- many shots and replays inside that same stream

So lane lock is **not** a separate media pipeline.
It is a tagged event window inside the continuous session stream.
