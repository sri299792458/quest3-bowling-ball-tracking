# Quest Laptop Pipeline Spec

Last updated: 2026-03-28

## Goal

Build the lowest-latency practical local pipeline for:

- Quest 3 passthrough capture
- laptop-side classical seed detection
- laptop-side SAM2 tracking
- Quest-side MR replay

The transport should match the real product shape:

- untethered Quest
- nearby laptop
- low-latency local network
- compact results returned to Quest

## Transport Decision

We are moving the active v1 transport to:

- TCP control channel
- UDP frame datagrams
- JPEG-compressed frames on Quest

This replaces the current WebRTC-first experiment as the primary path for this repo.

## Why This Move

The WebRTC experiments proved something useful, but not the thing we needed:

- Quest could reach the laptop
- control/signaling could come up
- video still did not publish reliably from the Unity 6 + Quest sender path in this setup

For our actual architecture, Quest to nearby laptop on the same local network, the simpler transport is the better bet:

- fewer moving parts
- easier packet-level debugging
- no browser/media-stack dependency
- no SDP / ICE / signaling machinery in the hot path

## Current Practical Design

### Upstream from Quest

- one passthrough camera for v1: left eye only
- Quest copies the latest camera frame into a local `RenderTexture`
- Quest does GPU readback plus JPEG encode
- Quest fragments each encoded frame into UDP datagrams and sends them to the laptop

### Control plane

Quest opens one TCP connection to the laptop and sends structured JSON messages in framed packets:

- `hello`
- `session_config`
- `lane_calibration`
- `shot_marker`
- `ping`

Laptop sends framed JSON back on the same TCP connection:

- `tracker_status`
- `shot_result`
- `pong`
- `error`

### Frame plane

- each UDP datagram carries one fragment of a single encoded frame payload
- the laptop reassembles fragments by sender endpoint plus `frame_id`
- once a full frame is reassembled, the laptop decodes the binary frame payload and routes it into the current session

## Why We Still Keep Session Metadata

The laptop still needs structured bowling metadata:

- session id
- camera intrinsics
- lane calibration
- shot start / shot end markers

That metadata is small and belongs on the reliable TCP control channel.

## Quest Runtime Flow

1. Open `PassthroughCameraAccess` for the left camera.
2. Open one TCP control connection to the laptop.
3. Send `hello`.
4. Send `session_config`.
5. Send `lane_calibration` when available.
6. At the target send FPS:
   - copy the latest source frame into a `RenderTexture`
   - read it back to CPU
   - JPEG encode it
   - fragment and send it over UDP
7. On user input:
   - send `shot_started`
   - send `shot_ended`
   - send `tracker_reset` when needed
8. Receive `tracker_status` and `shot_result` back over TCP.
9. Render replay locally in Quest.

## Laptop Runtime Flow

1. Listen for TCP and UDP on `5799`.
2. Accept the inbound Quest TCP control connection.
3. Register the session on `hello` / `session_config`.
4. Reassemble UDP frame fragments into full frame payloads.
5. Persist received JPEGs locally through the existing shot recorder path.
6. Keep a short pre-roll buffer.
7. On `shot_started`:
   - open a shot recorder
   - keep feeding frames into the online seed logic
8. As soon as the classical seed is confirmed:
   - start live SAM2 during the shot
9. On `shot_ended`:
   - finalize the shot
   - use live SAM2 result if available
   - otherwise use warm batch SAM2 fallback
10. Send `shot_result` back over TCP.

## Analysis Path

The transport change does not change the tracker stack.

The current analysis path is still:

- classical seed during capture
- live SAM2 when seed is confirmed
- warm SAM2 fallback if live path fails

## Diagnostic Modes

The repo keeps two lightweight receiver modes:

- `diagnostic`
  - records raw received UDP JPEG frames only
  - does not run the tracking bridge
  - returns a simple diagnostic `shot_result`
- `synthetic`
  - runs the normal control and recording path
  - returns a fake-but-valid tracking result for round-trip testing

There is also a `smoke` receiver mode that auto-records the first fixed batch of UDP frames, but the active Quest bring-up path is the main bowling scene plus `SyntheticPattern`.

## Latency Model

This path is intentionally simple, not magically optimal.

Current tradeoff:

- lower system complexity than WebRTC
- explicit frame-level visibility for debugging
- extra Quest CPU work from readback plus JPEG encode

That Quest-side JPEG encode is acceptable for the current bring-up because it gets us back to a controllable local transport. We can optimize the sender once the end-to-end path is proven stable.

## Current Limits

1. Manual server host
- Quest still needs a laptop IP/host today
- discovery is a later step

2. Quest-side JPEG encode
- simple and debuggable
- not yet the final optimized sender

3. Best-effort UDP
- packet loss is possible
- the control path remains reliable over TCP

## Planned Next Networking Step

After the UDP/TCP path is stable, the next networking upgrade should be:

- automatic laptop discovery on the local network

Preferred direction:

- mDNS / DNS-SD or equivalent local discovery

## Why We Are Not Returning Video Back to Quest

The laptop should not render replay frames and ship them back.

Quest should receive:

- path samples
- timing
- confidence
- failure flags

and render the MR replay locally.

## Current Commands

Laptop setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_pipeline\setup_laptop_env.ps1
```

Laptop live receiver:

```powershell
.\laptop_pipeline\start_quest_bowling_server.cmd
```

Laptop synthetic mode:

```powershell
.\laptop_pipeline\start_quest_bowling_server_synthetic.cmd
```

Laptop diagnostic mode:

```powershell
.\laptop_pipeline\start_quest_bowling_server_diagnostic.cmd
```

Laptop smoke mode:

```powershell
.\laptop_pipeline\start_quest_bowling_server_smoke.cmd
```
