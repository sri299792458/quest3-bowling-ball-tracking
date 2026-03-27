# Quest 3 Bowling Ball Tracking

This project is a standalone Unity project based on Meta's official Passthrough Camera API sample.

## What it does now

- Uses Quest 3 passthrough camera access locally on-device.
- Runs Meta's sample `YOLOv9t` model through Unity Inference Engine.
- Filters detections to the `sports_ball` class and overlays a tracked world-space marker.
- Adds a dedicated scene: `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.
- Keeps Meta's `StartScene` launcher visible on Quest before entering the bowling scene.
- Uses `GPUCompute` for inference. This is intentional; the `CPU` backend crashed on-device with the current Unity Inference Engine package in this project.
- Includes the first Quest-to-laptop streaming pipeline for the actual bowling prototype:
  - Quest frame streaming: `Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs`
  - Quest debug shot controls: `Assets/BallTracking/Runtime/QuestBowlingSessionDebugController.cs`
  - laptop receiver: `laptop_pipeline/quest_bowling_server.py`
  - current analysis path: classical seed + SAM2

## First open

1. Open the project root in Unity `6000.3.5f2`.
2. Let Unity resolve packages.
3. Switch the active platform to `Android` in `File > Build Profiles` or `Build Settings` if Unity opens the project with `Windows` active. The active platform is local editor state and is not shared through the repo.
4. Run `Tools > Ball Tracking > Create Or Update Project Assets`.
5. Open `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.
6. Build and run on Quest 3. Use a subfolder such as `Builds/Android` as the build output folder. Create it first if it does not exist.
7. Do not test the camera path over Link or XR Simulator.

## On-device flow

1. Launch the app on Quest 3.
2. The app starts in Meta's `StartScene` launcher.
3. Select `BowlingBallTracking`.
4. If Quest asks for `Scene` or `Passthrough Camera Access`, grant them.
5. In the bowling scene, press `A` or do a pinch once to start inference.

## Current behavior and limits

- The included detector is still the generic COCO-style sample model, not a bowling-ball-specific model.
- The custom tracker only follows the `sports_ball` class.
- Generic classes such as `laptop`, `mouse`, `person`, and `chair` may detect more reliably than `bottle` or `cell phone` in passthrough.
- A real bowling ball is not expected to detect reliably with the current bundled model.

## Important

- The included model is still a generic object detector. It is useful only as a Quest-side sample baseline, not as the planned bowling tracker.
- The target product spec assumes a hybrid architecture: Quest capture + PC analysis + immediate post-shot MR replay.
- The current implemented PC tracking path is `classical seed + SAM2`, with the seed detector running during capture and live SAM2 starting as soon as a seed is confirmed.
- See `BALL_TRACKING_SPEC.md` for the product spec, architecture, algorithm choice, verification plan, and v1 boundaries.
- See `BALL_TRACKING_AUTO_INIT_SPEC.md` for the focused automatic-initializer plan that removes manual seeding from the PC prototype.
- See `QUEST_LAPTOP_PIPELINE_SPEC.md` for the current Quest-to-laptop transport and live tracking flow.
- See `running_notes.md` for implementation decisions and current gaps.
