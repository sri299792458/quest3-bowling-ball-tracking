# Quest 3 Bowling Ball Tracking

This project is a standalone Unity project based on Meta's official Passthrough Camera API sample.

## What it does now

- Uses Quest 3 passthrough camera access locally on-device.
- Runs Meta's sample `YOLOv9t` model through Unity Inference Engine.
- Filters detections to the `sports_ball` class and overlays a tracked world-space marker.
- Adds a dedicated scene: `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.

## First open

1. Open the project root in Unity `6000.3.5f2`.
2. Let Unity resolve packages.
3. Run `Tools > Ball Tracking > Create Or Update Project Assets`.
4. Open `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.
5. Build and run on Quest 3. Use a subfolder such as `Builds/Android` as the build output folder. Create it first if it does not exist.
6. Do not test the camera path over Link or XR Simulator.

## Important

- The included model is still a generic object detector. For real bowling tracking, replace it with a custom-trained one-class bowling-ball YOLOv9t model.
- See `running_notes.md` for implementation decisions and current gaps.
