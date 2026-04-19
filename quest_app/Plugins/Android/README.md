# Android Plugin

This folder contains the standalone Quest-side Android plugin scaffold for local `H.264` proof capture.

Current scope:

- `MediaCodec` lifecycle
- `MediaMuxer` lifecycle
- surface-input encoder session start/stop
- status reporting back to Unity

What is **not** done yet:

- rendering Unity frames into the encoder input surface
- end-to-end proof clip validation on device

The first intended use is:

- Quest starts a local encode session
- Unity later renders into the exposed input surface
- encoded `video.mp4` lands beside the standalone metadata files
