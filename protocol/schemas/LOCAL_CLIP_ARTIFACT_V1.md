# Local Clip Artifact V1

Last updated: 2026-04-18

This is the first local proof-of-life artifact for the standalone Quest capture path.

It is intentionally simple.

The goal is to prove:

- Quest can locally encode `H.264`
- the clip is decodable
- frame metadata stays aligned with the encoded artifact

## Directory Shape

Each saved local proof clip should live in its own directory:

```text
clip_<session_id>_<shot_id>/
  artifact_manifest.json
  video.mp4
  session_metadata.json
  lane_lock_metadata.json
  frame_metadata.jsonl
  shot_metadata.json
```

## Files

### `video.mp4`

The locally encoded `H.264` proof clip.

For Milestone 1, using an `.mp4` container is preferred over a raw elementary stream because it is easier to inspect and validate quickly.

### `artifact_manifest.json`

Small top-level index pointing to the rest of the files.

### `session_metadata.json`

One session metadata object using the `Capture Metadata V1` contract.

### `lane_lock_metadata.json`

The lane-lock state active for the clip.

For Milestone 1 this may be:

- placeholder
- mocked
- or marked `unknown`

if lane lock is not yet implemented.

### `frame_metadata.jsonl`

One JSON record per encoded frame.

This is the key file for proving media-to-metadata alignment.

### `shot_metadata.json`

Shot boundaries and trigger summary for the exported clip.

## Validation Checks

The artifact is acceptable only if:

1. `video.mp4` decodes cleanly
2. `frame_metadata.jsonl` has a believable record count for the clip duration
3. timestamps increase monotonically
4. `pts_us` and `camera_timestamp_us` can be joined consistently
5. per-frame camera pose and head pose are present

If these checks fail, the local capture proof is not strong enough to move on to transport.
