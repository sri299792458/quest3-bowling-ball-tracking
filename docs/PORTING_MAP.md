# Porting Map From Archive Repo

Last updated: 2026-04-18

This file records which pieces of the old repository are worth mining for the standalone build.

The rule is:

- copy only proven pieces
- do not drag old architecture forward by accident

## Quest-Side Sources Worth Mining First

### 1. `QuestBowlingStreamClient.cs`

Archive path:

- `C:\Users\student\Quest3BowlingBallTracking\Assets\BallTracking\Runtime\QuestBowlingStreamClient.cs`

Use for:

- camera timestamp capture
- camera pose capture
- head pose capture
- session state ideas
- lane-lock message/state ideas
- shot marker ideas

Do **not** copy whole-cloth for the standalone build.

Avoid carrying over:

- JPEG encode path
- current TCP/UDP streaming loop
- async GPU readback experiment code
- accumulated debug/status plumbing that only exists for the old pipeline

### 2. `BowlingProtocol.cs`

Archive path:

- `C:\Users\student\Quest3BowlingBallTracking\Assets\BallTracking\Runtime\BowlingProtocol.cs`

Use for:

- packet/message taxonomy
- shot marker enum ideas
- shared schema vocabulary

Do **not** assume the old wire format is the standalone format.

The standalone `protocol/` module should stay free to define cleaner contracts.

### 3. `QuestVideoEncoderProbe.cs`

Archive path:

- `C:\Users\student\Quest3BowlingBallTracking\Assets\BallTracking\Runtime\QuestVideoEncoderProbe.cs`

Use for:

- early Android codec capability probing
- confirming `video/avc` availability on-device

This is one of the safest early pieces to port nearly as-is.

## Laptop-Side Sources Worth Mining Later

### 4. `quest_bowling_udp_server.py`

Archive path:

- `C:\Users\student\Quest3BowlingBallTracking\laptop_pipeline\quest_bowling_udp_server.py`

Use later for:

- session/shot artifact layout ideas
- metadata persistence ideas
- result handoff ideas

Do **not** copy:

- JPEG-specific frame reassembly
- old per-shot server assumptions
- transport details tied to the old UDP chunked JPEG path

## Tracking Sources Worth Mining Later

### 5. Existing `YOLO -> SAM2` logic

Archive area:

- `C:\Users\student\Quest3BowlingBallTracking\laptop_pipeline`

Use later for:

- seeding heuristics
- shot bundle layout ideas
- evaluation against `bowling_tests`

Do **not** bring over:

- training utilities
- hillclimb tooling
- oracle review tooling

unless a later milestone clearly needs them.

## First Porting Order

1. port encoder capability probe ideas
2. port timestamp/pose capture ideas
3. define clean standalone metadata schema
4. only then port tracking-side logic
