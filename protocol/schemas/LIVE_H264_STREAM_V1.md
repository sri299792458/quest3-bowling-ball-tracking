# LIVE_H264_STREAM_V1

Last updated: 2026-04-19

This document defines the first live Quest-to-laptop streaming slice for the standalone bowling project.

The goal of this protocol is not to solve the entire final product at once.

The goal is:

- Quest continuously sends encoded `H.264` samples while the shot is happening
- Quest sends per-frame metadata on a separate lightweight side channel
- laptop persists both streams in one session directory
- laptop can later decode, align, and run `YOLO -> SAM2`

## Scope

This protocol is intentionally simple:

- `TCP` for live media samples
- `TCP` for live metadata JSON lines
- no packet loss logic yet
- no retransmission logic yet
- no lane-lock inference here

This is the first real live streaming path, not the final optimized transport.

## Ports

Default port layout:

- media stream: `8766`
- metadata stream: `8767`
- health HTTP: `8768`

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

## Laptop Persistence Shape

The laptop receiver should create one directory per live stream session and persist:

- `stream.h264`
- `codec_config.h264`
- `media_samples.jsonl`
- `metadata_stream.jsonl`
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
