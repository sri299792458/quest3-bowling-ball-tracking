# Quest Laptop Pipeline Spec

Last updated: 2026-03-27

## Goal

Build the lowest-latency practical local pipeline for:

- Quest 3 passthrough capture
- laptop-side classical seed detection
- laptop-side SAM2 tracking
- Quest-side MR replay

The main requirement is not just "it works." The transport has to look like the real system we would want in a bowling alley:

- untethered Quest
- nearby laptop
- low-latency local network
- compact results returned to Quest

## Transport Decision

We are moving the v1 transport from:

- custom TCP + JPEG + manual packet framing

to:

- WebRTC video upstream
- WebRTC data channel for control and results
- HTTP signaling between Quest and laptop

## Why WebRTC

The old TCP/JPEG path was useful as a bring-up baseline, but it had three bad properties:

- Quest did explicit GPU readback and JPEG encode every frame
- the network path was not media-optimized
- the design pushed us toward a manual-IP, custom-framing local minimum

WebRTC is a better fit because it gives us:

- media-oriented transport
- built-in congestion control and jitter handling
- a clean split between video and control data
- a realistic foundation for low-latency local wireless streaming

## Current Practical Design

### Upstream from Quest

- one passthrough camera for v1: left eye only
- Quest copies the latest camera texture into a WebRTC video source texture
- Quest sends that texture as a WebRTC video track

### Control plane

Quest opens a reliable ordered WebRTC data channel and sends JSON control messages:

- `hello`
- `session_config`
- `lane_calibration`
- `shot_marker`
- `ping`

Laptop sends JSON back on the same data channel:

- `tracker_status`
- `shot_result`
- `pong`

### Signaling plane

For now, signaling is HTTP:

- Quest posts an SDP offer to the laptop
- laptop returns an SDP answer

This still requires a host/IP today, but only for signaling. The streaming path itself is WebRTC.

## Why We Are Still Keeping Session Metadata

Even with WebRTC video, the laptop still needs structured bowling metadata:

- session id
- camera intrinsics
- lane calibration
- shot start / shot end markers

That metadata is small, so it belongs on the data channel instead of being crammed into the video path.

## Quest Runtime Flow

1. Open `PassthroughCameraAccess` for the left camera.
2. Create a WebRTC peer connection.
3. Create a reliable ordered data channel.
4. Create a `VideoStreamTrack` from a persistent `RenderTexture`.
5. Copy the latest passthrough frame into that render texture at the target send FPS.
6. Create an SDP offer and send it to the laptop over HTTP.
7. Apply the SDP answer from the laptop.
8. When the data channel opens:
   - send `hello`
   - send `session_config`
   - send `lane_calibration` if available
9. On user input:
   - send `shot_started`
   - send `shot_ended`
   - send `tracker_reset` when needed
10. Receive `tracker_status` and `shot_result` on the data channel.
11. Render replay locally in Quest.

## Laptop Runtime Flow

1. Listen for HTTP signaling on `5799`.
2. Accept a Quest SDP offer.
3. Build an `aiortc` peer connection.
4. Accept the inbound video track.
5. Accept the inbound control data channel.
6. Convert each received video frame to BGR and persist it locally as JPEG for the existing SAM2 bridge.
7. Keep a short pre-roll buffer.
8. On `shot_started`:
   - open a shot recorder
   - keep feeding frames into the online seed logic
9. As soon as the classical seed is confirmed:
   - start live SAM2 during the shot
10. On `shot_ended`:
   - finalize the shot
   - use live SAM2 result if available
   - otherwise use warm batch SAM2 fallback
11. Send `shot_result` back over the data channel.

## Analysis Path

The transport change does not change the tracker stack.

The current analysis path is still:

- classical seed during capture
- live SAM2 when seed is confirmed
- warm SAM2 fallback if live path fails

The new part is only how frames reach the laptop.

## Latency Model

The main latency wins from this move are:

- no explicit JPEG encode on Quest
- video goes over a transport designed for media
- control messages are separated from bulk pixels

The laptop still re-encodes received frames to JPEG for the existing bridge, but that happens after network receive and keeps the current SAM2 pipeline intact while we switch transports.

That local JPEG persistence is acceptable in v1 because:

- it avoids rewriting the whole SAM2 bridge at the same time
- it keeps the current shot recorder, online seed logic, and fallback path intact

## Current Limits

The first WebRTC cut still has two deliberate compromises:

1. Manual signaling host
- Quest still needs a laptop host/IP in the inspector today
- we are not solving discovery in the same patch

2. HTTP offer/answer signaling
- simple and robust for v1
- not yet a full discovery + signaling service

## Planned Next Networking Step

After the WebRTC transport is stable, the next networking upgrade should be:

- automatic laptop discovery on the local network

Preferred direction:

- mDNS / DNS-SD or an equivalent local discovery layer

That removes repeated manual IP entry without changing the media/control design.

## Why We Are Not Returning Video Back to Quest

The laptop should not render replay frames and ship them back.

Quest should receive:

- path samples
- timing
- confidence
- failure flags

and render the MR replay locally.

That keeps the downstream payload tiny and preserves headset-local MR anchoring.

## Current Commands

Laptop setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
```

Laptop WebRTC receiver:

```powershell
.\laptop_pipeline\start_quest_bowling_server.cmd
```

Laptop synthetic mode:

```powershell
.\laptop_pipeline\start_quest_bowling_server_synthetic.cmd
```

## References

- Meta Passthrough Camera API sample:
  - https://github.com/oculus-samples/Unity-PassthroughCameraApiSamples
- Unity WebRTC package:
  - https://github.com/Unity-Technologies/com.unity.webrtc
- aiortc:
  - https://github.com/aiortc/aiortc
