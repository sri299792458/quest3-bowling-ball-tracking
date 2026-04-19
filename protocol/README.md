# Protocol

This module will contain the shared contracts between Quest and laptop.

Planned contents:

- session metadata schema
- frame metadata schema
- shot boundary schema
- transport message definitions
- versioning rules

The goal is to keep shared contracts explicit before transport code spreads across both sides.

Current first contract:

- [CAPTURE_METADATA_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/CAPTURE_METADATA_V1.md)
- [LOCAL_CLIP_ARTIFACT_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/LOCAL_CLIP_ARTIFACT_V1.md)
- [LIVE_H264_STREAM_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/LIVE_H264_STREAM_V1.md)

Current transport direction:

- Quest streams encoded `H.264` media live to the laptop while Unity sends frame metadata on a separate side channel

The live transport exists so laptop-side `YOLO -> SAM2` can move toward true streaming instead of waiting for a finished clip.
