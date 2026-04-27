# Lane Lock Math And Data Contract

Last updated: 2026-04-27

This document defines the lane-lock contract for the standalone bowling product.

Lane selection is explicit. The system does not silently choose a lane.

## Product Rule

The user defines the lane by selecting the two foul-line lane edges:

- left lane edge at the foul line
- right lane edge at the foul line

The solver may snap, validate, and render an overlay, but lane identity comes from the user.

The session becomes lane locked only after a candidate overlay is shown and accepted.

## Required Quest Inputs

For the live stream:

- image frames and per-frame metadata
- camera intrinsics: `fx`, `fy`, `cx`, `cy`, image width, image height
- camera pose in world per frame
- head pose in world per frame
- floor plane point and floor normal, expected to point upward

For lane selection:

- `leftSelectionFrameSeq`
- `rightSelectionFrameSeq`
- `leftFoulLinePointWorld`
- `rightFoulLinePointWorld`

The selected foul-line points are physical Quest-world floor intersections. They are not image pixels. This is the source of truth for lane calibration.

## Quest Selection Path

The shared Quest selector emits a world ray from the active hand/controller ray. Lane lock consumes that ray as follows:

1. intersect the ray with the current floor plane
2. store that floor hit as a Quest-world point
3. store the current frame sequence for audit/debugging

The first accepted selection is the left foul-line edge. The second accepted selection is the right foul-line edge. The code does not silently create a lane from pixels, image center, or automatic lane identity detection.

The selection is rejected if the ray misses the floor, points behind the user, or the two selected world points are effectively the same point.

## Coordinate Frames

Image frame:

- `u` grows rightward
- `v` grows downward

Camera frame:

- `x` right
- `y` up
- `z` forward

World frame:

Quest world is the common coordinate frame for both selected points and future camera poses. The lane lock remains valid only while that world frame remains continuous.

## Two-Point Foul-Line Solve

The selected foul-line endpoints are already in Quest world:

```text
P_left
P_right
```

Project both points onto the current floor plane to remove tiny ray/floor numerical error:

```text
P_projected = P - dot(P - floorPoint, n_w) * n_w
```

The selected width is:

```text
selectedWidth = |P_right - P_left projected onto floor|
```

The solve is rejected if the selected points are nearly coincident. The difference between `selectedWidth` and regulation `laneWidthMeters` becomes the selection agreement score; the solver does not invent a lane from image geometry to hide a bad selection.

## Lane Frame

The foul-line midpoint is the lane origin:

```text
O_w = 0.5 * (P_left + P_right)
```

The lane width axis is:

```text
u_w = normalize(P_right - P_left projected onto the lane plane)
```

The downlane axis is perpendicular to width and floor normal:

```text
s_w = normalize(u_w x n_w)
```

If `s_w` points opposite the user's head/camera forward direction, flip it.

Then re-orthogonalize:

```text
u_w = normalize(n_w x s_w)
```

The lane rectangle is:

```text
C0 = O_w - 0.5 * laneWidthMeters * u_w
C1 = O_w + 0.5 * laneWidthMeters * u_w
C2 = C1 + laneLengthMeters * s_w
C3 = C0 + laneLengthMeters * s_w
```

## Lane Lock Request

```json
{
  "schemaVersion": "lane_lock_request",
  "sessionId": "string",
  "requestId": "string",
  "frameSeqStart": 100,
  "frameSeqEnd": 124,
  "frameCount": 25,
  "captureDurationSeconds": 0.8,
  "leftSelectionFrameSeq": 100,
  "rightSelectionFrameSeq": 114,
  "leftFoulLinePointWorld": { "x": -0.52, "y": 0.0, "z": 0.0 },
  "rightFoulLinePointWorld": { "x": 0.52, "y": 0.0, "z": 0.0 },
  "laneWidthMeters": 1.0541,
  "laneLengthMeters": 18.288,
  "fx": 900.0,
  "fy": 900.0,
  "cx": 640.0,
  "cy": 480.0,
  "imageWidth": 1280,
  "imageHeight": 960,
  "floorPlanePointWorld": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "floorPlaneNormalWorld": { "x": 0.0, "y": 1.0, "z": 0.0 },
  "cameraSide": "Left"
}
```

The request is invalid without `leftSelectionFrameSeq`, `rightSelectionFrameSeq`, `leftFoulLinePointWorld`, and `rightFoulLinePointWorld`.

## Lane Lock Result

```json
{
  "schemaVersion": "lane_lock_result",
  "sessionId": "string",
  "requestId": "string",
  "success": true,
  "failureReason": "",
  "confidence": 0.92,
  "confidenceBreakdown": {
    "edgeFit": 0.80,
    "selectionAgreement": 1.0,
    "markingAgreement": 0.0,
    "temporalStability": 0.95,
    "candidateMargin": 1.0,
    "visibleExtent": 0.90
  },
  "lockState": "candidate_ready",
  "requiresConfirmation": true,
  "userConfirmed": false,
  "previewFrameSeq": 100,
  "laneOriginWorld": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "laneRotationWorld": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 },
  "laneWidthMeters": 1.0541,
  "laneLengthMeters": 18.288,
  "floorPlanePointWorld": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "floorPlaneNormalWorld": { "x": 0.0, "y": 1.0, "z": 0.0 },
  "visibleDownlaneMeters": 14.2,
  "releaseCorridor": {
    "sStartMeters": 0.0,
    "sEndMeters": 2.5,
    "halfWidthMeters": 0.45
  },
  "reprojectionMetrics": {
    "meanErrorPx": 9.6,
    "p95ErrorPx": 14.8,
    "runnerUpMargin": 1.0
  },
  "sourceFrameRange": {
    "start": 100,
    "end": 124
  }
}
```

## Ball Projection

For a tracked ball image point, build a camera ray using the same intrinsics and pose. Intersect that ray with the locked lane plane, then convert to lane coordinates:

```text
Delta = P_w - O_w
x_lane = dot(Delta, u_w)
s_lane = dot(Delta, s_w)
h_lane = dot(Delta, n_w)
```

The ball point is considered on the locked lane only if:

```text
abs(x_lane) <= laneWidthMeters / 2 + margin
0 <= s_lane <= visibleDownlaneMeters + margin
```

## Non-Goals

- no fully automatic lane identity selection
- no hidden fallback to view-center aim
- no silent acceptance of a lane candidate without user confirmation
