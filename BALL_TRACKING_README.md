# Quest 3 Bowling Ball Tracking

This project is a standalone Unity project based on Meta's official Passthrough Camera API sample.

## What it does now

- Uses Quest 3 passthrough camera access locally on-device.
- Runs Meta's sample `YOLOv9t` model through Unity Inference Engine.
- Filters detections to the `sports_ball` class and overlays a tracked world-space marker.
- Auto-starts the detection session in the dedicated bowling scene after permissions are granted.
- Shows a head-locked status readout with the current target class and recently visible labels.
- Adds a dedicated scene: `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.

## First open

1. Open the project root in Unity `6000.3.5f2`.
2. Let Unity resolve packages.
3. Switch the active platform to `Android` in `File > Build Profiles` or `Build Settings` if Unity opens the project with `Windows` active. The active platform is local editor state and is not shared through the repo.
4. Run `Tools > Ball Tracking > Create Or Update Project Assets`.
5. Open `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.
6. Build and run on Quest 3. Use a subfolder such as `Builds/Android` as the build output folder. Create it first if it does not exist.
7. Do not test the camera path over Link or XR Simulator.

## Important

- The included model is still a generic object detector. For real bowling tracking, replace it with a custom-trained one-class bowling-ball YOLOv9t model.
- The current target class is `sports_ball`, which comes from the generic COCO label set. For a quick smoke test, try objects the model is known to recognize such as `person`, `chair`, `cup`, `bottle`, or a bright `sports ball`.
- See `running_notes.md` for implementation decisions and current gaps.
