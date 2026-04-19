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
- Latest pulled proof artifact:
  - `C:\Users\student\QuestBowlingStandalone\unity_proof\Temp\device_pull\standalone_local_clips\clip_2e2890ae03b64ce3b98d37938bf3b199_standalone-proof`
- The earlier `passthrough_not_updated` concern is now understood as expected cadence mismatch:
  - render loop is polling around `72 Hz`
  - camera source is updating around `30 FPS`
  - observed success/skip ratio matches that pattern closely

## Immediate Next Focus

1. Commit the clean proof milestone without dragging generated Unity/build clutter into Git.
2. Inspect the proof clip visually and with richer media tooling when convenient so we have a human-quality check in addition to metadata checks.
3. Decide the next disciplined slice after local proof:
   - laptop ingest of the local proof artifact, or
   - Quest-side rolling buffer / shot-boundary logic
4. Keep `unity_proof` as the primary Quest-side testbed and avoid falling back to the old bowling app project for proof runs.

## Important Assumption

- the first native surface path is explicitly `OpenGL ES 3`-oriented
- if the eventual Unity project is configured differently, we must realign the bridge instead of forcing it blindly
- current proof metadata uses camera-derived timing and passes that timing into the encoder surface path
- we still have not independently inspected the MP4 container timestamps with dedicated media tooling, so that remains a future verification step rather than a current blocker

## Known Follow-Ups

- Unity build output still warns that [libstandaloneencodersurfacebridge.so](C:/Users/student/QuestBowlingStandalone/unity_proof/Assets/Plugins/Android/arm64-v8a/libstandaloneencodersurfacebridge.so) is not `16KB` aligned for Android 15+ page-size guidance. This is not blocking current Quest proof runs, but it should be cleaned up before a more production-shaped build.
- Unity also logs an optional future deprecation note about switching from `OpenXR.Input.PoseControl` to `InputSystem.XR.PoseControl`. That is not blocking the proof milestone either.
