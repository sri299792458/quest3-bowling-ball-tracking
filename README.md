# Quest Bowling Standalone

This repository is the clean starting point for the standalone bowling replay product.

The active product definition lives in [docs/STANDALONE_PRODUCT_GOAL.md](C:/Users/student/QuestBowlingStandalone/docs/STANDALONE_PRODUCT_GOAL.md).

The detailed lane-lock design lives in [docs/LANE_LOCK_MATH_AND_CONTRACT.md](C:/Users/student/QuestBowlingStandalone/docs/LANE_LOCK_MATH_AND_CONTRACT.md).

## Working Rules

- keep the scope centered on the standalone product, not the old experiment stack
- maintain [running_notes.md](C:/Users/student/QuestBowlingStandalone/running_notes.md) as the current build log and decision log
- use the local validation dataset at `C:\Users\student\QuestBowlingStandalone\data\bowling_tests`
- only commit deliberate checkpoints

## Current Baseline

- single camera
- `1280 x 960 @ 30 FPS, H.264`
- lightweight session lane lock
- one continuous live session stream
- YOLO-seeded live camera SAM2 tracking
- true lane-anchored MR replay

## Repository Layout

- `docs/`: product definition and implementation notes
- `unity_proof/`: active Unity project and Quest-side standalone implementation
- `laptop_receiver/`: laptop-side media, tracking, and replay module
- `protocol/`: shared schemas and message contracts
- `third_party/sam2/`: repo-local SAM2 source; checkpoint is downloaded/ignored
- `data/`: local validation data and other non-source assets
- `running_notes.md`: current execution log so we stay organized

## Immediate Build Slice

We are starting with one disciplined first slice:

- prove Quest-side local `H.264` encode at `1280 x 960 @ 30 FPS`
- preserve timestamp and pose metadata cleanly
- keep the repo structure ready for the later laptop and protocol pieces

## Current Milestone

Milestone `1` is now proven in the clean Unity proof app:

- local Quest-side `H.264` proof capture works
- a real `video.mp4` is written on-device
- per-frame metadata is written to `frame_metadata.jsonl`
- encoder surface binding and native blit path are working
- `ptsUs` in metadata is now camera-derived and coherent with the shot span
- laptop-side standalone artifact validation now works against a pulled proof clip

The clean next slice after Quest proof is now in place:

- load `artifact_manifest.json`, sidecars, and `video.mp4` as one standalone artifact
- validate decoded video frames against `frame_metadata.jsonl`
- prove timestamp and metadata alignment before porting over more of the old laptop stack
- run standalone causal YOLO seeding directly on a `LocalClipArtifact`
- import one legacy `bowling_tests` run into the standalone artifact shape for real bowling-content validation
- run offline batch SAM2 from the standalone `yolo_seed.json` contract
- receive a live Quest `H.264` stream plus live metadata on the laptop
- keep a live laptop-to-Quest result channel open for lane/replay payloads
- make the landed live session decodable and loadable through the same analysis boundary as offline artifacts

Current validation entry point:

- `powershell -ExecutionPolicy Bypass -File .\laptop_receiver\setup_laptop_env.ps1`
- `powershell -ExecutionPolicy Bypass -File .\start_live_pipeline.ps1`
- `.\.venv\Scripts\python.exe -m laptop_receiver.validate_local_clip_artifact <artifact_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact <artifact_dir>` uses the repo-local YOLO26s checkpoint when it is present
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact <artifact_dir> --checkpoint <path-to-best.pt>` overrides the detector checkpoint
- `.\.venv\Scripts\python.exe -m laptop_receiver.import_legacy_bowling_run <legacy_run_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_sam2_on_artifact <artifact_dir>` runs the offline batch SAM2 check
- `.\.venv\Scripts\python.exe -m laptop_receiver.live_stream_receiver`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline`

Live alley startup:

- `powershell -ExecutionPolicy Bypass -File .\start_live_pipeline.ps1` stops stale live receiver/pipeline Python processes, starts the receiver, then runs the full `YOLO26s -> SAM2` live pipeline in the same terminal
- `powershell -ExecutionPolicy Bypass -File .\start_live_pipeline.ps1 -NoSam2` runs receiver plus YOLO shot detection/tracking without SAM2

Use the repo-local `.venv` for standalone work. The normal runtime path should not depend on the older experiment repo.

Important note:

- the proof diagnostics still show many `passthrough_not_updated` skips
- those skips are now understood as expected render-loop vs camera-source cadence mismatch
- current proof runs show about `72 Hz` render polling against a `~30 FPS` camera source, which matches the observed skip ratio closely

Live transport note:

- the main direction is now live Quest-to-laptop streaming
- Quest proof capture is being extended to stream encoded `H.264` media live while Unity sends frame metadata over a separate TCP side channel
- latest milestone: a real hotspot run now lands as a decodable live `H.264` session on the laptop, with codec config persisted and the shared loader able to open the session as a `LocalClipArtifact`
- lane lock is solved on the Quest: pinch/hold aligns the heads-region rectangle, release previews the full lane, and confirm sends the final lane geometry to the laptop

Lane-lock implementation note:

- lane lock is the Quest-side heads-region placement flow in:
  - [StandaloneQuestLaneLockStateCoordinator.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockStateCoordinator.cs)
  - [StandaloneQuestLaneLockButton.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockButton.cs)
  - [StandaloneQuestFloorPlaneSource.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFloorPlaneSource.cs)
- there is no laptop-side lane solver in the live loop and no dev injection path
- confirming the lane sends one `lane_lock_confirm` metadata event containing the complete `lane_lock_result`
- the laptop receiver persists that result at `analysis_lane_lock/<requestId>/lane_lock_result.json`
- YOLO shot gating, SAM2 tracking, and replay projection use that confirmed lane result directly
- typed result contracts are in:
  - [lane_lock_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_types.py)
- projection and lane-coordinate helpers are in:
  - [lane_geometry.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_geometry.py)
- the session stream itself is now managed by:
  - [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs)
- that controller replaces the old short proof autorun behavior and keeps one live stream active for the session until we explicitly stop it
- one live session is created per Quest app run; closing and reopening the Quest app creates a fresh `session_id`
- live runs should first disable proximity sleep with `adb shell am broadcast -a com.oculus.vrpowermanager.prox_close`
- if Quest/app/camera/encoder truly pause/restart from zero or the tracking origin relocalizes, the lane must be locked again
- the live pipeline processes the latest live stream by default; old streams stay on disk and are used only when selected explicitly
- the Quest app discovers the laptop at runtime over UDP `8765`, so the scene no longer needs a hardcoded laptop IP
- the laptop receiver also owns the Quest-facing result channel:
  - Quest listens as a client on `tcp://<laptop>:8769`
  - laptop analysis stages publish strict result envelopes to `tcp://127.0.0.1:8770`
  - forwarded results are persisted in `outbound_results.jsonl`
- strict shot-boundary parsing is in:
  - [live_shot_boundaries.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundaries.py)
- automatic YOLO/lane-space shot-boundary detection is in:
  - [live_shot_boundary_detector.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundary_detector.py)
- lane-lock results can now be processed and forwarded to Quest through the same session channel instead of being only local files
- shot boundaries are now generated after lane lock, with camera SAM2 ending each shot after tracking loss or the fixed live tracking window
- live camera SAM2 tracking is in:
  - [live_camera_sam2_tracker.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_camera_sam2_tracker.py)
- windowed live shot tracking is in:
  - [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py)
- strict shot result payloads are in:
  - [shot_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/shot_result_types.py)
- the live pipeline can now auto-detect shot starts with YOLO, seed camera SAM2 immediately, and build results only from that camera SAM2 track when configured with `--yolo-checkpoint --run-sam2`
- `shot_result` messages require lane-space trajectory data from a user-confirmed lane lock; missing or invalidated lane confirmation is reported as a failed result, not guessed
- automatic shot windows carry the confirmed `laneLockRequestId`, and shot tracking projects through that exact lane result
- Quest-side replay rendering consumes successful `shot_result.trajectory` points through [StandaloneQuestShotReplayRenderer.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestShotReplayRenderer.cs)
- the old desktop click harness was removed because those clicks were not physical foul-line endpoints
- no automatic lane identity selection, view-center guess, or silent acceptance path remains in lane locking

See [docs/IMPLEMENTATION_PLAN.md](C:/Users/student/QuestBowlingStandalone/docs/IMPLEMENTATION_PLAN.md) for the active build sequence.
See [docs/PORTING_MAP.md](C:/Users/student/QuestBowlingStandalone/docs/PORTING_MAP.md) for the exact archive files we should mine and what to avoid copying.
