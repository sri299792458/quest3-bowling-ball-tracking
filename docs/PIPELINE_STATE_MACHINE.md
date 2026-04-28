# Pipeline State Machine

Last updated: 2026-04-27

This document describes the current pipeline state machine as implemented, why it feels random, and the target redesign.

The goal is not to add more fallbacks.
The goal is to make the product run from one explicit state model where every transition has an owner, an event, and a durable record.

## First Principles

The product has one user-visible job:

1. start a continuous Quest-to-laptop session stream
2. let the user explicitly lock the physical lane
3. arm shot detection only after lane lock is confirmed
4. use YOLO to seed one shot at a time
5. track that shot immediately with live camera SAM2
6. project the ball track into the confirmed lane frame
7. return replay results to Quest
8. let the user pick from a growing shot replay list

Anything that does not support that flow should be invisible or removed.

The main rule:

```text
No downstream stage runs on ambiguous upstream state.
```

Practical meaning:

- no shot detection until the lane is confirmed
- no replay until the shot result is projected through a confirmed lane lock
- no "Lock Lane" success state until Quest has received and accepted a lane-lock result
- no silent interpretation of old schemas or partial state
- no UI label pretending an operation is done when the operation is merely queued

## Current State Machine

There is no single current state machine.
The implemented state is spread across Quest components, laptop receiver files, laptop polling state, and result messages.

### Current Quest Transport State

Owner:

- `StandaloneQuestSessionController`
- `StandaloneQuestLocalProofCapture`
- `StandaloneQuestLiveMetadataSender`
- `StandaloneQuestLiveResultReceiver`

Current implicit states:

```text
Disabled
  -> StartupDelay
  -> DiscoveringLaptop
  -> BeginSessionRetryLoop
  -> CaptureStarted
  -> MediaStreamStarted
  -> MetadataStreamStarted
  -> ResultStreamStarted
  -> SessionActive
  -> Finalized

Any active state
  -> Aborted
```

Current transition triggers:

- `OnEnable` starts a coroutine after `startupDelaySeconds`
- laptop discovery either fills host/ports or stops startup
- `TryBeginSession` starts capture, media stream, metadata stream, and result receiver
- `OnDisable`, `OnDestroy`, app quit, and app pause abort the session

Current problems:

- `_sessionActive` is only local to `StandaloneQuestSessionController`
- media, metadata, and result channels can fail independently, but there is no explicit `Degraded` state
- Quest UI does not have one authoritative session state to render
- the same `shot_id` is currently used as a stream id for the continuous session
- there is no explicit "laptop is connected and ready for analysis" state

### Current Quest Lane-Lock State

Owners:

- `StandaloneQuestLaneLockButton`
- `StandaloneQuestFoulLineRaySelector`
- `StandaloneQuestLaneLockCapture`
- `StandaloneQuestLaneLockResultRenderer`

Current implicit states:

```text
NoSelection
  -> SelectingLeftFoulLinePoint
  -> SelectingRightFoulLinePoint
  -> FoulLineSelectionReady
  -> LaneLockRequestActive
  -> LaneLockRequestSent
  -> WaitingForLaneLockResult
  -> LaneVisualizationRendered
```

Current transition triggers:

- pressing `Lock Lane` starts foul-line selection if no selection exists
- first ray click becomes the left foul-line point
- second ray click becomes the right foul-line point
- pressing `Lock Lane` again sends a `lane_lock_request`
- laptop returns `lane_lock_result`
- Quest renders the lane overlay when the result succeeds

Current problems:

- older builds let button text do state-machine work through transient labels
- the low-level selector and request sender still expose independent booleans, but the coordinator now owns the visible lane state
- the lane-lock result is visualized as a candidate and must be explicitly accepted or retried
- `lane_lock_confirm` now exists, and the current UI has explicit accept/retry controls
- laptop no longer treats the latest successful lane-lock result as usable immediately

### Current Laptop Receiver State

Owner:

- `live_stream_receiver.py`

Current implicit states per `(session_id, shot_id)`:

```text
NoDirectory
  -> DirectoryCreated
  -> MediaSessionStartSeen
  -> CodecConfigSeen
  -> MediaSamplesAppending
  -> MetadataSessionStartSeen
  -> FrameMetadataAppending
  -> LaneLockRequestsAppending
  -> ShotBoundariesAppending
  -> OutboundResultsAppending
  -> SessionEndSeen
```

Current transition triggers:

- media channel `session_start` creates or opens a session directory
- metadata channel can also create or open the same session directory
- media samples append to `stream.h264`
- metadata messages append to `metadata_stream.jsonl`
- lane-lock request messages also append to `lane_lock_requests.jsonl`
- shot-boundary messages also append to `shot_boundaries.jsonl`
- local analysis publishes result envelopes to `127.0.0.1:8770`
- result hub appends to `outbound_results.jsonl` and broadcasts to Quest clients

Live session identity invariant:

- there is one live session per Quest app run
- closing/killing/reopening the Quest app creates a new `session_id`
- live runs should first disable proximity sleep with `adb shell am broadcast -a com.oculus.vrpowermanager.prox_close`
- after that preflight, briefly removing the headset should not pause the app
- `session_id` identifies the current Quest calibration/session epoch
- `shot_id` stays `session-stream` for the continuous live feed
- `frameSeq` must be monotonic inside one `(session_id, shot_id)` stream and must not reset on brief pause/resume
- if the app pauses anyway, is killed, the camera/encoder is rebuilt from zero, or Quest relocalizes the tracking origin, lane lock must be treated as invalid and the user must relock
- media and metadata `session_start` messages for the same `(session_id, shot_id)` must land in the same directory
- old stream artifacts stay on disk for debugging; they are not reused after a true app/session restart
- the live pipeline processes only the latest live stream by default; older streams require an explicit `--session-dir`

Current problems:

- session readiness is inferred from files, not an explicit session state
- media and metadata can race each other
- the result publish endpoint only knows active in-memory sessions
- if the receiver restarts, persisted sessions exist but result publish cannot target them unless recreated in memory
- no durable "transport healthy/degraded/ended" state exists

### Current Laptop Analysis State

Owner:

- `live_session_pipeline.py`

Current implicit states:

```text
SessionDiscovered
  -> NewLaneLockRequestSeen
  -> LaneLockRequestProcessed
  -> LaneLockResultPublished
  -> AutoShotBoundaryScan
  -> CompletedShotWindowSeen
  -> ShotWindowProcessed
  -> ShotResultPublished
```

Durable state today:

```text
analysis_live_pipeline/pipeline_state.json
  processedLaneLockRequests: requestId -> status
  processedShotWindows: windowId -> status
```

Current transition triggers:

- polling loop discovers `live_*` directories
- unprocessed lane-lock requests are solved once
- shot detector scans frames if configured
- completed shot windows are tracked once
- results are published to the live receiver

Current problems:

- pipeline state records what was processed, not what state the session is in
- lane lock has no candidate/confirmed distinction
- shot detection can be configured, but the pipeline does not own an explicit "armed" state
- shot-boundary detector has its own separate state file
- shot tracking has per-window outputs, but no session-level shot lifecycle
- errors are printed in summaries, not represented as recoverable states

### Current Shot State

Owners:

- `LiveShotBoundaryDetector`
- `live_shot_boundaries.py`
- `live_shot_tracking_stage.py`
- Quest replay list

Current implicit states:

```text
WaitingForLaneLock
  -> ScanningFrames
  -> ShotStartEmitted
  -> ShotEndEmitted
  -> CompletedWindow
  -> YOLOSeeded
  -> SAM2Tracked
  -> LaneProjected
  -> ShotResultPublished
  -> QuestReplayListAdded
```

Current problems:

- shot boundary detection is file-output driven, not state-output driven
- open shot state is inferred from `shot_boundaries.jsonl`
- a failed shot result does not become an explicit user-visible shot state unless no previous replay exists
- replay numbering is Quest-local list order, while laptop window ids are frame ranges
- a lane-lock change does not explicitly invalidate future shot state

## Why Random Things Are Happening

The current design lets multiple components decide what phase we are in.
They are all locally reasonable, but globally incoherent.

Examples:

- the lane button says "Lock Lane" because its transient status expired, even though the selector or laptop may still be in a meaningful state
- lane overlay can render from a successful result even though no user confirmation was captured
- shot detection previously depended on "latest successful lane-lock file," not "confirmed session lane"
- receiver readiness is inferred by whether files and sockets happen to exist
- result delivery depends on active result clients and in-memory receiver registry state
- replay list state is only Quest-local and not tied to an explicit shot lifecycle

The fix is an explicit state model, not more conditional UI messages.

## Target Redesign

Use one product-level state machine made of four orthogonal regions:

1. transport state
2. lane state
3. shot state
4. replay state

These regions are allowed to move independently, but transitions between them must be explicit.
For example, shot state cannot move from `Disabled` to `Armed` until lane state is `Confirmed`.

## Target Transport State

Owner:

- Quest session coordinator owns the Quest-side state
- laptop live receiver owns the laptop-side persisted state

States:

```text
Transport.Offline
Transport.DiscoveringLaptop
Transport.Connecting
Transport.Streaming
Transport.Degraded
Transport.Ending
Transport.Ended
Transport.Failed
```

Transitions:

```text
Offline
  -- app enabled -->
DiscoveringLaptop
  -- discovery ok -->
Connecting
  -- media + metadata + result connected -->
Streaming
  -- one non-critical channel drops -->
Degraded
  -- channel recovers -->
Streaming
  -- user/app/session end -->
Ending
  -- session_end persisted -->
Ended

Any non-ended state
  -- unrecoverable required channel failure -->
Failed
```

Required durable evidence:

- Quest has an in-memory `TransportState`
- laptop writes `session_state.json`
- laptop records `mediaStarted`, `metadataStarted`, `codecConfigSeen`, `firstFrameSeen`, `lastFrameSeq`, `resultClients`

## Target Lane State

Owner:

- Quest owns user selection and final acceptance
- laptop owns solving and candidate result
- confirmed lane is a shared session fact

States:

```text
Lane.Unknown
Lane.SelectingLeftFoulLine
Lane.SelectingRightFoulLine
Lane.SelectionReady
Lane.RequestQueued
Lane.Solving
Lane.CandidateReceived
Lane.Confirmed
Lane.Rejected
Lane.Failed
Lane.RelockRequired
```

Transitions:

```text
Unknown
  -- user presses Lock Lane -->
SelectingLeftFoulLine
  -- left point accepted -->
SelectingRightFoulLine
  -- right point accepted -->
SelectionReady
  -- request auto-sent -->
RequestQueued
  -- laptop starts processing -->
Solving
  -- lane_lock_result success -->
CandidateReceived
  -- user accepts overlay -->
Confirmed
  -- user rejects overlay -->
Rejected
  -- user restarts selection -->
SelectingLeftFoulLine

RequestQueued or Solving
  -- lane_lock_result failure -->
Failed

Confirmed
  -- user requests relock or confidence invalid -->
RelockRequired
```

Important rule:

```text
Lane.CandidateReceived is not Lane.Confirmed.
```

The laptop may show a result. Quest must accept it before shot detection is armed.

Required protocol event:

```text
lane_lock_confirm
  requestId
  accepted
  reason
```

Required laptop behavior:

- store candidate lane results
- mark one candidate as confirmed only after `lane_lock_confirm accepted=true`
- shot detection and shot projection use `load_confirmed_lane_lock`
- shot detector waits for confirmed lane

## Target Shot State

Owner:

- laptop analysis owns shot detection and tracking
- Quest only displays status and replay results

States:

```text
Shot.DisabledUntilLaneConfirmed
Shot.Armed
Shot.StartCandidate
Shot.Open
Shot.EndCandidate
Shot.WindowComplete
Shot.Analyzing
Shot.ResultReady
Shot.ResultFailed
```

Transitions:

```text
DisabledUntilLaneConfirmed
  -- Lane.Confirmed -->
Armed
  -- YOLO ball in release corridor -->
StartCandidate
  -- downlane confirmation -->
Open
  -- terminal region or sustained lost track or max duration -->
EndCandidate
  -- post-roll captured -->
WindowComplete
  -- tracking stage starts -->
Analyzing
  -- shot_result success -->
ResultReady
  -- shot_result failure -->
ResultFailed
  -- result published -->
Armed
```

Rules:

- one open shot at a time
- nested `shot_start` is invalid
- unmatched `shot_end` is invalid
- every completed window gets exactly one durable result record
- failed shot results are real results and should be visible enough to debug, but they should not pollute the replay list as playable shots

## Target Replay State

Owner:

- Quest replay UI owns display state
- laptop owns result payload correctness

States:

```text
Replay.Empty
Replay.HasResults
Replay.Playing
Replay.Complete
Replay.Unavailable
```

Transitions:

```text
Empty
  -- first successful shot_result -->
HasResults
  -- user selects shot_N -->
Playing
  -- replay reaches end -->
Complete
  -- user selects another shot -->
Playing

Any replay state
  -- selected shot result has no trajectory -->
Unavailable
```

Rules:

- Quest labels playable successful results as `Shot 1`, `Shot 2`, ...
- laptop keeps stable `windowId` for traceability
- Quest list order is display order, not identity
- replay should only render trajectories that were projected through the confirmed lane lock used for that shot

## Target Durable State Files

Each live session should have one authoritative state file:

```text
session_state.json
```

Suggested top-level shape:

```json
{
  "schemaVersion": "quest_bowling_session_state_v1",
  "sessionId": "...",
  "streamId": "...",
  "transport": {
    "state": "Streaming",
    "codecConfigSeen": true,
    "lastFrameSeq": 1234
  },
  "lane": {
    "state": "Confirmed",
    "activeRequestId": "...",
    "confirmedRequestId": "...",
    "candidateResultPath": "...",
    "confirmedResultPath": "..."
  },
  "shot": {
    "state": "Armed",
    "openWindowId": "",
    "completedWindowCount": 2
  },
  "replay": {
    "successfulShotCount": 2,
    "latestWindowId": "shot_100_220"
  }
}
```

Current per-stage state files can still exist, but they should become implementation details.
The session state file is the thing humans and UI code reason about.

## Target Event Log

Keep append-only logs, but make them event logs rather than hidden state:

```text
metadata_stream.jsonl
lane_lock_requests.jsonl
lane_lock_confirms.jsonl
shot_boundaries.jsonl
outbound_results.jsonl
pipeline_events.jsonl
```

Every transition should be explainable from either:

- a Quest input event
- a laptop analysis event
- a transport event
- a result event

## Redesign Plan

### Step 1: Write This State Machine

Status: complete.

Outcome:

- current implicit states are documented
- target states are named
- no code behavior changes yet

### Step 2: Add Shared State Names

Status: in progress.

Add explicit enums/constants for:

- transport state
- lane state
- shot state
- replay state

Use the same names in docs, Python, and Unity.

No UI logic should invent labels from raw notes after this.
Raw notes are diagnostics, not product state.

### Step 3: Add Laptop `session_state.json`

Status: complete for the laptop receiver and live pipeline.

Add a small state writer on the laptop receiver/pipeline side.

It should update:

- transport state when sessions are created, media starts, metadata starts, codec config arrives, and session ends
- lane state when requests are seen, solving starts, candidates arrive, confirmation arrives
- shot state when detector arms, starts, opens, completes, analyzes, succeeds, or fails
- replay counters when results are published

This is the first practical debugging win.
We should be able to inspect one file and know what the pipeline thinks is happening.

### Step 4: Create One Quest Lane Coordinator

Status: complete for lane lock.

Added a Quest-side lane coordinator that subscribes to:

- lane selector
- lane request sender
- result receiver

It owns the displayed product state.

Existing components can still do low-level work, but they stop competing to decide the user-facing state.

The lock-lane button no longer parses raw notes or owns lane state. It only displays the coordinator's primary label and invokes the coordinator's primary action.

### Step 5: Implement Lane Confirmation

Status: complete.

Implemented:

- Quest can send `lane_lock_confirm`
- laptop persists `lane_lock_confirms.jsonl`
- laptop marks accepted candidates as `Lane.Confirmed`
- Quest shows explicit `Accept Lane` and `Retry Lane` actions for a candidate
- Quest auto-submits the lane-lock request after the right foul-line edge is selected
- `Retry Lane` sends `lane_lock_confirm accepted=false` for that candidate before starting selection again
- Quest relock sends `lane_lock_confirm accepted=false` for the previous confirmed request before allowing reselection
- laptop marks rejected/relocked lanes as `Lane.Rejected`, clears the confirmed request, and disables shot detection
- shot detection and shot projection require a confirmed lane

Add `lane_lock_confirm` for the real product state:

```text
CandidateReceived -- user accepts --> Confirmed
CandidateReceived -- user retries --> Rejected --> SelectingLeftFoulLine
```

This is the most important correctness change.

### Step 6: Gate Shot Detection On Confirmed Lane

Status: complete.

The shot detector now:

- if no confirmed lane, state is `Shot.DisabledUntilLaneConfirmed`
- if confirmed lane exists, state becomes `Shot.Armed`
- pending release evidence becomes `Shot.StartCandidate`
- an emitted `shot_start` becomes `Shot.Open`
- a paired `shot_start` / `shot_end` becomes `Shot.WindowComplete`
- each shot boundary carries the confirmed `laneLockRequestId`
- shot projection uses the window's `laneLockRequestId`, not whichever lane is latest

This prevents shot windows from being generated against a lane model the user has not accepted.

### Step 7: Make Shot Lifecycle Durable

Status: complete for the laptop session state.

Extend laptop pipeline state from "processed windows" to actual shot lifecycle:

- current open shot
- candidate start evidence
- completed windows
- analysis status per window
- published status per result

Keep the current strict `shot_boundaries.jsonl` parser.
It is good.
The lifecycle is now visible in `session_state.json`; the per-stage detector state remains an implementation detail.

### Step 8: Make Quest Replay UI Consume Product State

The replay list should only grow on successful replayable `shot_result`.

Failed results should update a status surface, not silently disappear and not become playable shots.

The list should display:

```text
Shot 1
Shot 2
Shot 3
```

Internally each entry keeps:

- `windowId`
- `laneLockRequestId`
- source frame range
- result receive time

### Step 9: Remove Competing Old State

After the coordinator and laptop session state exist:

- remove transient lane-button state guessing
- remove any direct "latest successful lane lock means locked" use
- remove UI-driven state transitions that are not backed by explicit events
- keep diagnostic notes only as diagnostics

## Immediate Coding Order

I would implement in this order:

1. laptop `session_state.json` writer and reader
2. explicit state constants in Python
3. explicit state constants in Unity
4. Quest coordinator that renders state without changing existing low-level behavior
5. `lane_lock_confirm` metadata event from Quest
6. laptop confirmed-lane loader
7. gate shot detector on confirmed lane
8. replay list/status cleanup

This order gives us visibility first, then correctness.

## Acceptance Criteria

We are done with this redesign when the following are true:

- one file says whether the session is streaming, lane is confirmed, shot is armed/open/analyzing, and replay is ready
- the Quest UI cannot show `Lock Lane` while a lane candidate is waiting for acceptance
- the laptop cannot run shot detection before confirmed lane lock
- every shot result can be traced back to one confirmed lane lock
- every user-visible state maps to one documented state, not a status string guess
- restarting the laptop analysis process does not lose the durable understanding of processed requests/windows

## Current Recommendation

Do not add more hidden transitions or UI-only interpretations.

The next code slice should be Quest validation:

```text
Build/install, run a live session, and verify lane accept/retry plus Shot 1 / Shot 2 replay growth in headset.
```

Everything else should continue to obey `session_state.json`, `lane_lock_confirms.jsonl`, and the confirmed-lane gate.
