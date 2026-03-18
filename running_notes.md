# Running Notes

## 2026-03-18

- Started from Meta's official `Unity-PassthroughCameraApiSamples` project instead of the coursework project so the Quest 3 camera permissions, MRUK setup, and Unity Inference Engine wiring come from a known-good baseline.
- Kept the sample's local `YOLOv9t` path for the first testable build. This project currently uses the generic COCO-style model and filters for the `sports_ball` class as a stand-in for a bowling-ball-specific detector.
- Chose a runtime bootstrap approach instead of hand-editing Unity scene YAML. The tracker installs itself automatically in `BowlingBallTracking` and `MultiObjectDetection`, which keeps the feature isolated and avoids brittle scene surgery.
- Added an editor utility to duplicate Meta's `MultiObjectDetection` scene into `Assets/BallTracking/Scenes/BowlingBallTracking.unity` and add it to Build Settings.
- Version-control automation is blocked in this shell because neither `git` nor Plastic's `cm` CLI is installed. No commits were created from here.

## Current Limitations

- The bundled model is not trained specifically for bowling balls. Expect false positives and misses until it is replaced with a one-class bowling-ball YOLOv9t model.
- The current tracker uses world-space positions from the sample's environment raycast pipeline. It does not yet estimate a lane plane, release timing, or ballistic motion.
- This project has not been committed to version control from the shell. If you want Plastic/Git history, install a CLI or create the repo from Unity Hub / Unity Version Control after opening the project.
