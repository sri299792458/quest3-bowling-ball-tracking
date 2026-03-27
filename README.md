# Quest 3 Bowling Ball Tracking

This repo is the full project for the Quest 3 mixed-reality bowling prototype.

It contains:

- the Unity Quest app
- the Quest-to-laptop transport layer
- the laptop tracking pipeline
- the vendored `SAM2` source used by the laptop pipeline

The current implemented tracking path is:

- `classical seed + live SAM2`

The seed is found on the laptop during capture. As soon as the seed is confirmed, live `SAM2` starts tracking. Quest receives compact tracking results back for replay rendering.

## Repo Layout

- [`Assets/BallTracking`](Assets/BallTracking)
  - Unity runtime and editor code for the bowling project
- [`laptop_pipeline`](laptop_pipeline)
  - Quest receiver, online seed logic, and `SAM2` bridge
- [`third_party/sam2`](third_party/sam2)
  - vendored `SAM2` source and configs
- [`BALL_TRACKING_SPEC.md`](BALL_TRACKING_SPEC.md)
  - main product and research spec
- [`QUEST_LAPTOP_PIPELINE_SPEC.md`](QUEST_LAPTOP_PIPELINE_SPEC.md)
  - transport and runtime pipeline spec

## Prerequisites

Quest / Unity:

- Unity `6000.3.5f2`
- Quest 3 or Quest 3S
- Android build target

Laptop:

- Windows machine with an NVIDIA GPU
- Python `3.10+`
- CUDA-capable driver

## Clone

```powershell
git clone <your-repo-url>
cd Quest3BowlingBallTracking
```

## Unity Setup

1. Open the repo in Unity `6000.3.5f2`.
2. Let Unity finish package import.
3. Switch the active platform to `Android`.
4. Run `Tools > Ball Tracking > Create Or Update Project Assets`.
5. Open `Assets/BallTracking/Scenes/BowlingBallTracking.unity`.

Notes:

- Do not test passthrough camera access over Link or XR Simulator.
- Grant Quest scene and passthrough camera permissions on device when prompted.

## Laptop Setup

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
```

That script will:

- create `laptop_pipeline/.venv`
- install the Python dependencies
- verify that `torch.cuda.is_available()` is true in that venv
- download `sam2.1_hiera_tiny.pt` into `third_party/sam2/checkpoints`

If the script stops at the CUDA check, install a CUDA-enabled PyTorch build for that machine and rerun the setup script.

Then start the receiver:

```powershell
.\laptop_pipeline\start_quest_bowling_server.cmd
```

## First End-to-End Test

1. Start the laptop receiver.
2. In Unity, add `QuestBowlingStreamClient` to a scene object.
3. Add `QuestBowlingSessionDebugController` to a scene object.
4. Assign:
   - `cameraAccess`
   - laptop IP / port
   - `laneReference`
5. Build and run on Quest.
6. Use the current debug controls:
   - `A`: start shot
   - `B`: end shot
   - `X`: resend lane calibration
   - `Y`: tracker reset

The laptop should create a run folder under:

- `laptop_pipeline/runs`

## Current Limitations

- The polished MR replay renderer is not finished yet.
- The on-device `YOLOv9t` sample remains only a Quest-side baseline, not the main bowling tracker.
- The current laptop path is tuned for a local NVIDIA GPU and the `SAM2` tiny checkpoint.
- The classical seed stage is still heuristic and will need more validation on real Quest captures.

## Self-Sufficiency

This repo is now self-contained for development:

- Unity project lives here
- laptop pipeline lives here
- vendored `SAM2` source lives here
- setup scripts live here

The only large runtime artifact that is not committed is the `SAM2` checkpoint. The setup script downloads that automatically.

## More Docs

- [`BALL_TRACKING_README.md`](BALL_TRACKING_README.md)
- [`BALL_TRACKING_SPEC.md`](BALL_TRACKING_SPEC.md)
- [`BALL_TRACKING_AUTO_INIT_SPEC.md`](BALL_TRACKING_AUTO_INIT_SPEC.md)
- [`HOLISTIC_PIPELINE_RESEARCH.md`](HOLISTIC_PIPELINE_RESEARCH.md)
- [`QUEST_LAPTOP_PIPELINE_SPEC.md`](QUEST_LAPTOP_PIPELINE_SPEC.md)
- [`running_notes.md`](running_notes.md)
