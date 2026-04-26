# Standalone Implementation Plan

Last updated: 2026-04-25

This document turns the product goal into a concrete build layout and a small first execution slice.

## Module Layout

### `quest_app/`

Owns everything that runs on Quest:

- passthrough camera access
- lane-lock UX and session state
- hardware `H.264` encode path
- rolling encoded session buffer
- shot markers and per-frame metadata capture
- live laptop result receiver
- replay rendering on the locked lane

### `laptop_receiver/`

Owns everything that runs on the laptop:

- media ingest
- result return channel
- clip reconstruction
- frame plus metadata decode
- `YOLO` seed
- `SAM2` track
- lane-space analytics
- replay payload generation back to Quest

### `protocol/`

Owns shared contracts:

- session metadata schema
- per-frame metadata schema
- shot marker schema
- transport message types
- versioning rules between Quest and laptop

## First Build Principle

Do not try to build the whole product at once.

The first real implementation slice is:

1. Quest local `H.264` proof-of-life at `1280 x 960 @ 30 FPS`
2. per-frame metadata capture with trustworthy timestamp and pose linkage
3. local clip artifact that can later be handed to the laptop side

This intentionally avoids networking until the media path itself is proven.

## Immediate Milestones

### Milestone 0: Repo Scaffold

- create clean module folders
- keep one clear entry README
- keep `running_notes.md` current

### Milestone 1: Quest Local Encode Proof

Success means:

- Quest can encode local `H.264`
- the clip is decodable
- target settings are `1280 x 960 @ 30 FPS`
- we can associate encoded output with frame timestamps and poses
- we can export a local artifact shaped like [LOCAL_CLIP_ARTIFACT_V1.md](C:/Users/student/QuestBowlingStandalone/protocol/schemas/LOCAL_CLIP_ARTIFACT_V1.md)

Current sub-state:

- metadata capture and local artifact writing scaffold exist
- a first Android `MediaCodec` / `MediaMuxer` bridge scaffold exists
- a standalone Quest frame source now exists for `RenderTexture` generation at target settings
- the remaining hard part is feeding that Unity-rendered output into the encoder input surface reliably

### Milestone 2: Lane Lock Session Loop

Success means:

- user can enter a lightweight lane-lock flow
- Quest confirms `lane locked`
- laptop can return a strict lane-lock result to Quest
- a lane model is cached for the session

### Milestone 3: Rolling Buffer + Shot Boundaries

Success means:

- Quest keeps a rolling encoded buffer
- laptop-side YOLO/release logic writes strict `shot_start` events after lane lock
- laptop-side track/end logic writes strict `shot_end` events
- a useful shot clip can be cut with pre-roll and post-roll

### Milestone 4: Laptop Decode + Tracking

Success means:

- laptop reconstructs clip plus metadata
- `YOLO -> SAM2` works on the standalone media path
- results are checked against the local `bowling_tests` set

### Milestone 5: Anchored Replay

Success means:

- tracked trajectory is projected into the locked lane frame
- replay payload returns over the same laptop result channel
- replay appears anchored on Quest in the intended place

## First Validation Rule

Every milestone should first be checked against:

- `C:\Users\student\QuestBowlingStandalone\data\bowling_tests`

We should not expand scope until the current milestone behaves sanely on the real Quest-captured data we already trust.
