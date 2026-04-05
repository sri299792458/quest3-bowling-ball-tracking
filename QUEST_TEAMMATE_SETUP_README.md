# Quest Teammate Setup

This guide is for teammates who need to:

- open the Unity project
- build the current Quest app
- connect it to a laptop on the same network
- verify that frames and metadata are reaching the laptop

This is the setup guide for the current working pipeline, not the future V3 transport redesign.

## What The Current Working Pipeline Is

Today the stable path is:

- Quest passthrough camera
- Quest `TCP` control channel to the laptop
- Quest `UDP` JPEG frame stream to the laptop
- laptop records the shot and runs the current tracking/analysis pipeline

Important current defaults:

- `Target Send Fps = 30`
- `Passthrough Send Resolution = 960 x 720`
- `Jpeg Quality = 65`
- `Use Async Gpu Readback = false`
- `Camera Source Probe Only = false`

These defaults are already set in:

- [BowlingBallTracking.unity](/C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Scenes/BowlingBallTracking.unity)
- [QuestBowlingHomeTestRigSetup.cs](/C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Editor/QuestBowlingHomeTestRigSetup.cs)

## Prerequisites

Quest / Unity:

- Quest 3 or Quest 3S
- Developer Mode enabled on the headset
- USB debugging enabled
- Unity `6000.3.5f2`
- Android Build Support installed in Unity Hub

Laptop:

- Windows machine
- Python `3.10+`
- NVIDIA GPU recommended for the full laptop tracking path
- Quest and laptop on the same Wi-Fi network

Repo:

- clone this repo locally
- open it once in Unity so package import completes

## 1. Laptop Setup

From the repo root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
```

That script creates `laptop_pipeline/.venv`, installs dependencies, checks CUDA/PyTorch, and downloads the `SAM2` tiny checkpoint used by the laptop pipeline.

If it fails on CUDA:

- install a CUDA-enabled PyTorch build for that laptop
- rerun the setup script

## 2. Start The Laptop Receiver

For the normal end-to-end path:

```powershell
.\laptop_pipeline\start_quest_bowling_server.cmd
```

For raw capture only, use:

```powershell
.\laptop_pipeline\start_quest_bowling_server_record_only.cmd
```

Notes:

- only run one receiver at a time
- both `TCP` and `UDP` use port `5799`
- that is normal: `TCP 5799` and `UDP 5799` are different sockets

## 3. Open The Project In Unity

1. Open the repo in Unity `6000.3.5f2`.
2. Let Unity finish importing packages.
3. Switch platform to `Android`.
4. Open:
   - [BowlingBallTracking.unity](/C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Scenes/BowlingBallTracking.unity)
5. Run:
   - `Tools > Ball Tracking > Create Or Update Project Assets`
   - `Tools > Ball Tracking > Create Or Update Home Test Rig`

The home test rig should give you a `QuestBowlingHomeTestRig` with the current project wiring already filled in.

## 4. Set The Laptop Address

In the Inspector, select the object with `QuestBowlingStreamClient` and set:

- `Server Host` = the laptop’s IPv4 address on the local network
- `Server Port` = `5799`

To find the laptop IPv4 on Windows:

```powershell
ipconfig
```

Use the address from the active Wi-Fi adapter.

## 5. Confirm The Current Quest Settings

In `QuestBowlingStreamClient`, verify these values:

- `Stream Source = PassthroughCamera`
- `Target Send Fps = 30`
- `Passthrough Send Resolution = 960 x 720`
- `Jpeg Quality = 65`
- `Max Datagram Payload Bytes = 1400`
- `Use Async Gpu Readback = false`
- `Camera Source Probe Only = false`
- `Auto Stream When Connected = true`

These are the current bring-up / collection defaults.

## 6. Build And Install On Quest

1. Connect the Quest by USB.
2. In Unity, build for Android and install to the headset.
3. Put on the headset and grant permissions when prompted:
   - Scene permission
   - Passthrough camera permission

Do not test the passthrough path through Link or simulator. Use the actual headset.

## 7. Basic On-Headset Controls

Current debug controls:

- `X`: start shot
- `Y`: end shot
- `Left thumbstick click`: resend lane calibration

These controls are handled by:

- [QuestBowlingSessionDebugController.cs](/C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingSessionDebugController.cs)

## 8. What “Working” Looks Like

On Quest, the debug view should eventually show statuses like:

- `transport_ready`
- `hello_sent`
- `session_config_sent`
- `lane_calibration_sent`

When you press `X` and `Y`, you should see:

- `local_start_sent`
- `local_end_sent`

On the laptop, a new run directory should appear under:

- `laptop_pipeline/runs`

Important files in a successful run include:

- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `raw/capture_summary.json`
- `capture_context.json`
- `session_config.json`
- `lane_calibration.json`
- `shot_events.jsonl`
- `quest_tracker_status.jsonl`

## 9. What The Metadata Means

The Quest is already sending more than just JPEG frames.

Per session / shot we capture:

- session config
- lane calibration
- shot markers
- Quest-side tracker / capture status

Per frame we capture:

- `source_frame_id`
- `timestamp_us`
- `camera_position`
- `camera_rotation`
- `head_position`
- `head_rotation`

The frame timestamp path now uses the camera API timestamp when available, not just app wall-clock time.

## 10. Troubleshooting

If Quest says `control_connect_timeout` or never connects:

- verify the laptop receiver is running
- verify `Server Host` is correct
- verify Quest and laptop are on the same Wi-Fi
- check Windows Firewall rules for Python / port `5799`

If you get permission problems:

- make sure the app was launched on the real headset
- grant Scene and Passthrough Camera permissions
- if needed, uninstall and reinstall the app

If the laptop receives nothing:

- make sure there is only one receiver process
- do not run multiple copies of the server on port `5799`
- confirm the run folder is updating under `laptop_pipeline/runs`

If you see many `passthrough_not_updated` statuses:

- that is part of the current Quest-side throughput bottleneck
- the current JPEG path typically delivers around `18 FPS` effective even though the camera source itself can update faster

If Unity looks misconfigured:

- rerun `Tools > Ball Tracking > Create Or Update Home Test Rig`
- reopen the bowling scene

## 11. What Not To Change

Unless you are intentionally running an experiment, do not change:

- `Target Send Fps`
- `Passthrough Send Resolution`
- `Jpeg Quality`
- `Use Async Gpu Readback`
- `Camera Source Probe Only`

We have already used those fields for transport experiments, and the teammate setup should stay on the known-good baseline.

## 12. Current Reality Check

The current shipped path is good enough for:

- Quest-to-laptop transport
- collecting raw bowling shots
- recording timestamps and poses
- running the laptop-side tracking pipeline

It is not yet the final V3 video-encoder path.

For transport architecture background:

- [QUEST_LAPTOP_TRANSPORT_README.md](/C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_TRANSPORT_README.md)

For the future redesign:

- [QUEST_LAPTOP_PIPELINE_V3_SPEC.md](/C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_PIPELINE_V3_SPEC.md)
