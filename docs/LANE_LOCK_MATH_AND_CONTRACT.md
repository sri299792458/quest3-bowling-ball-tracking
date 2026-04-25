# Lane Lock Math And Data Contract

Last updated: 2026-04-25

This document defines the lane-lock contract for the standalone bowling product.

Lane selection is explicit. The system does not silently choose a lane.

## Product Rule

The user defines the lane by selecting the two foul-line lane edges:

- left lane edge at the foul line
- right lane edge at the foul line

The solver may snap, validate, and render an overlay, but lane identity comes from the user.

The session becomes lane locked only after a candidate overlay is shown and accepted.

## Required Quest Inputs

For the selected frame:

- image pixels
- `frameSeq`
- camera timestamp
- camera intrinsics: `fx`, `fy`, `cx`, `cy`, image width, image height
- camera pose in world: position and rotation
- head pose in world
- floor normal, expected to point upward
- two normalized image selections:
  - `leftFoulLinePointNorm`
  - `rightFoulLinePointNorm`

The selected points are normalized image coordinates in `[0, 1]`.

## Quest Selection Path

The shared Quest selector emits a world ray from the active hand/controller ray. Lane lock consumes that ray as follows:

1. intersect the ray with the current floor plane
2. project the floor hit point into the current passthrough camera frame
3. store the resulting normalized image coordinate

The first accepted selection is the left foul-line edge. The second accepted selection is the right foul-line edge. The code does not sort those points silently; if the second point is not to the right in image space, the request is rejected and the user must select again.

World point to image pixel:

```text
P_c = inverse(cameraRotationWorld) * (P_w - cameraPositionWorld)
u = fx * (P_c.x / P_c.z) + cx
v = cy - fy * (P_c.y / P_c.z)
pointNorm = [u / imageWidth, v / imageHeight]
```

The selection is rejected if the ray misses the floor, the projected point is behind the camera, or the normalized point falls outside `[0, 1]`.

## Coordinate Frames

Image frame:

- `u` grows rightward
- `v` grows downward

Camera frame:

- `x` right
- `y` up
- `z` forward

For pixel `(u, v)`:

```text
d_c_raw = [(u - cx) / fx, -(v - cy) / fy, 1]
d_c = normalize(d_c_raw)
```

World frame:

```text
o_w = cameraPositionWorld
d_w = cameraRotationWorld * d_c
```

So each selected pixel defines a world ray:

```text
P(t) = o_w + t * d_w
```

## Two-Point Foul-Line Solve

The selected left and right foul-line pixels give two world rays:

```text
d_left
d_right
```

The lane plane is assumed perpendicular to the upward floor normal `n_w`, but its exact offset can be solved from known lane width.

Let the unknown plane offset from the camera along `n_w` be `alpha`:

```text
n_w dot (X - o_w) = alpha
```

For each ray:

```text
t_left  = alpha / dot(n_w, d_left)
t_right = alpha / dot(n_w, d_right)

P_left  = o_w + t_left  * d_left
P_right = o_w + t_right * d_right
```

Choose `alpha` so the two intersections are exactly the regulation lane width apart:

```text
|P_right - P_left| = laneWidthMeters
```

This gives:

```text
scale = |d_right / dot(n_w, d_right) - d_left / dot(n_w, d_left)|
alpha = -laneWidthMeters / scale
```

The negative sign assumes the floor normal points upward and the lane is below the camera. The solution is rejected if either intersection is behind the camera.

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
  "selectionFrameSeq": 100,
  "leftFoulLinePointNorm": { "x": 0.40, "y": 0.66 },
  "rightFoulLinePointNorm": { "x": 0.72, "y": 0.63 },
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

The request is invalid without `selectionFrameSeq`, `leftFoulLinePointNorm`, and `rightFoulLinePointNorm`.

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
