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
- After confirming the GPUCompute change fixed on-device inference, the temporary detection debug UI and step-by-step exception instrumentation were removed to return the sample scene to a cleaner baseline while keeping the working backend change.

## Current Limitations

- The bundled model is not trained specifically for bowling balls. Expect false positives and misses until it is replaced with a one-class bowling-ball YOLOv9t model.
- The current tracker uses world-space positions from the sample's environment raycast pipeline. It does not yet estimate a lane plane, release timing, or ballistic motion.
- The current implementation is a Quest 3 test harness, not a production app. It is intended to prove local PCA + YOLOv9t + world-space marker tracking on device before training or calibrating a bowling-specific model.

## 2026-03-25

- Added `BALL_TRACKING_SPEC.md` as the main project spec so the repo has one concrete reference for scope, algorithm choices, verification strategy, and v1 non-goals.
- Locked the baseline algorithm decision to a custom one-class `YOLOv9t` detector plus a single-ball Kalman tracker, with TrackNet-style temporal tracking reserved as the main benchmark alternative rather than the first implementation target.
- Wrote the verification plan explicitly as offline-first: public bowling videos and Quest-recorded passthrough clips should be used to validate detector / tracker changes before alley testing.
- Kept the spec honest about v1 boundaries: no spin estimation, no production-grade claims, and no assumption that full-lane reliable breakpoint measurement is solved from the current sample-model baseline.

## 2026-03-26

- Rewrote the project spec around the user-perspective product flow rather than around the current Unity sample architecture.
- The agreed v1 target is now a hybrid system: Quest 3 captures the shot and renders the MR replay, while a nearby PC performs the heavier analysis and returns structured replay data.
- Clarified that the intended timing mode is immediate post-shot MR replay, not fully offline batch processing and not live during-roll coaching overlays.
- Marked depth and scene understanding as optional geometry aids rather than hard dependencies. The replay should still work from manual lane calibration, headset pose, and known lane geometry.
- Kept `YOLOv9t + Kalman` as the first baseline, while moving `SAM 3`, `RF-DETR`, and TrackNet-style models into the benchmark / later-experiment category.
- Updated the plan again once the dataset bottleneck became clear: we should not block the project on collecting a bowling dataset before we can test the full idea.
- The first research baseline is now `classical seed + SAM 2`, with `XMem++` as an optional follow-up if SAM 2 needs stronger long-range memory.
- `YOLOv9t + Kalman` remains in the spec, but only as the later deployment path after bootstrapped bowling data exists.

## 2026-03-27

- Tightened the promptable-tracking plan again after the manual SAM2 runs. Manual seeding proved feasibility, but it is not acceptable for the intended replay workflow.
- Added [`BALL_TRACKING_AUTO_INIT_SPEC.md`](BALL_TRACKING_AUTO_INIT_SPEC.md) to document the first automatic-initializer path: `Grounding DINO` picks the initial bowling-ball box and `SAM2` propagates it through the short clip.
- Updated the main spec and README so the short-term baseline now reads `Grounding DINO + SAM2`, while classical bowling-analysis heuristics are kept as fallback/ranking ideas rather than the primary initializer.
- The working implementation direction moved again after the offline initializer experiments: the current implemented path is now `classical seed + SAM2`, not `Grounding DINO + SAM2`.
- Brought the Quest-to-laptop transport work into this repo after realizing the previous round of implementation had been done in the coursework Unity workspace instead of `Quest3BowlingBallTracking`.
- Added the Quest streaming client, debug shot controller, laptop receiver, online classical seed bridge, and live SAM2 handoff here so future work stays in the correct repository.
- Added `QUEST_LAPTOP_PIPELINE_SPEC.md` to document the current runtime architecture: Quest streams frames, the laptop seeds during capture, live SAM2 starts once the seed is confirmed, and Quest receives compact replay data back.
- Vendored the `SAM2` source into `third_party/sam2`, copied the classical seed core into `laptop_pipeline`, and added `laptop_pipeline/setup_laptop_env.ps1` so the repo no longer depends on a separate `sam2_bowling_eval` workspace.
- Rewrote the top-level README and laptop README around a clone-and-run path: open the Unity project, run the laptop setup script, start the receiver, then test the Quest scene against the local server.

## 2026-03-28

- Replaced the first Quest-to-laptop prototype transport with `WebRTC video + data channel + HTTP signaling` and updated the runtime spec to match that direction.
- Fixed multiple non-network blockers before the transport itself could be judged honestly:
  - Android cleartext HTTP had to be enabled for local `http://<laptop-ip>:5799` signaling.
  - Quest passthrough camera permission (`horizonos.permission.HEADSET_CAMERA`) had to be requested at runtime.
  - The bowling scene needed to stay the actual startup path instead of falling back to the inherited sample UX.
- Added device-side status breadcrumbs to the Quest client so the headset can report concrete stages such as `waiting_camera`, `checking_signal`, `signal_ok`, `creating_offer`, and later WebRTC state changes.
- Added persistent Quest-side status logs under app storage because headset HUD text and logcat alone were too noisy for reliable debugging.
- Proved that the Quest runtime path is alive in the built APK: `BowlingBallRuntimeBootstrap` registers, the bowling rig configures, and `QuestBowlingStreamClient` reaches its connection loop.
- Narrowed the network diagnosis carefully instead of guessing:
  - campus/public Wi-Fi was not the first blocker;
  - the real first blockers were app-side config and permission issues;
  - later testing on the phone hotspot showed that Quest could reach the laptop signaling endpoint successfully.
- Replaced the Quest signaling preflight and offer POST from `UnityWebRequest` to a direct `TcpClient` HTTP path after the app repeatedly stalled at `checking_signal` despite the laptop server being reachable from the Quest shell.
- Confirmed that the hotspot path now reaches the laptop cleanly: Quest advanced from `checking_signal` to `signal_ok`, successfully posted the WebRTC offer, received an answer, and opened the WebRTC data channel.
- The next concrete Quest-side blocker was not signaling but texture format compatibility in Unity WebRTC:
  - `VideoStreamTrack` rejected the initial render texture format with `ArgumentException: This graphics format R8G8B8A8_SRGB is not supported for streaming, please use supportedFormat: B8G8R8A8_SRGB`.
  - Fixed the stream texture creation to use `WebRTC.GetSupportedGraphicsFormat(SystemInfo.graphicsDeviceType)` instead of a hard-coded `RenderTextureFormat.ARGB32`.
- Current transport milestone: on Quest hotspot networking, the app now reaches `peer_state=Connected`, `ice_state=Connected`, and `data_channel_open`, which means the base Quest <-> laptop WebRTC control path is functioning.
- The next ambiguity was the media plane: Quest control messages and even synthetic `shot_result` payloads were working, but the laptop `raw/frames` folders were still empty in the normal bowling flow.
- Decided to stop patching inside the full bowling pipeline and add a clean transport diagnostic harness instead.
- The new diagnostic plan is intentionally narrow:
  - Quest can stream either `PassthroughCamera` or a `SyntheticPattern`.
  - Laptop can run a `diagnostic` mode that records raw received frames only and returns a frame-count summary.
  - This creates a clean matrix:
    - synthetic source + diagnostic server = pure WebRTC media check
    - passthrough source + diagnostic server = real camera-to-WebRTC check
    - passthrough source + live server = full bowling pipeline
- The diagnostic matrix gave the first clean media conclusion:
  - `SyntheticPattern` also produced `no_video_frames_received`.
  - Therefore the current failure was not in passthrough capture; it was in the Quest WebRTC sender path itself.
- Added Quest-side outbound RTP stats and finally got the decisive evidence from logcat:
  - Quest was rendering local stream frames continuously (`local_stream_frames` kept increasing),
  - but `sender_video_stats` stayed at `encoded 0 | sent 0 | bytes 0`.
  - That means the sender was not encoding any video at all, even though signaling and the data channel were fully connected.
- The strongest native clue in logcat was `HardwareVideoEncoderFactory: No shared EglBase.Context. Encoders will not use texture mode.`
- The next sender-side fix was based on Unity WebRTC's own sample patterns rather than further ad hoc patching:
  - use `WebRTC.GetSupportedRenderTextureFormat(SystemInfo.graphicsDeviceType)` for the stream `RenderTexture`,
  - create the video track with the named `VideoStreamTrack("bowling-video", renderTexture)` constructor,
  - attach it through a `MediaStream`,
  - and set the video transceiver codec preference to `H264` so Android can stay on the MediaCodec hardware path.
- Tried an in-app `LocalLoopback` mode to remove the laptop from the equation entirely, but on Quest this caused an immediate native crash inside `libwebrtc` / `Il2CppExceptionWrapper` during startup.
- That loopback path is now treated as an unsafe Android diagnostic for this project:
  - the scene default was switched back to `RemoteLaptop`,
  - and the client now guards against `LocalLoopback` on Quest builds by falling back to remote mode with a `loopback_unsupported` status instead of hard-crashing the app.
- Added a stricter reset point after that: a dedicated `WebRtcSmokeTest` path that is intentionally outside the bowling flow.
  - Quest side: `WebRtcSmokeTestClient` uses a hidden synthetic Unity camera and the package-style `CaptureStreamTrack(...)` path.
  - Laptop side: `quest_bowling_server.py --analysis-mode smoke` records the first fixed batch of incoming frames automatically and returns a simple success/failure result.
  - The purpose is to answer one bounded question only: can this Unity WebRTC setup on Quest publish any video frames in this repo.
- The smoke test now has a decisive result:
  - Quest reaches `signal_ok`, `peer_state=Connected`, and `data_channel_open`,
  - but `sender_video_stats` still remains `encoded 0 | sent 0 | bytes 0`,
  - and the laptop smoke run finalizes with `failure_reason = no_video_frames_received`.
- That means the current blocker is no longer plausibly inside the bowling pipeline. Even the stripped-down synthetic-camera repro fails to publish video RTP from Quest in this project/setup.
- Added a stronger external control after that result:
  - pulled the official `Unity Render Streaming` package repo locally,
  - compared its sender path against the smoke sender,
  - and added a repo-contained `Render Streaming Official Control` harness.
- The new control path includes:
  - a package reference to `com.unity.renderstreaming`,
  - an editor menu item to create `RenderStreamingOfficialControl.unity`,
  - a runtime bootstrap that points the official signaling manager at the laptop web app,
  - a portable local Node.js setup script,
  - and a launcher for Unity's official Render Streaming web app on port `8080`.
- This control matters because it removes the custom bowling laptop server from the test entirely.
  - If Quest video appears in the browser through the official Render Streaming path, the custom laptop stack is the likely culprit.
  - If it still fails, the issue is much more likely to be Unity 6000 + Quest + Unity WebRTC / Render Streaming on this machine rather than the bowling code.
- Stopped treating WebRTC as the active path after that investigation and switched the repo back to a simpler local transport design:
  - reliable TCP control packets for session metadata, calibration, shot markers, status, and results
  - UDP datagrams for JPEG-compressed frame payloads
- Reused the existing app-level bowling packet format instead of inventing a whole new session protocol:
  - `BowlingProtocol` still frames control packets
  - frame payloads still carry the same `session_id`, `shot_id`, `frame_id`, timestamp, pose placeholder, and JPEG bytes
  - only the outer transport changed
- Replaced the main Quest runtime transport in `QuestBowlingStreamClient`:
  - removed the active dependency on peer connections, SDP signaling, and data channels
  - added one TCP control connection plus one UDP sender
  - added explicit Quest-side JPEG readback/encode and UDP fragmentation
- Replaced the laptop receiver implementation with a TCP + UDP server:
  - TCP control packets now drive session registration and shot lifecycle
  - UDP fragments are reassembled into full frame payloads before they enter the existing `SAM2` bridge
  - synthetic, diagnostic, and smoke receiver modes were kept on the Python side so the same local validation patterns still exist
- Verified the new code path locally before trying Quest again:
  - `py -3 -m py_compile` passed for the new laptop transport files
  - `dotnet build Assembly-CSharp.csproj -nologo` succeeded
  - the Python receiver imported cleanly and stayed alive when started briefly on localhost
- Cleaned the Unity project back down to the active transport path:
  - removed the legacy WebRTC / Render Streaming package references from `Packages/manifest.json`
  - removed the old smoke-test / official-control scenes from Build Settings
  - deleted the old Unity-side WebRTC / Render Streaming editor/runtime artifacts and imported sample assets
  - briefly added a one-off cleanup utility during the transport migration, then removed it once the repo was cleaned up

## 2026-03-29

- Wrote a consolidated pause-state findings note in [FINDINGS_SO_FAR.md](C:/Users/student/Quest3BowlingBallTracking/FINDINGS_SO_FAR.md) covering transport, capture, oracle review, YOLO training, causal YOLO -> SAM2 results, and the mixed open-source generalization check.
