# Laptop Receiver

This module will contain the standalone laptop-side pipeline.

Responsibilities:

- ingest Quest media and metadata
- reconstruct shot clips
- decode frames
- run YOLO seeding plus SAM2 tracking
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
- [standalone_warm_sam2_tracker.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_warm_sam2_tracker.py) is the offline-only batch/video SAM2 tracker path
- [standalone_sam2_tracking.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_sam2_tracking.py) runs offline batch SAM2 against `video.mp4 + yolo_seed.json`
- [run_sam2_on_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_sam2_on_artifact.py) is the CLI entry point for that offline SAM2 stage
- [live_stream_receiver.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_stream_receiver.py) runs the first real live Quest-to-laptop receiver for `H.264` media plus metadata
- [laptop_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/laptop_result_types.py) defines strict laptop-to-Quest result envelopes
- [shot_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/shot_result_types.py) defines strict shot result and lane-space trajectory payloads
- the same [local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/local_clip_artifact.py) loader now also accepts a persisted live session directory directly
- Quest now sends the confirmed `lane_lock_result` directly in `lane_lock_confirm`; the live laptop loop does not solve lane lock requests
- [live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_session_pipeline.py) polls live session directories and runs the post-lane shot analysis stages
- [live_shot_boundaries.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundaries.py) validates strict `shot_start` / `shot_end` windows from `shot_boundaries.jsonl`
- [live_shot_boundary_detector.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundary_detector.py) writes automatic `shot_start` / `shot_end` events after lane lock; YOLO finds the seed and live camera SAM2 owns tracking/end
- [live_camera_sam2_tracker.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_camera_sam2_tracker.py) keeps the camera SAM2 predictor warm and writes the per-shot track CSV
- [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py) builds the strict `shot_result` from the camera SAM2 track artifact
- [run_live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_live_session_pipeline.py) is the live pipeline CLI entry point

Validation checks currently include:

- `video.mp4` opens and decodes fully
- decoded frame count matches `frame_metadata.jsonl`
- frame timestamps increase monotonically
- `ptsUs` and `cameraTimestampUs` stay joinable
- per-frame pose fields are present

Usage:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_receiver\setup_laptop_env.ps1
.\.venv\Scripts\python.exe -m laptop_receiver.validate_local_clip_artifact C:\path\to\clip_<session>_<shot>
```

Use the repo-local `.venv` for laptop-side validation and analysis. Normal standalone runs should not depend on the older experiment repo.

Optional JSON output:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.validate_local_clip_artifact --json C:\path\to\clip_<session>_<shot>
```

YOLO seed usage:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact C:\path\to\clip_<session>_<shot>
```

The default detector is the repo-local YOLO26s checkpoint:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/weights/best.pt
```

Pass `--checkpoint C:\path\to\best.pt` only when intentionally testing another detector.

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
.\.venv\Scripts\python.exe -m laptop_receiver.import_legacy_bowling_run C:\path\to\legacy_run_dir
```

This writes an ignored local artifact under:

- `C:\Users\student\QuestBowlingStandalone\data\imported_artifacts\`

That imported artifact can then be validated and seeded with the same standalone commands as a native proof artifact.

SAM2 usage:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_sam2_on_artifact C:\path\to\clip_<session>_<shot>
```

Current SAM2 environment note:

- default `sam2_root` points at `third_party/sam2` in this repo
- default checkpoint path is `third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt`
- the checkpoint is downloaded by `laptop_receiver/setup_laptop_env.ps1` and ignored by Git
- override with `--sam2-root`, `--checkpoint`, `SAM2_REPO_ROOT`, or `SAM2_CHECKPOINT_PATH` only when intentionally testing another SAM2 install

Live stream receiver usage:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.live_stream_receiver
```

Normal live alley startup should use the repo-level launcher instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_live_pipeline.ps1
```

That command stops stale live receiver/pipeline Python processes, starts the receiver, waits for health on `127.0.0.1:8768`, then runs the live pipeline in the same terminal. Use `-NoSam2` to keep YOLO shot processing enabled without SAM2.

By default it listens on:

- Quest laptop discovery UDP: `0.0.0.0:8765`
- media TCP: `0.0.0.0:8766`
- metadata TCP: `0.0.0.0:8767`
- health HTTP: `0.0.0.0:8768`
- Quest result TCP: `0.0.0.0:8769`
- local result publish TCP: `127.0.0.1:8770`

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8768/health
```

What it persists per live stream:

- `stream.h264`
- `codec_config.h264`
- `media_samples.jsonl`
- `metadata_stream.jsonl`
- `lane_lock_confirms.jsonl`
- `shot_boundaries.jsonl`
- `outbound_results.jsonl`
- `session_start.json`
- `session_end.json`
- `stream_receipt.json`
- `session_state.json`

Shot-boundary note:

- `shot_boundaries.jsonl` is strict: `boundary_type` must be `shot_start` or `shot_end`
- when `--yolo-checkpoint` is configured, the live pipeline creates shot boundaries automatically after a user-confirmed lane lock
- a rejected/relocked lane confirmation disables shot detection again until a new lane is confirmed
- automatic `shot_start` requires a confident YOLO ball projected into the lane-lock release corridor plus short downlane confirmation
- automatic `shot_end` uses terminal downlane region, sustained YOLO/projection loss with grace, or max shot duration
- each automatic shot boundary records the confirmed `laneLockRequestId`; shot projection uses that exact lane result
- the live pipeline reports completed shot windows, open shot windows, and malformed boundary errors in its polling summary

Current live transport note:

- media and metadata intentionally use separate TCP channels
- this keeps the Java encoder output path and Unity/C# frame-metadata path cleanly separated
- `pts_us` is the join key between encoded samples and frame metadata
- this is the first real live streaming slice, not the final optimized transport
- the receiver now persists codec config ahead of media samples so desktop decoders can open `stream.h264` directly
- lane lock is solved on Quest and sent as a `lane_lock_confirm` metadata event containing the full `lane_lock_result`
- laptop-to-Quest messages now use strict `laptop_result_envelope` JSON lines on the result channel

Live session pipeline usage:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline
```

Process one landed session without publishing results:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline --session-dir C:\path\to\live_<session>_<stream> --once --no-publish
```

Enable automatic YOLO shot boundaries and windowed shot tracking:

```powershell
$yolo26s = "models\bowling_ball_yolo26s_img1280_lightaug_v3\weights\best.pt"
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline --yolo-checkpoint $yolo26s
```

Run live camera SAM2 after each successful YOLO seed:

```powershell
$yolo26s = "models\bowling_ball_yolo26s_img1280_lightaug_v3\weights\best.pt"
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline --yolo-checkpoint $yolo26s --run-sam2
```

Current honest note:

- the old desktop click artifacts were invalid for this contract because the selected pixels were not physical foul-line endpoints
- the live product path receives world-space lane geometry from the Quest lane coordinator in `lane_lock_confirm`
- there is no automatic lane identity selection or view-center guess in lane calibration
- shot boundaries and tracking are explicit: the live pipeline only runs the YOLO-based shot path when a YOLO checkpoint is configured, and replayable shot results require live camera SAM2 via `--run-sam2`
- a replayable `shot_result` requires a user-confirmed lane lock; without one, or after a relock invalidates one, the laptop emits a failed shot result instead of inventing lane-space trajectory data
