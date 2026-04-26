# Running Notes

Last updated: 2026-04-25

## Purpose

This file is the current working log for the standalone bowling replay project.

Use it to keep:

- the latest decisions
- current blockers
- next concrete tasks
- dataset or validation notes

The goal is to avoid drifting into disconnected experiments.

## Latest Session Update

- Lane lock is now explicitly the manual foul-line selection workflow.
- The user-selected contract is:
  - left lane edge at the foul line
  - right lane edge at the foul line
  - `selectionFrameSeq` for the frame where those two points were selected
- The solver converts those two selected pixels into world rays using camera intrinsics and camera pose, infers the lane plane offset from known lane width, and builds the lane basis from the selected foul-line segment.
- The old automatic lane identity path, view-center aim fallback, and image-template lane search are no longer part of the active workflow.
- The old desktop click harness was removed because those points were not physical foul-line endpoints.
- The live request is invalid unless it contains `selectionFrameSeq`, `leftFoulLinePointNorm`, and `rightFoulLinePointNorm`.
- Old annotation/result artifact folders were deleted so they cannot be mistaken for valid foul-line analysis.
- The live session now has a laptop-to-Quest result channel:
  - Quest connects to `tcp://<laptop>:8769`
  - laptop analysis producers publish strict result envelopes to `tcp://127.0.0.1:8770`
  - forwarded results are persisted as `outbound_results.jsonl`
- Shared Quest ray selection is now started:
  - [StandaloneQuestRayInteractor.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestRayInteractor.cs)
  - [StandaloneQuestFoulLineRaySelector.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFoulLineRaySelector.cs)
  - lane lock consumes the common world-ray selection stream, intersects it with the floor, projects that floor hit into the current camera frame, then calls `TrySetFoulLineSelection`
- Laptop lane lock is now a reusable live-session stage:
  - [live_lane_lock_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_lane_lock_stage.py)
  - [live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_session_pipeline.py)
  - [run_live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_live_session_pipeline.py)
- The live pipeline polls landed live session folders, processes each strict `lane_lock_request` once, writes `analysis_live_pipeline/pipeline_state.json`, and publishes the lane-lock result through the existing result channel.
- Shot boundaries are now strict `shot_start` / `shot_end` events:
  - [live_shot_boundaries.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundaries.py)
  - [live_shot_boundary_detector.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundary_detector.py) auto-writes those events after lane lock by projecting YOLO detections into the locked lane frame
  - the live pipeline reports completed shot windows, open shot windows, and malformed boundary errors before YOLO/SAM2 is attached to those windows
- Live shot tracking is now window-aware:
  - [standalone_yolo_seed.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_yolo_seed.py) can search only a requested `frameSeq` window
  - [standalone_sam2_tracking.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_sam2_tracking.py) can materialize and track only a requested source-frame range
  - [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py) ties those together for completed live shot windows
  - [run_live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_live_session_pipeline.py) enables automatic boundaries and tracking when `--yolo-checkpoint` is passed, with SAM2 behind `--run-sam2`
- The standalone repo now has its own local `.venv` for laptop analysis.
- Use [requirements-cuda.txt](C:/Users/student/QuestBowlingStandalone/laptop_receiver/requirements-cuda.txt) for the full CUDA/SAM2-capable environment; the old `Quest3BowlingBallTracking\laptop_pipeline\.venv` is no longer the default validation environment.
- `shot_result` is now a strict laptop-to-Quest payload:
  - [shot_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/shot_result_types.py)
  - [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py) writes `shot_result.json`
  - [StandaloneQuestLiveResultReceiver.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLiveResultReceiver.cs) receives `shot_result`
  - [StandaloneQuestShotReplayRenderer.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestShotReplayRenderer.cs) renders successful lane-space shot trajectories back in Quest world space
  - replayable results require a solved lane lock; missing lane lock is a failed `shot_result`, not a guessed trajectory

## Current State

- New standalone repo created at `C:\Users\student\QuestBowlingStandalone`
- Fresh clean Unity proof project created at `C:\Users\student\QuestBowlingStandalone\unity_proof`
- Product definition moved to [docs/STANDALONE_PRODUCT_GOAL.md](C:/Users/student/QuestBowlingStandalone/docs/STANDALONE_PRODUCT_GOAL.md)
- Initial implementation map added in [docs/IMPLEMENTATION_PLAN.md](C:/Users/student/QuestBowlingStandalone/docs/IMPLEMENTATION_PLAN.md)
- Archive mining map added in [docs/PORTING_MAP.md](C:/Users/student/QuestBowlingStandalone/docs/PORTING_MAP.md)
- First validation dataset moved locally to `C:\Users\student\QuestBowlingStandalone\data\bowling_tests`
- `bowling_tests` is intentionally local-only for now and excluded from Git by `.gitignore`
- Module folders created:
  - [quest_app](C:/Users/student/QuestBowlingStandalone/quest_app)
  - [laptop_receiver](C:/Users/student/QuestBowlingStandalone/laptop_receiver)
  - [protocol](C:/Users/student/QuestBowlingStandalone/protocol)
- First safe standalone code port added:
  - [QuestVideoEncoderProbe.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/QuestVideoEncoderProbe.cs)
- First standalone Quest capture stub added:
  - [StandaloneCaptureTypes.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneCaptureTypes.cs)
  - [QuestCaptureMetadataBuilder.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/QuestCaptureMetadataBuilder.cs)
  - [StandaloneLocalClipArtifactWriter.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneLocalClipArtifactWriter.cs)
  - [StandaloneQuestLocalProofCapture.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneQuestLocalProofCapture.cs)
  - [StandaloneQuestVideoEncoderBridge.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneQuestVideoEncoderBridge.cs)
  - [StandaloneQuestFrameSource.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneQuestFrameSource.cs)
- First Android encoder plugin scaffold added:
  - [quest_app/Plugins/Android/README.md](C:/Users/student/QuestBowlingStandalone/quest_app/Plugins/Android/README.md)
  - [StandaloneVideoEncoderPlugin.java](C:/Users/student/QuestBowlingStandalone/quest_app/Plugins/Android/src/main/java/com/questbowling/standalone/StandaloneVideoEncoderPlugin.java)
  - [StandaloneEncoderSurfaceBridge.cpp](C:/Users/student/QuestBowlingStandalone/quest_app/Plugins/Android/src/main/cpp/StandaloneEncoderSurfaceBridge.cpp)
- Clean Unity proof project has already been seeded with:
  - minimal passthrough/XR package manifest in [unity_proof/Packages/manifest.json](C:/Users/student/QuestBowlingStandalone/unity_proof/Packages/manifest.json)
  - resolved package lock in [unity_proof/Packages/packages-lock.json](C:/Users/student/QuestBowlingStandalone/unity_proof/Packages/packages-lock.json)
  - standalone proof runtime scripts under [unity_proof/Assets/StandaloneProof/Runtime](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime)
  - Android encoder plugin under [unity_proof/Assets/Plugins/Android/StandaloneVideoEncoderPlugin](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/Plugins/Android/StandaloneVideoEncoderPlugin)
- First standalone metadata contract added:
  - [CAPTURE_METADATA_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/CAPTURE_METADATA_V1.md)
  - [LOCAL_CLIP_ARTIFACT_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/LOCAL_CLIP_ARTIFACT_V1.md)
- Clean proof milestone is now real in [unity_proof](C:/Users/student/QuestBowlingStandalone/unity_proof):
  - visible passthrough works
  - local Quest-side `H.264` proof clips are written on-device
  - `frame_metadata.jsonl` is written alongside the clip
  - native encoder surface bind + blit path is working
  - `ptsUs` now matches `cameraTimestampUs - firstCameraTimestampUs`
- Laptop-side standalone artifact ingest is now started cleanly:
  - [local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/local_clip_artifact.py)
  - [validate_local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/validate_local_clip_artifact.py)
- Standalone YOLO seed port is now started cleanly:
  - [standalone_yolo_seed.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_yolo_seed.py)
  - [run_yolo_seed_on_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_yolo_seed_on_artifact.py)
- Latest pulled proof artifact for validation:
  - `C:\Users\student\QuestBowlingStandalone\data\proof_artifacts\clip_2e2890ae03b64ce3b98d37938bf3b199_standalone-proof`
- Validation result on that artifact:
  - decoded video frame count: `180`
  - metadata frame count: `180`
  - `ptsUs` offset range relative to camera timeline: `[0, 0]`
  - result: `PASS`
- YOLO seed smoke test on that same artifact:
  - result: clean `FAIL`
  - failure reason: `yolo_detection_failed`
  - searched frames: `180`
  - best candidate: `none`
  - interpretation: expected, because the proof clip is not a bowling-shot artifact
- Legacy-to-standalone adapter is now in place:
  - [import_legacy_bowling_run.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/import_legacy_bowling_run.py)
- Important cleanup:
  - the adapter no longer fabricates a fake standalone lane lock from old `lane_calibration.json`
  - new imports now write `laneLockState = 0` and a note instead of pretending the old debug payload is real standalone lock data
- First imported bowling artifact:
  - `C:\Users\student\QuestBowlingStandalone\data\imported_artifacts\a28ae558fcc04acea0ceb5a5dac3f199_shot_1774746015082_20260328_200013_standalone-artifact`
- Validation result on that imported artifact:
  - decoded video frame count: `129`
  - metadata frame count: `129`
  - `ptsUs` offset range relative to camera timeline: `[0, 0]`
  - result: `PASS`
- YOLO seed result on that imported artifact:
  - result: `PASS`
  - seed frame: `54`
  - detector confidence: `0.8170`
  - searched frames: `55`
  - note: this matches the old pipeline's causal seed frame for the same clip
- Standalone SAM2 port is now started cleanly:
  - [standalone_warm_sam2_tracker.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_warm_sam2_tracker.py)
  - [standalone_sam2_tracking.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/standalone_sam2_tracking.py)
  - [run_sam2_on_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_sam2_on_artifact.py)
- Standalone SAM2 result on the imported bowling artifact:
  - result: `PASS`
  - tracked frames: `20`
  - first frame: `54`
  - last frame: `73`
  - total seconds: about `56.3`
  - note: old pipeline tracked `21` frames through frame `74` on the original JPEG run, so the standalone-imported MP4 path is very close but not pixel-identical
  - likely reason: imported artifact goes through MP4 encode/decode plus extracted JPEG cache before SAM2
- Streaming-ready laptop handoff is now started cleanly:
  - [live_stream_receiver.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_stream_receiver.py)
- Live-stream protocol contract is now started cleanly:
  - [LIVE_H264_STREAM_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/LIVE_H264_STREAM_V1.md)
- Local live receiver smoke result:
  - synthetic media stream passed
  - synthetic metadata side channel passed
  - receiver persisted `stream.h264`, `media_samples.jsonl`, `metadata_stream.jsonl`, `session_start.json`, `session_end.json`, and `stream_receipt.json`
- Quest proof app live transport hooks are now started cleanly:
  - [StandaloneQuestLiveMetadataSender.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLiveMetadataSender.cs)
  - [StandaloneQuestVideoEncoderBridge.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestVideoEncoderBridge.cs) now exposes live media connect/disconnect
  - [StandaloneVideoEncoderPlugin.java](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/Plugins/Android/StandaloneVideoEncoderPlugin/src/main/java/com/questbowling/standalone/StandaloneVideoEncoderPlugin.java) now streams encoded `H.264` samples from the encoder drain loop
  - [StandaloneQuestProofRenderCoordinator.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestProofRenderCoordinator.cs) now mirrors committed frame metadata to the live metadata channel
- Real live hotspot streaming is now proven end to end:
  - live session directories land under `C:\Users\student\QuestBowlingStandalone\data\incoming_live_streams`
  - the Java encoder now sends explicit codec config for live sessions
  - the receiver now persists `codec_config.h264` and prefixes `stream.h264` with decodable SPS/PPS bytes
  - `ffprobe` now recognizes the landed live stream as `1280x960` H.264 High Profile instead of failing on missing PPS
  - the shared loader in [local_clip_artifact.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/local_clip_artifact.py) now opens a live session directory through the same analysis boundary as offline artifacts
  - latest verified live session:
    - `C:\Users\student\QuestBowlingStandalone\data\incoming_live_streams\live_e031bed968584a678586ad1edc57b1a5_standalone-proof`
  - latest verified live receipt:
    - `178` media samples
    - `6` keyframes
    - `180` metadata messages
    - `codec_config_seen = true`
- Live YOLO smoke result on that latest live proof session:
  - result: clean `FAIL`
  - failure reason: `yolo_detection_failed`
  - interpretation: expected, because the proof clip was not a real bowling shot
  - important part: the standalone YOLO seed path now runs directly on a live landed session directory
- Lane-lock design is now written down explicitly in:
  - [LANE_LOCK_MATH_AND_CONTRACT.md](C:/Users/student/QuestBowlingStandalone/docs/LANE_LOCK_MATH_AND_CONTRACT.md)
  - this is the source of truth for:
    - lane model parameterization
    - ray-plane projection math
    - lock request/result JSON contracts
    - lane-space ball coordinate contract
- Lane-lock implementation is now the foul-line selection path:
  - [lane_lock_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_types.py)
  - [lane_geometry.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_geometry.py)
  - [lane_lock_solver.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_solver.py)
  - [lane_line_support.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_line_support.py)
- Important lane-lock cleanup:
  - removed the automatic image-lane fit/template-search path from active code
  - lane identity is no longer inferred from the view center, a best candidate, or early multi-lane footage
  - old click/benchmark artifacts were removed because they were not foul-line endpoint selections
  - the legacy importer still avoids fabricating a fake standalone lane lock from old `lane_calibration.json`
- Line-support extraction remains inside the live-session solver only as overlay/scoring support; it does not choose the lane identity.
- Quest-side lane-lock request capture is now started in the real runtime path:
  - [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs)
  - [StandaloneQuestFloorPlaneSource.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFloorPlaneSource.cs)
  - [StandaloneQuestLaneLockCapture.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockCapture.cs)
  - [StandaloneQuestLaneLockButton.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLaneLockButton.cs)
- That runtime slice now does the right high-level thing:
  - keep one shared Quest session id
  - keep one continuous live `H.264 + metadata` session stream active
  - start and hold that stream through [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs) instead of a short proof autorun
  - reject lane-lock requests until the user-selected foul-line points exist
  - capture the selected frame plus a short lock window inside that stream
  - emit one `lane_lock_request` metadata event instead of creating a second JPG pipeline
  - include selected foul-line points, frame range, capture duration, intrinsics, floor plane, and lane dimensions in that event
- Laptop-side lane-lock session ingestion is now started:
  - [lane_lock_live_session.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/lane_lock_live_session.py)
  - [run_lane_lock_on_live_session.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_lane_lock_on_live_session.py)
- The live receiver now persists lane-lock and shot event sidecars next to the session stream:
  - `lane_lock_requests.jsonl`
  - `shot_boundaries.jsonl`
  - `outbound_results.jsonl`
- Laptop-to-Quest result return is now started:
  - [laptop_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/laptop_result_types.py)
  - [StandaloneQuestLiveResultReceiver.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestLiveResultReceiver.cs)
  - [StandaloneQuestSessionController.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestSessionController.cs)
- Result envelopes require `schemaVersion = laptop_result_envelope`; lane-lock result payloads require `schemaVersion = lane_lock_result`.
- [run_lane_lock_on_live_session.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_lane_lock_on_live_session.py) can now publish a solved lane lock with `--publish-result-host 127.0.0.1`.
- [live_lane_lock_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_lane_lock_stage.py) holds the shared lane-lock solve/write/preview stage used by the one-shot CLI and live pipeline.
- [run_live_session_pipeline.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/run_live_session_pipeline.py) is the first laptop session orchestrator: it processes pending live `lane_lock_request` events once, persists pipeline state, and can publish results to Quest through the live receiver.
- [live_shot_boundaries.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_boundaries.py) validates completed shot windows from `shot_boundaries.jsonl`; only `shot_start` and `shot_end` are accepted boundary types.
- [live_shot_tracking_stage.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/live_shot_tracking_stage.py) runs windowed shot tracking under `analysis_shot_tracking/<windowId>`.
- [shot_result_types.py](C:/Users/student/QuestBowlingStandalone/laptop_receiver/shot_result_types.py) defines the compact replay-facing shot result contract.
- [StandaloneQuestShotReplayRenderer.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestShotReplayRenderer.cs) listens for `shot_result` events and renders a replay trajectory plus moving marker in Quest world space.
- Quest-side foul-line selection now has a common input layer:
  - [StandaloneQuestRayInteractor.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestRayInteractor.cs) emits shared hand/controller ray selections
  - [StandaloneQuestFoulLineRaySelector.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneQuestFoulLineRaySelector.cs) is the lane-specific consumer
  - first selection is left foul-line edge; second selection is right foul-line edge; invalid order is rejected by the existing strict lane-lock request path
- Current explicit lane-selection decision:
  - the user must provide the two foul-line edge selections before `Lock Lane` can send a request
  - the selection frame is part of the request and is the only anchor frame the solver accepts
  - line support may score or visualize the result, but it does not choose the lane identity
- The earlier `passthrough_not_updated` concern is now understood as expected cadence mismatch:
  - render loop is polling around `72 Hz`
  - camera source is updating around `30 FPS`
  - observed success/skip ratio matches that pattern closely

## Immediate Next Focus

1. Keep `unity_proof` as the primary Quest-side testbed and avoid falling back to the old bowling app project for proof runs.
2. Build and deploy the Unity proof scene so the shared ray selector can be verified on-device.
3. Verify that a real live session writes `lane_lock_requests.jsonl` with `selectionFrameSeq`, `leftFoulLinePointNorm`, and `rightFoulLinePointNorm`.
4. Run `run_lane_lock_on_live_session.py` on that landed session, publish the result through `--publish-result-host 127.0.0.1`, and confirm Quest receives it.
5. Run `run_live_session_pipeline.py` beside `live_stream_receiver.py` and confirm the lane-lock result is processed and returned automatically.
6. Exercise the new `shot_result` payload and Quest replay renderer on a real live shot window after lane lock is solved.
7. When a real bowling clip is available, validate one live bowling session end to end through:
   - live stream landing
   - lane lock
   - result return to Quest
   - YOLO seed
   - SAM2 tracking
   - strict `shot_result` return
8. Expand validation from one imported bowling clip to a small batch, so we know whether the standalone adapter holds up across multiple runs.
9. Decide whether the tiny SAM2 drift versus the old JPEG-first path is acceptable or worth deeper investigation.

## Important Assumption

- the first native surface path is explicitly `OpenGL ES 3`-oriented
- if the eventual Unity project is configured differently, we must realign the bridge instead of forcing it blindly
- current proof metadata uses camera-derived timing and passes that timing into the encoder surface path
- we still have not independently inspected the MP4 container timestamps with dedicated media tooling, so that remains a future verification step rather than a current blocker

## Known Follow-Ups

- Unity build output still warns that [libstandaloneencodersurfacebridge.so](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/Plugins/Android/arm64-v8a/libstandaloneencodersurfacebridge.so) is not `16KB` aligned for Android 15+ page-size guidance. This is not blocking current Quest proof runs, but it should be cleaned up before a more production-shaped build.
- Unity also logs an optional future deprecation note about switching from `OpenXR.Input.PoseControl` to `InputSystem.XR.PoseControl`. That is not blocking the proof milestone either.
