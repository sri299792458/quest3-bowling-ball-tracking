# Live Trajectory Reconstruction

This is the final live replay trajectory path. The replay trajectory is reconstructed from the live SAM2 masks, not from YOLO boxes and not from SAM bbox bottom.

## Inputs

- A confirmed lane lock with world-space lane basis and floor plane.
- A completed shot window from live shot detection.
- The live SAM2 camera tracker output for that shot.
- Per-frame Quest camera pose and intrinsics from `metadata_stream.jsonl`.

## Live SAM2 Output Contract

During the original live SAM2 pass, each tracked frame must persist:

- bbox, centroid, and area
- mask top-quantile point
- final mask measurement point
- compact largest contour points for debugging and future fitting

The final measurement point is a blend of the mask top-quantile point and mask centroid. This intentionally replaces the older bbox-bottom contact proxy.

The mask itself is not rerun from `stream.h264` later. Rerunning SAM from raw H.264 can diverge from the original live tracker state, so the live pass is the source of truth.

## Measurement Model

For each present SAM frame:

1. Read `mask_measurement_x`, `mask_measurement_y`.
2. Project that image point through the per-frame Quest camera pose onto the locked lane plane.
3. Store a lane-space measurement:
   - `x`: lateral lane coordinate
   - `s`: downlane coordinate
   - confidence from lane projection and mask quality

Mask-size depth is deliberately not used. Experiments showed equivalent-radius and enclosing-circle depth estimates under-shoot badly because SAM mask area is not a stable physical apparent radius.

## Smoother

The replay trajectory is produced by a lane-space Kalman filter plus RTS smoother with state:

```text
[x, s, vx, vs]
```

The model assumes:

- `s` is nondecreasing
- `vs` is normally positive
- `x` changes smoothly
- far-downlane `s` measurements are noisier than near-lane measurements
- small or degraded masks are less trustworthy

After smoothing:

- `s` is clamped to `[0, laneLength]`
- `s` is made nondecreasing
- short terminal prediction is allowed only when the ball is centered enough and already near the pin deck
- edge/gutter trajectories are not dragged to the pins

## Output

The shot result trajectory remains a list of `lane_space_ball_point` objects, but their `pointDefinition` is:

```text
camera_sam2_mask_measurement_kalman_rts
```

Quest replay continues to render world-space trajectory points from the shot result.
