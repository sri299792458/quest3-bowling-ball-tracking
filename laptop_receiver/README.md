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

Current implemented slice:

- [local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/local_clip_artifact.py) loads a standalone proof artifact from disk
- [validate_local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/validate_local_clip_artifact.py) validates one artifact end to end
- [standalone_yolo_seed.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_yolo_seed.py) runs the causal YOLO seed sweep directly over a standalone artifact
- [run_yolo_seed_on_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_yolo_seed_on_artifact.py) is the CLI entry point for that seed stage
- [import_legacy_bowling_run.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/import_legacy_bowling_run.py) packages one old `bowling_tests` run into the standalone artifact shape
- [standalone_warm_sam2_tracker.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_warm_sam2_tracker.py) is the standalone copy of the warm SAM2 video tracker path
- [standalone_sam2_tracking.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_sam2_tracking.py) runs warm SAM2 against `video.mp4 + yolo_seed.json`
- [run_sam2_on_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_sam2_on_artifact.py) is the CLI entry point for that SAM2 stage
- [live_stream_receiver.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_stream_receiver.py) runs the first real live Quest-to-laptop receiver for `H.264` media plus metadata
- the same [local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/local_clip_artifact.py) loader now also accepts a persisted live session directory directly

Validation checks currently include:

- `video.mp4` opens and decodes fully
- decoded frame count matches `frame_metadata.jsonl`
- frame timestamps increase monotonically
- `ptsUs` and `cameraTimestampUs` stay joinable
- per-frame pose fields are present

Usage:

```powershell
py -m pip install -r laptop_receiver/requirements.txt
py -m laptop_receiver.validate_local_clip_artifact C:\path\to\clip_<session>_<shot>
```

Optional JSON output:

```powershell
py -m laptop_receiver.validate_local_clip_artifact --json C:\path\to\clip_<session>_<shot>
```

YOLO seed usage:

```powershell
py -m laptop_receiver.run_yolo_seed_on_artifact C:\path\to\clip_<session>_<shot> --checkpoint C:\path\to\best.pt
```

What it writes:

- `analysis_yolo_seed/yolo_seed.json`
- `analysis_yolo_seed/yolo_seed_result.json`
- `analysis_yolo_seed/yolo_seed_preview.jpg` when a seed is found

Current note:

- the standalone proof clip we already pulled is not an actual bowling shot, so the new YOLO runner currently fails cleanly on it with `yolo_detection_failed`
- that is expected and still useful, because it proves the standalone artifact-to-YOLO path runs end to end
- the standalone SAM2 path currently materializes `video.mp4` into an analysis-local JPEG frame cache before calling SAM2
- that avoids the `decord` dependency in the direct-video SAM2 path and stays closer to how the old pipeline already operated

Legacy import usage:

```powershell
py -m laptop_receiver.import_legacy_bowling_run C:\path\to\legacy_run_dir
```

This writes an ignored local artifact under:

- `C:\Users\student\QuestBowlingStandalone\data\imported_artifacts\`

That imported artifact can then be validated and seeded with the same standalone commands as a native proof artifact.

SAM2 usage:

```powershell
py -m laptop_receiver.run_sam2_on_artifact C:\path\to\clip_<session>_<shot>
```

Current SAM2 environment note:

- this uses the already-working laptop SAM2 environment from the old project for now
- default `sam2_root` and checkpoint paths point at the existing vendored SAM2 repo under `C:\Users\student\Quest3BowlingBallTracking\third_party\sam2`
- so this stage is now standalone at the artifact boundary, but not yet fully standalone at the Python-environment boundary

Live stream receiver usage:

```powershell
py -m laptop_receiver.live_stream_receiver
```

By default it listens on:

- media TCP: `0.0.0.0:8766`
- metadata TCP: `0.0.0.0:8767`
- health HTTP: `0.0.0.0:8768`

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8768/health
```

What it persists per live stream:

- `stream.h264`
- `codec_config.h264`
- `media_samples.jsonl`
- `metadata_stream.jsonl`
- `session_start.json`
- `session_end.json`
- `stream_receipt.json`

Current live transport note:

- media and metadata intentionally use separate TCP channels
- this keeps the Java encoder output path and Unity/C# frame-metadata path cleanly separated
- `pts_us` is the join key between encoded samples and frame metadata
- this is the first real live streaming slice, not the final optimized transport
- the receiver now persists codec config ahead of media samples so desktop decoders can open `stream.h264` directly
