# Quest Bowling Standalone

Quest Bowling Standalone is a Quest 3 mixed-reality bowling replay prototype. The headset streams passthrough camera video and frame metadata to a laptop. The laptop detects the bowling ball, tracks it with YOLO and SAM2, reconstructs a lane-space trajectory, computes shot stats, and sends replay results back to the headset.

The documentation rule for this repo is simple: this README describes what the current code does. Protocol files under `protocol/` are the wire contracts. Old planning docs and speculative design notes should not be treated as product truth.

## Demo Video

[Watch the final narrated demo](https://drive.google.com/file/d/1ChvX2wGKDNvMor3lKa0ZUYFAq08_IGWq/view?usp=sharing).

The demo shows lane placement, live ball tracking, trajectory replay, shot stats, session review, and the current far-lane tracking limitation.

## Current Pipeline

1. The laptop starts `live_stream_receiver` and advertises itself over UDP discovery.
2. The Quest app discovers the laptop, opens media, metadata, and result sockets, then starts one live session for the app run.
3. The Quest encodes passthrough frames as `1280 x 960` H.264 and sends frame metadata on a separate TCP channel.
4. The bowler places the lane in the headset with the pinch-and-hold lane flow, then confirms it.
5. Quest sends a `lane_lock_confirm` metadata event containing the full `lane_lock_result`.
6. The laptop persists that confirmed lane geometry and arms shot detection.
7. YOLO scans live decoded frames for a lane-valid ball seed.
8. SAM2 camera tracking starts immediately from that seed and runs for the live tracking window or until sustained tracking loss.
9. The laptop reconstructs a lane-space trajectory, smooths it, computes stats, and publishes a strict `shot_result`.
10. Quest renders the trajectory replay, shot rail, dynamic callouts, and session review UI.

There is no laptop-side lane guessing in the normal live path. Replayable shot results require a Quest-confirmed lane lock and a camera SAM2 track.

## Repository Layout

- `unity_proof/Assets/StandaloneProof/`: live Quest-side Unity implementation.
- `unity_proof/Assets/Plugins/Android/StandaloneVideoEncoderPlugin/`: Android MediaCodec encoder plugin.
- `laptop_receiver/`: laptop receiver, live pipeline, YOLO/SAM2 tracking, trajectory reconstruction, and stats.
- `protocol/`: versioned metadata, live stream, and artifact contracts.
- `models/`: ignored local model checkpoints and training outputs. The published YOLO training dataset is on Hugging Face: `https://huggingface.co/datasets/sri299792458/quest-bowling-ball-yolo`.
- `third_party/sam2/`: repo-local SAM2 source; checkpoints and caches are ignored.
- `data/`: ignored live sessions, experiments, validation clips, and generated artifacts.
- `start_live_pipeline.ps1`: normal live-session launcher for the laptop.

## Requirements

- Windows laptop with PowerShell.
- Python 3.10 or newer.
- CUDA-capable PyTorch environment for SAM2.
- Unity `6000.3.5f2` with Android/Quest build support.
- Quest 3 connected to the laptop hotspot for live runs.
- YOLO checkpoint at:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/weights/best.pt
```

- SAM2 tiny checkpoint at:

```text
third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt
```

The SAM2 checkpoint is downloaded by the laptop setup script.

## Laptop Setup

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_receiver\setup_laptop_env.ps1
```

That script creates or updates `.venv`, installs `laptop_receiver/requirements-cuda.txt`, verifies CUDA, and downloads the SAM2 tiny checkpoint if it is missing.

## Build And Install Quest App

Build the APK:

```powershell
$unity = "C:\Program Files\Unity\Hub\Editor\6000.3.5f2\Editor\Unity.exe"
& $unity -batchmode -quit `
  -projectPath "$PWD\unity_proof" `
  -executeMethod QuestBowlingStandalone.Editor.StandaloneProofBuild.BuildAndroidProofApk `
  -logFile "$PWD\unity_proof\standalone_proof_build.log"
```

Install it on the connected Quest:

```powershell
$adb = "C:\Program Files\Unity\Hub\Editor\6000.3.5f2\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe"
& $adb devices
& $adb install -r -d .\unity_proof\Builds\StandaloneProof.apk
```

The package name is:

```text
com.student.questbowlingstandaloneproof
```

## Bowling Alley Runbook

1. Start the laptop hotspot.
2. Connect the Quest to the laptop hotspot.
3. Disable Quest proximity sleep for the session:

```powershell
$adb = "C:\Program Files\Unity\Hub\Editor\6000.3.5f2\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe"
& $adb shell am broadcast -a com.oculus.vrpowermanager.prox_close
```

4. Start the laptop live pipeline:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_live_pipeline.ps1
```

5. Launch the Quest app.
6. Wait for the headset to connect to the laptop. If it is not connected, the status should block before lane placement.
7. Use the headset lane flow:
   - pinch and hold to place/align the lane overlay
   - release to preview the lane
   - confirm only when the lane is aligned
8. Wait for `Shot Ready`.
9. Throw the ball.
10. Watch the MR replay and use the shot rail or Review panel after successful shots.

`start_live_pipeline.ps1` stops stale receiver/pipeline Python processes, starts the live receiver, waits for receiver health, then runs the live YOLO/SAM2 pipeline in the same terminal. Press `Ctrl+C` to stop the pipeline and receiver.

`start_live_pipeline.ps1 -NoSam2` is a debug mode. Normal replay requires SAM2.

## Shot Ready Meaning

The headset should show `Shot Ready` only when all of these are true:

- Quest has an active live session.
- H.264 media is streaming.
- metadata is connected.
- the Quest result channel is connected.
- lane calibration is confirmed.
- the laptop pipeline has published a ready `pipeline_status` for the current session/lane.

If any gate is missing, the headset shows `Shot Not Ready` plus the first blocking reason.

Common blocking labels:

- `Laptop Connecting`: Quest does not have an active laptop-backed session yet.
- `Media Stream Not Ready`: the encoder/media socket is not ready.
- `Metadata Reconnecting`: the metadata socket is not connected.
- `Results Reconnecting`: the Quest result socket is not connected.
- `Pinch + Hold Lane`: lane placement is waiting for the bowler.
- `Confirm Lane`: a lane candidate exists and needs confirmation.
- `Laptop Preparing`: laptop has not yet armed the pipeline for the confirmed lane.
- `Laptop Catching Up`: the laptop detector is behind the live stream and is fast-forwarding before it arms shot detection again.
- `Processing Shot`: a shot window is open or being analyzed.

## Live Ports

The default live ports are:

- UDP `8765`: Quest laptop discovery.
- TCP `8766`: H.264 media.
- TCP `8767`: frame metadata and lane confirmations.
- HTTP `8768`: receiver health.
- TCP `8769`: laptop-to-Quest result channel.
- TCP `8770`: laptop-local result publish endpoint.

Receiver health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8768/health
```

## Live Data Outputs

Live sessions are written under:

```text
data/incoming_live_streams/live_<sessionId>_<streamId>/
```

Important files in a live session:

- `stream.h264`: raw H.264 media samples.
- `codec_config.h264`: persisted codec config.
- `media_samples.jsonl`: media sample timing and packet metadata.
- `metadata_stream.jsonl`: frame metadata and Quest metadata events.
- `lane_lock_confirms.jsonl`: lane confirmations from Quest.
- `analysis_lane_lock/<requestId>/lane_lock_result.json`: persisted confirmed lane result.
- `shot_boundaries.jsonl`: automatic shot start/end windows.
- `analysis_camera_sam2/<windowId>/`: camera SAM2 tracking artifacts.
- `analysis_live_shots/<windowId>/shot_result.json`: final shot result payload.
- `outbound_results.jsonl`: result envelopes forwarded to Quest.
- `session_state.json`: current receiver/pipeline state summary.
- `session_start.json` and `session_end.json`: session lifecycle records.

These outputs are ignored by Git.

## Offline And Debug Commands

Validate a landed artifact or live session directory:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.validate_local_clip_artifact <artifact_or_live_session_dir>
```

Process one live session directory once without publishing results:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline `
  --session-dir <live_session_dir> `
  --once `
  --no-publish `
  --yolo-checkpoint .\models\bowling_ball_yolo26s_img1280_lightaug_v3\weights\best.pt `
  --run-sam2
```

Run the live pipeline manually:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.live_stream_receiver
.\.venv\Scripts\python.exe -m laptop_receiver.run_live_session_pipeline `
  --yolo-checkpoint .\models\bowling_ball_yolo26s_img1280_lightaug_v3\weights\best.pt `
  --run-sam2
```

The repo still has offline YOLO and batch SAM2 CLIs for local artifact checks:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact <artifact_dir>
.\.venv\Scripts\python.exe -m laptop_receiver.run_sam2_on_artifact <artifact_dir>
```

### Recreate A Quest Recording From Live Logs

The Unity editor has an offline recorded-session video exporter. It takes a completed live session directory, decodes `stream.h264`, replays the recorded camera poses, lane lock, shot results, trajectory renderer, callouts, shot rail, and review UI through the same Unity scene, then writes a presentation video under `Temp/`.

This is useful when the headset recording contains distracting UI, or when we need a reproducible demo video that matches what the live app would have rendered from the saved logs.

```powershell
$unity = "C:\Program Files\Unity\Hub\Editor\6000.3.5f2\Editor\Unity.exe"
& $unity -batchmode -quit `
  -projectPath "$PWD\unity_proof" `
  -executeMethod QuestBowlingStandalone.Editor.StandaloneRecordedSessionVideoExporter.ExportLatest `
  -sessionDir "$PWD\data\incoming_live_streams\<live_session_dir>" `
  -output "$PWD\Temp\recorded_session_replay.mp4" `
  -questRecordingLook true `
  -fps 30 `
  -frameStep 1 `
  -logFile "$PWD\Temp\recorded_session_replay.log"
```

The exporter uses `outbound_results.jsonl` timestamps, so trajectory overlays appear when the laptop actually published each shot result, not immediately after the throw.

Final demo video: <https://drive.google.com/file/d/1ChvX2wGKDNvMor3lKa0ZUYFAq08_IGWq/view?usp=sharing>

## Core Runtime Invariants

- One Quest app run creates one live session ID.
- Closing and reopening the Quest app creates a fresh session.
- Confirmed Quest lane geometry is the source of truth for shot gating, projection, stats, and replay.
- Automatic shot windows carry the confirmed `laneLockRequestId`.
- Quest replay rejects shot results that do not match the current confirmed lane request ID.
- YOLO is used to find a lane-valid ball seed.
- Camera SAM2 owns live tracking after the seed.
- Trajectory points are reconstructed in lane space and smoothed before stats/replay.
- Predicted terminal tail points are low confidence and should not be treated as measured ball observations.

## Troubleshooting

`Shot Not Ready / Laptop Connecting`

- Start `start_live_pipeline.ps1`.
- Make sure Quest is on the laptop hotspot.
- Check that UDP `8765` and TCP `8766-8769` are not blocked.

`Shot Not Ready / Media Stream Not Ready`

- The Quest encoder/media connection is not healthy.
- Restart the Quest app and the laptop pipeline if the media socket was interrupted.

`Shot Not Ready / Laptop Preparing`

- The laptop has not published ready pipeline status for the confirmed lane.
- Check the terminal running `start_live_pipeline.ps1` for model load or lane confirmation errors.

No replay after a throw

- Check the pipeline terminal for `shot_result_failed`.
- Common causes are `yolo_detection_failed`, `camera_sam2_track_missing`, track loss, or invalid lane projection.
- Look in the latest live session under `analysis_camera_sam2/` and `analysis_live_shots/`.

YOLO misses the ball

- Check lighting first. The live H.264 frames are what YOLO sees, not the beautified headset passthrough view.
- Inspect `stream.h264` or generated debug frames from the latest live session.

Replay is spatially wrong

- Relock the lane carefully.
- Do not trust old replay geometry after a Quest/app/camera/encoder restart or tracking-origin discontinuity.

## Current Limitations

- This is a strong prototype, not a polished product.
- Lane placement quality still matters.
- Low light can break ball detection.
- Stats are only as good as the reconstructed trajectory.
- The live path is optimized for the bowling-alley workflow, not for arbitrary imported videos.
