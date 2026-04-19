# Laptop Receiver

This module will contain the standalone laptop-side pipeline.

Responsibilities:

- ingest Quest media and metadata
- reconstruct shot clips
- decode frames
- run `YOLO -> SAM2`
- compute replay and analytics payloads

First target:

- accept a future standalone shot clip plus metadata bundle
- decode and validate it against local `bowling_tests`
