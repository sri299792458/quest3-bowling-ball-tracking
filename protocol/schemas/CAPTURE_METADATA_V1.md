# Capture Metadata V1

Last updated: 2026-04-18

This is the first standalone metadata contract we should keep stable while the media path is being proven.

The intent is simple:

- every encoded frame must have a trustworthy metadata partner
- shot boundaries must be reconstructable without guesswork
- the laptop must be able to join media, timing, pose, and lane-lock state deterministically

## Session Metadata

One session record per session:

```json
{
  "session_id": "string",
  "device_name": "string",
  "camera_side": "left|right",
  "requested_width": 1280,
  "requested_height": 960,
  "actual_width": 1280,
  "actual_height": 960,
  "requested_fps": 30.0,
  "actual_source_fps": 30.0,
  "video_codec": "h264",
  "target_bitrate_kbps": 3500,
  "camera_intrinsics": {
    "fx": 0.0,
    "fy": 0.0,
    "cx": 0.0,
    "cy": 0.0,
    "sensor_width": 0,
    "sensor_height": 0,
    "lens_offset_position": [0.0, 0.0, 0.0],
    "lens_offset_rotation_xyzw": [0.0, 0.0, 0.0, 1.0]
  }
}
```

## Lane Lock Metadata

One active lane-lock record per session:

```json
{
  "lane_lock_state": "locked|suspect|invalid",
  "locked_at_unix_ms": 0,
  "confidence": 0.0,
  "lane_origin_world_xyz": [0.0, 0.0, 0.0],
  "lane_rotation_world_xyzw": [0.0, 0.0, 0.0, 1.0],
  "lane_width_m": 1.0668,
  "lane_length_m": 18.288
}
```

## Per-Frame Metadata

One frame metadata record per encoded frame:

```json
{
  "frame_seq": 0,
  "camera_timestamp_us": 0,
  "pts_us": 0,
  "is_keyframe": false,
  "width": 1280,
  "height": 960,
  "camera_position_xyz": [0.0, 0.0, 0.0],
  "camera_rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
  "head_position_xyz": [0.0, 0.0, 0.0],
  "head_rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
  "lane_lock_state": "locked"
}
```

## Shot Metadata

One shot record per saved clip:

```json
{
  "shot_id": "string",
  "shot_start_time_us": 0,
  "shot_end_time_us": 0,
  "pre_roll_ms": 1500,
  "post_roll_ms": 500,
  "trigger_reason": "release_detected",
  "lane_lock_state_at_shot_start": "locked"
}
```

## Joining Rule

The laptop side should be able to answer:

- which encoded access unit corresponds to which `frame_seq`
- which `camera_timestamp_us` and `pts_us` belong to that unit
- what the camera pose and head pose were for that unit
- what lane-lock state was active at that unit

If we cannot answer those deterministically, the metadata contract is not good enough.
