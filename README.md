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
- `YOLO -> SAM2`
- true lane-anchored MR replay

## Repository Layout

- `docs/`: product definition and implementation notes
- `unity_proof/`: clean Unity project for Quest-side standalone proof runs
- `quest_app/`: Quest-side standalone product module
- `laptop_receiver/`: laptop-side media, tracking, and replay module
- `protocol/`: shared schemas and message contracts
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
- run warm SAM2 from the standalone `yolo_seed.json` contract
- receive a live Quest `H.264` stream plus live metadata on the laptop
- keep a live laptop-to-Quest result channel open for lane/replay payloads
- make the landed live session decodable and loadable through the same analysis boundary as offline artifacts

Current validation entry point:

- `py -m venv .venv`
- `.\.venv\Scripts\python.exe -m pip install --upgrade pip`
- `.\.venv\Scripts\python.exe -m pip install -r laptop_receiver/requirements-cuda.txt`
- `.\.venv\Scripts\python.exe -m laptop_receiver.validate_local_clip_artifact <artifact_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact <artifact_dir> --checkpoint <path-to-best.pt>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.import_legacy_bowling_run <legacy_run_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_sam2_on_artifact <artifact_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.live_stream_receiver`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_lane_lock_on_live_session <live_session_dir>`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_lane_lock_on_live_session <live_session_dir> --publish-result-host 127.0.0.1`
- `.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline`

Use the repo-local `.venv` for standalone work. The old `Quest3BowlingBallTracking\laptop_pipeline\.venv` should only be a reference while we finish cutting dependencies over.

Important note:

- the proof diagnostics still show many `passthrough_not_updated` skips
- those skips are now understood as expected render-loop vs camera-source cadence mismatch
- current proof runs show about `72 Hz` render polling against a `~30 FPS` camera source, which matches the observed skip ratio closely

Live transport note:

- the main direction is now live Quest-to-laptop streaming
- Quest proof capture is being extended to stream encoded `H.264` media live while Unity sends frame metadata over a separate TCP side channel
- latest milestone: a real hotspot run now lands as a decodable live `H.264` session on the laptop, with codec config persisted and the shared loader able to open the session as a `LocalClipArtifact`
- lane lock now follows that same media path: `Lock Lane` tags a short request window inside the continuous session stream instead of creating a separate JPG bundle

Lane-lock implementation note:

- lane lock is now manual foul-line lane selection, not automatic lane choice
- the user-selected inputs are:
  - left lane edge at the foul line
  - right lane edge at the foul line
  - the exact frame sequence where those points were selected
- typed request/result contracts are in:
  - [lane_lock_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_types.py)
- projection and lane-coordinate helpers are in:
  - [lane_geometry.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_geometry.py)
- the solver is in:
  - [lane_lock_solver.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_solver.py)
- line-support extraction is still available for validation/overlay scoring:
  - [lane_line_support.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_line_support.py)
- Quest-side request capture is in:
  - [StandaloneQuestRayInteractor.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestRayInteractor.cs)
  - [StandaloneQuestFoulLineRaySelector.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFoulLineRaySelector.cs)
  - [StandaloneQuestLaneLockCapture.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockCapture.cs)
  - [StandaloneQuestLaneLockButton.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockButton.cs)
  - [StandaloneQuestFloorPlaneSource.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFloorPlaneSource.cs)
  - [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs)
- the shared ray interactor is reusable by replay controls; the foul-line selector is just the lane-lock consumer
- that Quest-side slice rejects lane-lock requests until a foul-line selection exists, then sends one `lane_lock_request` metadata event with:
  - `selectionFrameSeq`
  - `leftFoulLinePointNorm`
  - `rightFoulLinePointNorm`
  - frame range
  - capture duration
  - camera intrinsics
  - floor plane
  - regulation lane dimensions
- the session stream itself is now managed by:
  - [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs)
- that controller replaces the old short proof autorun behavior and keeps one live stream active for the session until we explicitly stop it
- the laptop receiver persists those requests in `lane_lock_requests.jsonl` next to the streamed `H.264` session
- the laptop receiver also owns the Quest-facing result channel:
  - Quest listens as a client on `tcp://<laptop>:8769`
  - laptop analysis stages publish strict result envelopes to `tcp://127.0.0.1:8770`
  - forwarded results are persisted in `outbound_results.jsonl`
- the current lane-lock runner is:
  - [run_lane_lock_on_live_session.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_lane_lock_on_live_session.py)
- the reusable lane-lock stage and live pipeline are in:
  - [live_lane_lock_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_lane_lock_stage.py)
  - [live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_session_pipeline.py)
  - [run_live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_live_session_pipeline.py)
- strict shot-boundary parsing is in:
  - [live_shot_boundaries.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundaries.py)
- automatic YOLO/lane-space shot-boundary detection is in:
  - [live_shot_boundary_detector.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundary_detector.py)
- lane-lock results can now be processed and forwarded to Quest through the same session channel instead of being only local files
- shot boundaries are now generated after lane lock, then validated as `shot_start` / `shot_end` windows before the tracking stage is attached
- windowed live shot tracking is in:
  - [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py)
- strict shot result payloads are in:
  - [shot_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/shot_result_types.py)
- the live pipeline can now auto-detect shot windows and run `YOLO -> SAM2` inside completed windows when configured with `--yolo-checkpoint` and optional `--run-sam2`
- `shot_result` messages require lane-space trajectory data from a successful lane lock; missing lane lock is reported as a failed result, not guessed
- Quest-side replay rendering consumes successful `shot_result.trajectory` points through [StandaloneQuestShotReplayRenderer.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestShotReplayRenderer.cs)
- the old desktop click harness was removed because those clicks were not physical foul-line endpoints
- no automatic lane identity selection, view-center fallback, or silent acceptance path remains in the lane-lock solver

See [docs/IMPLEMENTATION_PLAN.md](C:/Users/student/QuestBowlingStandalone/docs/IMPLEMENTATION_PLAN.md) for the active build sequence.
See [docs/PORTING_MAP.md](C:/Users/student/QuestBowlingStandalone/docs/PORTING_MAP.md) for the exact archive files we should mine and what to avoid copying.
