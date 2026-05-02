# Live VR Experience And Analytics Spec

This is the product and pipeline spec for the final live Quest bowling experience.

The north star is:

```text
SPECTO-style bowling analysis, anchored directly on the real lane in the headset.
```

This is not a debug UI. The headset should feel like a calm bowling assistant: lock the lane, bowl normally, then see a replay and useful stats where the shot actually happened.

## Goals

- Make the physical lane the primary interface.
- Keep the bowler's shot view clean while they are preparing and throwing.
- Return a replay that is spatially anchored to the real lane.
- Show bowling stats that can be defended from the current trajectory data.
- Keep every successful shot replayable in the headset.
- Build a session review view that helps the bowler improve consistency.

## Non-Goals

- Do not show pipeline internals in the headset.
- Do not expose raw failure strings such as `sam2_tracking_failed` to the bowler.
- Do not estimate RPM, axis rotation, axis tilt, pinfall, or carry until the sensing supports it.
- Do not add runtime bypasses for missing lane lock or missing trajectory data.
- Do not bring back old dev injection, desktop lane drawing, or fallback trajectory heuristics.

## Product Principles

### 1. The Lane Is The UI

The most important visual information is drawn on the lane itself:

- lane calibration preview
- ready/armed lane state
- replay trajectory
- replay milestones
- dynamic stat callouts

Floating panels are secondary and should live off the bowler's shot line.

### 2. The Throw View Must Stay Quiet

Before and during a throw, the bowler should see almost nothing:

- no debug text
- no model logs
- no transport status spam
- no shot list blocking the lane
- no moving UI except the real bowling ball

The UI may show a tiny peripheral `Ready` state, but it should not compete with the bowler's focus.

### 3. Stats Must Be Honest

A stat is shown only if it follows directly from:

- confirmed lane geometry
- smoothed lane-space trajectory
- frame timing
- projection confidence
- SAM2 mask quality

If a value cannot be defended, the UI should omit it instead of guessing.

### 4. The Headset Shows Product State, The Laptop Shows Debug State

The Quest UI shows:

- `Needs Lane`
- `Preview Lane`
- `Ready`
- `Tracking`
- `Replay`
- `Needs Attention`

The laptop can show:

- socket state
- YOLO frame counts
- SAM2 timings
- file paths
- raw error reasons

The headset should not mirror the laptop console.

## High-Level User Flow

### 1. Preflight

Operator starts the laptop pipeline and disables proximity sleep before the bowling session.

Quest discovers the laptop and starts one continuous live session stream:

```text
Quest H.264 media stream
Quest frame metadata stream
Laptop result stream back to Quest
```

User-visible headset state:

```text
Connecting -> Needs Lane
```

### 2. Lane Lock

The user pinches and holds while looking down the lane.

Quest shows only the heads-region placement rectangle. On pinch release, Quest shows the full lane preview.

User-visible states:

```text
Needs Lane
  -> Placing Lane
  -> Preview Lane
  -> Ready
```

Rules:

- Confirming the lane sends the complete `lane_lock_result` to the laptop.
- The laptop persists that lane result as the confirmed session geometry.
- Shot detection is armed only after the laptop has a confirmed lane.
- Relocking invalidates shot detection until the new lane is confirmed.

### 3. Ready To Bowl

Once the lane is locked:

- the full lane overlay fades down
- optional subtle lane rails remain visible
- a small side/peripheral status shows `Ready`

The bowler should be able to ignore the UI and bowl normally.

### 4. Shot Detection And Tracking

Laptop detects a shot start from YOLO inside the confirmed lane/release corridor, then immediately starts live camera SAM2 tracking.

SAM2 writes live mask measurements and compact contours. The final trajectory is reconstructed from the original live SAM2 mask measurements, not from a later SAM rerun.

User-visible headset state:

```text
Ready -> Tracking
```

During `Tracking`, the headset should only show a small peripheral pulse or label. It should not render live model detections.

### 5. Replay

When a successful `shot_result` arrives, Quest:

1. adds the shot to the shot list
2. renders the trajectory line on the lane
3. animates a ball marker along the trajectory
4. reveals dynamic stat callouts at the relevant lane positions
5. ends with a compact summary card

User-visible state:

```text
Tracking -> Replay Available
```

### 6. Session Review

After multiple shots, the user can open a session review panel.

This view focuses on consistency:

- speed average and spread
- entry board average and spread
- entry angle average and spread
- breakpoint board and distance spread
- best shot vs current shot comparison
- optional ghost trajectory overlay

## Quest UI Surfaces

### 1. Floor Overlay

World anchored to the real lane.

Responsibilities:

- heads-region placement preview
- full-lane confirmation preview
- subtle locked-lane rails
- shot trajectory line
- breakpoint marker
- entry marker
- optional ghost trajectory

Design:

- calibration preview: amber
- locked lane rails: low-alpha cyan or green
- current replay trajectory: bright cyan
- selected/previous ghost: thin dim gray-blue
- marker ball: warm yellow/orange

The lane overlay must never obscure the physical lane enough to distract a bowler.

### 2. Side Status Strip

Small peripheral panel mounted away from the shot line, preferably near the ball-return side.

Shows only product state:

```text
Laptop
Models
Lane
Ready
```

Each item is a compact indicator, not a log line.

Examples:

```text
Laptop  Connected
Models  Ready
Lane    Locked
Shot    Ready
```

Failure examples:

```text
Laptop  Reconnecting
Lane    Relock Needed
Shot    Ball Not Found
```

### 3. Dynamic Replay Callouts

Callouts appear one at a time during replay and anchor near the relevant trajectory point.

Replay sequence:

```text
Early lane:      Speed
Arrows:          Arrows board
Breakpoint:      Breakpoint board + distance
Entry zone:      Entry board + entry angle + entry speed
End:             Compact shot summary
```

Callouts should be short:

```text
17.8 mph
```

```text
Arrows 14.8
```

```text
Breakpoint
8.4 @ 42 ft
```

```text
Entry
17.2 board · 4.6 deg
```

Only one or two callouts should be visible at once.

### 4. Shot Rail

A compact replay list near the side status strip.

Each successful shot becomes replayable:

```text
Shot 6   17.8 mph   4.6 deg   Bkpt 8.4
Shot 5   18.1 mph   3.9 deg   Bkpt 9.1
Shot 4   17.5 mph   5.0 deg   Bkpt 7.8
```

Tapping a shot:

- selects that shot
- rerenders the lane trajectory
- replays the dynamic callouts

The shot rail should show the latest few shots by default. Session review can expose the full list later.

### 5. Session Review Card

Opened intentionally, never shown automatically while preparing to throw.

Shows consistency rather than raw volume:

```text
Speed Avg       17.8 mph
Speed Spread    +/- 0.4 mph

Entry Board     17.1 avg
Entry Spread    +/- 1.2 boards

Entry Angle     4.5 deg avg
Angle Spread    +/- 0.6 deg

Breakpoint      8.6 @ 41 ft
Bkpt Spread     +/- 1.5 boards
```

Later extension:

- best shot marker
- current vs previous ghost
- last 3 trend
- manual outcome tags such as strike, pocket, miss left, miss right

## User-Visible State Model

Add a Quest presentation owner:

```text
StandaloneQuestExperiencePresenter
```

It owns only user-facing experience state:

```text
Connecting
NeedsLane
PlacingLane
PreviewLane
Ready
Tracking
ReplayAvailable
SessionReview
NeedsAttention
```

It listens to pipeline producers:

- session controller
- lane lock coordinator
- live result receiver
- shot replay list
- shot replay renderer

It drives UI presenters:

- `LaneOverlayPresenter`
- `SessionStatusPresenter`
- `ShotReplayPresenter`
- `ShotStatsPresenter`
- `ShotRailPresenter`
- `SessionReviewPresenter`

Pipeline components continue to own transport, capture, lane lock, tracking, and result parsing. The experience presenter translates those states into bowler-facing UI.

## Shot Result Contract

Successful `shot_result` payloads should include:

```json
{
  "schemaVersion": "shot_result",
  "sessionId": "...",
  "shotId": "...",
  "success": true,
  "trackingSummary": {},
  "trajectory": [],
  "shotStats": {}
}
```

`shotStats` is required for successful replayable shots once this feature lands.

### Shot Stats Schema

```json
{
  "schemaVersion": "shot_stats_v1",
  "pointDefinition": "lane_space_trajectory_stats_v1",
  "laneLengthMeters": 18.288,
  "laneWidthMeters": 1.0541,
  "boardCount": 39,
  "trajectoryCoverage": {
    "startSFeet": 10.7,
    "endSFeet": 60.0,
    "trackedDistanceFeet": 49.3,
    "coverageConfidence": 0.91
  },
  "speed": {
    "averageMph": 17.8,
    "earlyMph": 18.4,
    "entryMph": 15.2,
    "speedLossMph": 3.2,
    "hasEntrySpeed": true
  },
  "positions": {
    "arrowsBoard": 14.8,
    "breakpointBoard": 8.4,
    "breakpointDistanceFeet": 42.0,
    "entryBoard": 17.2,
    "boardsCrossed": 8.8
  },
  "angles": {
    "launchAngleDegrees": 2.1,
    "entryAngleDegrees": 4.6,
    "breakpointAngleDegrees": 6.7
  },
  "milestones": []
}
```

Fields may be hidden in the UI when their availability or confidence is poor, but the laptop should persist enough information for debugging.

### Replay Milestones

Milestones let Quest reveal dynamic callouts without recomputing bowling math:

```json
{
  "kind": "breakpoint",
  "label": "Breakpoint",
  "frameSeq": 2441,
  "sMeters": 12.8,
  "xMeters": 0.31,
  "board": 8.4,
  "distanceFeet": 42.0,
  "normalizedReplayTime": 0.62,
  "primaryValue": "8.4 @ 42 ft"
}
```

Required milestone kinds:

- `early_speed`
- `arrows`
- `breakpoint`
- `entry`
- `summary`

Quest may use the rendered trajectory sample time instead of `normalizedReplayTime`, but the normalized value makes the UI simple and consistent.

## Stat Definitions

Lane coordinates:

- `sMeters`: distance from foul line toward pins
- `xMeters`: lateral distance from lane center
- `xMeters > 0`: bowler's right side of the lane
- lane length: `18.288 m` / `60 ft`
- lane width: `1.0541 m`
- boards: `39`

Board number from lane `x`:

```text
boardWidthMeters = laneWidthMeters / 39
board = ((laneWidthMeters * 0.5 - xMeters) / boardWidthMeters) + 0.5
```

This makes board `1` the right edge board and board `39` the left edge board from the bowler's perspective. Lane center is board `20`.

Distance points:

- arrows: `15 ft`
- entry board: `59.5 ft`
- entry/impact angle segment: preferably `57 ft` to `59.5 ft`
- launch/early angle segment: first reliable `10 ft` of tracked path, or omitted if coverage starts too late

Speed:

- compute from lane-space path distance over frame PTS time
- average speed uses all reliable trajectory points
- early speed uses the first reliable early segment
- entry speed uses the entry segment only when enough real trajectory points exist there
- speed loss is `earlyMph - entryMph` only when both are available

Breakpoint:

- breakpoint is the trajectory point with the maximum lateral excursion from lane center
- breakpoint board and breakpoint distance come from that point
- gutter/edge shots keep their real endpoint and are not dragged to the pins

Angles:

- angle is `atan2(deltaX, deltaS)` in degrees
- positive angle means movement toward bowler's right
- UI may show absolute entry angle unless handedness-specific interpretation is added

## Session Stats Contract

The Quest can compute simple in-memory session stats from received `shotStats`.

The laptop may later publish a durable `session_stats` result:

```json
{
  "schemaVersion": "session_stats_v1",
  "sessionId": "...",
  "successfulShotCount": 12,
  "speed": {
    "averageMph": 17.8,
    "stdDevMph": 0.4
  },
  "entry": {
    "averageBoard": 17.1,
    "stdDevBoards": 1.2,
    "averageAngleDegrees": 4.5,
    "stdDevAngleDegrees": 0.6
  },
  "breakpoint": {
    "averageBoard": 8.6,
    "stdDevBoards": 1.5,
    "averageDistanceFeet": 41.0,
    "stdDevDistanceFeet": 2.2
  }
}
```

Session stats are for improvement:

- repeatability
- trend
- dispersion
- comparison

They are not a scoreboard.

## Laptop Responsibilities

The laptop owns:

- receiving continuous H.264 media
- receiving frame metadata
- receiving confirmed lane geometry
- detecting shot starts with YOLO
- tracking shots with live camera SAM2
- reconstructing lane-space trajectory
- computing `shotStats`
- emitting replay milestones
- publishing `shot_result`
- persisting artifacts for debugging

The laptop must not:

- invent trajectory without a confirmed lane
- rerun SAM for final trajectory if live SAM measurements already exist
- publish user-facing stats that are not supported by the data

## Quest Responsibilities

Quest owns:

- passthrough camera capture and encoding
- frame pose/timestamp metadata
- lane placement and confirmation UX
- result reception
- lane-anchored replay rendering
- dynamic stat callouts
- shot rail
- in-memory session review

Quest must not:

- recompute core stats from raw trajectory unless only formatting is needed
- show low-level laptop pipeline state to the bowler
- keep stale lane/replay visuals after relock or session restart

## Failure Presentation

Raw failure reasons stay in logs. The bowler sees short action-oriented labels.

Mapping examples:

```text
laptop disconnected       -> Laptop Reconnecting
lane missing              -> Lock Lane First
yolo detection failed     -> Ball Not Found
sam2 tracking failed      -> Track Lost
empty trajectory          -> Replay Unavailable
lane relock required      -> Relock Lane
```

The UI should avoid blame language. It should tell the user what to do next.

## Implementation Phases

### Phase 1: Stats Contract

- Add `ShotStats` Python dataclasses.
- Add C# `StandaloneShotStats` types.
- Add `shotStats` to successful `shot_result`.
- Compute stats from final lane-space trajectory.
- Write unit/contract tests against the three saved shots.

### Phase 2: Shot Rail Upgrade

- Replace shot buttons that only say `Shot N`.
- Show compact stats per shot.
- Preserve tap-to-replay behavior.
- Keep latest shots visible by default.

### Phase 3: Dynamic Replay Callouts

- Add milestone callout rendering to Quest replay.
- Show one callout at a time.
- Anchor callouts near lane-space milestone positions.
- Collapse to compact summary after replay.

### Phase 4: Experience Presenter

- Add `StandaloneQuestExperiencePresenter`.
- Move user-facing labels out of individual pipeline components.
- Keep pipeline components as producers.
- Centralize bowler-facing state transitions.

### Phase 5: Session Review

- Aggregate received shot stats in Quest memory.
- Add intentional session review panel.
- Add averages and spreads.
- Add selected shot vs previous shot ghost overlay.

Implemented surface:

- `StandaloneQuestSessionReviewPanel` opens only from the `Review` button.
- It shows session averages/spreads, selected shot details, selected-vs-previous deltas, most-repeatable shot, and last-3 trends.
- `StandaloneQuestShotReplayRenderer` draws a dim previous-shot ghost trajectory while review is open.

## Validation

Before calling this product-ready:

- the three existing live shots must produce stable `shotStats`
- pin-hit shots must report entry stats near the pin deck
- gutter/edge shots must not be forced to pin-deck stats
- shot rail must remain readable with at least 10 shots received
- replay callouts must not block the physical lane during setup or throw
- relocking the lane must clear stale trajectory and stale session stats
- Quest app restart must create a new session with no old shot rail carryover

## Final Product Shape

The intended loop is:

```text
Lock the lane once.
Bowl normally.
Watch the replay on the real lane.
See a few meaningful stats.
Replay any shot.
Review consistency across the session.
```

That is the product. Everything else is implementation support.
