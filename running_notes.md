# Running Notes

## 2026-03-18

- Started from Meta's official `Unity-PassthroughCameraApiSamples` project instead of the coursework project so the Quest 3 camera permissions, MRUK setup, and Unity Inference Engine wiring come from a known-good baseline.
- Kept the sample's local `YOLOv9t` path for the first testable build. This project currently uses the generic COCO-style model and filters for the `sports_ball` class as a stand-in for a bowling-ball-specific detector.
- Chose a runtime bootstrap approach instead of hand-editing Unity scene YAML. The tracker installs itself automatically in `BowlingBallTracking` and `MultiObjectDetection`, which keeps the feature isolated and avoids brittle scene surgery.
- Added an editor utility to duplicate Meta's `MultiObjectDetection` scene into `Assets/BallTracking/Scenes/BowlingBallTracking.unity` and add it to Build Settings.
- Installed Git locally because neither `git` nor Plastic's `cm` CLI was initially available in the shell.
- Created the first local commit after copying the standalone sample-based project and adding the ball-tracking scaffolding.
- Ran Unity `6000.3.5f2` in batch mode, upgraded the project from the sample's editor version, resolved packages, and successfully generated `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.
- Unity upgraded `com.unity.ai.inference` from `2.2.1` to `2.4.1` and `com.unity.xr.openxr` from `1.15.1` to `1.16.1` during import. Those changes were kept because they match the installed editor.
- Kept README instructions repo-relative instead of machine-specific so teammates can clone the project without editing local file paths.
- Documented that the active build target may still open as `Windows` on another machine. Unity stores the selected platform in local editor state rather than repo content, so teammates should switch to `Android` before building.
- Confirmed on-device that `StartScene` was not actually empty. The launcher existed, but Quest was returning the scene to passthrough-only mode immediately after startup. Added a minimal `StartMenu` fix that keeps passthrough disabled while `StartScene` is active so the launcher remains visible.
- The next blocker is in the detection scene rather than the launcher. Reverted the temporary raw-count UI change and instead added detailed runtime status/debug to the detection panel and logcat so we can distinguish pause state, camera feed availability, raw inference output, and spatial-anchor gating without changing scene behavior.
- The first pass of detection debug showed the coroutine was still failing before those later status checkpoints. Added step-specific exception logging around texture capture, tensor conversion, scheduling, output peeks, and readback so Logcat can identify the exact failing inference stage on device.
- The step-specific exception logs narrowed the runtime failure to `Worker.Schedule(input)` while the inference manager was configured for `BackendType.CPU`. The installed `com.unity.ai.inference 2.4.1` package appears to have a null path there for this texture-driven model, so the project backend was switched to `GPUCompute` as the next single fix while keeping the detailed logs in place.

## Current Limitations

- The bundled model is not trained specifically for bowling balls. Expect false positives and misses until it is replaced with a one-class bowling-ball YOLOv9t model.
- The current tracker uses world-space positions from the sample's environment raycast pipeline. It does not yet estimate a lane plane, release timing, or ballistic motion.
- The current implementation is a Quest 3 test harness, not a production app. It is intended to prove local PCA + YOLOv9t + world-space marker tracking on device before training or calibrating a bowling-specific model.
