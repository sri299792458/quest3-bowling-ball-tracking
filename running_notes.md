# Running Notes

Last updated: 2026-04-19

## Purpose

This file is the current working log for the standalone bowling replay project.

Use it to keep:

- the latest decisions
- current blockers
- next concrete tasks
- dataset or validation notes

The goal is to avoid drifting into disconnected experiments.

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
  - [StandaloneProofAutoRun.cs](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/StandaloneProof/Runtime/StandaloneProofAutoRun.cs) now starts live media + metadata streaming alongside proof capture
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
- The earlier `passthrough_not_updated` concern is now understood as expected cadence mismatch:
  - render loop is polling around `72 Hz`
  - camera source is updating around `30 FPS`
  - observed success/skip ratio matches that pattern closely

## Immediate Next Focus

1. Keep building on the clean laptop-side ingest path rather than jumping into lane lock first.
2. Port only the necessary old laptop pieces onto the new artifact boundary:
   - decode
   - YOLO seed ingest
   - SAM2 tracking input
3. Keep `unity_proof` as the primary Quest-side testbed and avoid falling back to the old bowling app project for proof runs.
4. Decide the next analysis move now that live intake is real:
   - causal YOLO directly over a live session directory after landing
   - or a tighter rolling/near-live decode path
5. When a real bowling clip is available, validate one live bowling session end to end through:
   - live stream landing
   - YOLO seed
   - SAM2 tracking
6. Expand validation from one imported bowling clip to a small batch, so we know whether the standalone adapter holds up across multiple runs.
7. Decide whether the tiny SAM2 drift versus the old JPEG-first path is acceptable or worth deeper investigation.
8. Inspect the proof clip visually and with richer media tooling when convenient so we have a human-quality check in addition to metadata checks.

## Important Assumption

- the first native surface path is explicitly `OpenGL ES 3`-oriented
- if the eventual Unity project is configured differently, we must realign the bridge instead of forcing it blindly
- current proof metadata uses camera-derived timing and passes that timing into the encoder surface path
- we still have not independently inspected the MP4 container timestamps with dedicated media tooling, so that remains a future verification step rather than a current blocker

## Known Follow-Ups

- Unity build output still warns that [libstandaloneencodersurfacebridge.so](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/Plugins/Android/arm64-v8a/libstandaloneencodersurfacebridge.so) is not `16KB` aligned for Android 15+ page-size guidance. This is not blocking current Quest proof runs, but it should be cleaned up before a more production-shaped build.
- Unity also logs an optional future deprecation note about switching from `OpenXR.Input.PoseControl` to `InputSystem.XR.PoseControl`. That is not blocking the proof milestone either.
