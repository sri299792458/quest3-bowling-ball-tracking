# Quest App

This module will contain the standalone Quest-side product code.

Responsibilities:

- passthrough camera access
- lane-lock UX
- local `H.264` encode
- rolling encoded buffer
- shot boundary markers
- replay rendering

First target:

- prove local `H.264` encode at `1280 x 960 @ 30 FPS`
- preserve frame timestamp and pose metadata cleanly

First concrete file:

- [QuestVideoEncoderProbe.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/QuestVideoEncoderProbe.cs)
- [StandaloneCaptureTypes.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneCaptureTypes.cs)
- [QuestCaptureMetadataBuilder.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/QuestCaptureMetadataBuilder.cs)
- [StandaloneLocalClipArtifactWriter.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneLocalClipArtifactWriter.cs)
- [StandaloneQuestLocalProofCapture.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneQuestLocalProofCapture.cs)
- [StandaloneQuestFrameSource.cs](C:/Users/student/QuestBowlingStandalone/quest_app/Runtime/StandaloneQuestFrameSource.cs)

Current state:

- local proof capture flow can now write the standalone metadata/artifact shape
- a first `MediaCodec` bridge scaffold now exists for starting/stopping a local encoder session
- a standalone frame-source layer now owns passthrough render-target creation and camera FPS request
- the native surface bridge is currently written as an `OpenGL ES 3` render-thread path
- the remaining hard part is rendering that Unity output into the encoder input surface
