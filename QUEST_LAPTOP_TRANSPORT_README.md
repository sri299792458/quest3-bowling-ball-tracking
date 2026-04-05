# Quest-Laptop Transport README

Last updated: 2026-03-30

This document is a study guide for understanding the Quest-to-laptop networking stack in this repo.

It is intentionally more detailed than the normal project README so you can use it to prepare for presentation questions.

## 1. One-Sentence Summary

The Quest app sends small, reliable control messages over TCP and larger, lossy-but-fast JPEG frame payloads over UDP to a nearby laptop, and the laptop sends compact tracker status and shot results back over TCP.

## 2. What Problem This Transport Is Solving

The product shape is:

- untethered Quest 3
- nearby Windows laptop on the same local network
- Quest captures passthrough camera frames
- laptop does the heavy analysis
- Quest receives compact results back for replay

This means the transport has two very different jobs:

1. Move small, important metadata reliably.
2. Move a stream of camera frames with as little latency as practical.

Those two jobs have different networking needs, which is why the repo uses two protocols instead of one.

## 3. Why We Use Both TCP And UDP

### TCP Is Used For The Control Plane

TCP is connection-oriented and reliable.

That means:

- bytes arrive in order
- missing bytes are retransmitted
- the receiver sees a continuous stream of bytes, not separate packets

This is good for things that must not silently disappear:

- `hello`
- `session_config`
- `lane_calibration`
- `shot_started`
- `shot_ended`
- `tracker_status`
- `shot_result`

If `shot_started` is lost, the whole run can be mis-recorded. That is exactly the kind of message TCP is good at protecting.

### UDP Is Used For The Frame Plane

UDP is connectionless and best-effort.

That means:

- no retransmission
- no built-in ordering guarantee
- lower overhead than TCP
- sender can keep moving instead of waiting for lost frame data to be resent

This is better for camera frames because a late old frame is usually less valuable than the newest frame.

For our use case, frame traffic should prefer:

- low latency
- controllable packet-level debugging
- no retransmission backlog

That is why frames go over UDP instead of TCP.

## 4. Why Not Use Only TCP For Everything

Because TCP reliability becomes a liability for live-ish video.

If frames were sent over TCP:

- lost packets would trigger retransmissions
- later frames would get stuck behind earlier missing data
- backlog would build
- latency would rise

That is called head-of-line blocking.

For control messages, that tradeoff is worth it.
For camera frames, it usually is not.

## 5. Why Not Use Only UDP For Everything

Because some messages are too important to lose.

If we sent everything over UDP:

- `hello` could disappear
- `session_config` could disappear
- `lane_calibration` could disappear
- `shot_started` / `shot_ended` could disappear
- Quest might think the shot was recorded while the laptop never opened a recorder

So the design is:

- TCP for correctness-critical metadata
- UDP for high-volume frame payloads

## 6. Why We Abandoned WebRTC

This repo originally explored a WebRTC / Render Streaming style path.

What we learned:

- signaling could come up
- control channels could come up
- Quest outbound video publication was not reliable in this setup

The repo then moved to a simpler local architecture:

- TCP control
- UDP frames
- JPEG payloads

The project conclusion is not "WebRTC is bad in general."
The conclusion is:

- for this repo
- on this Quest + Unity + nearby-laptop setup
- the simpler custom transport was the better engineering bet

See:

- [QUEST_LAPTOP_PIPELINE_SPEC.md](C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_PIPELINE_SPEC.md)

## 7. Big Picture Architecture

### On Quest

The Quest side lives mainly in:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)
- [BowlingProtocol.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/BowlingProtocol.cs)

Its jobs are:

- open passthrough camera access
- open TCP control connection
- open UDP client
- send session metadata
- capture frames
- JPEG encode frames
- fragment each encoded frame into UDP datagrams
- send tracker status / debug status
- receive shot results back

### On Laptop

The laptop side lives mainly in:

- [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)
- [sam2_bowling_bridge.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/sam2_bowling_bridge.py)

Its jobs are:

- listen on TCP port `5799`
- listen on UDP port `5799`
- accept the Quest TCP control connection
- receive fragmented UDP datagrams
- reassemble complete frame payloads
- decode frame metadata
- save the run
- run analysis
- send tracker status and shot results back over TCP

## 8. Same Port Number For TCP And UDP

The repo uses:

- TCP `5799`
- UDP `5799`

This is valid because TCP and UDP are separate transport-layer namespaces.

So these are not "the same socket."
They are:

- one TCP listener bound to port `5799`
- one UDP listener bound to port `5799`

That keeps configuration simpler for the Quest side.

## 9. Exact TCP Control Packet Format

The control header is defined in:

- [BowlingProtocol.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/BowlingProtocol.cs)
- [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)

The control packet header is **12 bytes**:

1. `magic` - 4 bytes
2. `version` - 2 bytes
3. `packet_type` - 2 bytes
4. `payload_length` - 4 bytes

Important detail:

- The **TCP control** header is `12 bytes`.
- The **UDP frame datagram** header is **not** `12 bytes`; it is `26 bytes`.

This distinction matters because it was easy to blur them together in slides.

### Control Packet Magic / Version

The protocol uses:

- `Magic = 0x424F574C`
- `Version = 1`

The magic is just a recognizable constant that lets the receiver sanity-check that it is parsing the right protocol.

If the magic or version is wrong, the receiver can reject the packet immediately instead of mis-parsing garbage.

## 10. TCP Control Message Types

Packet type IDs are defined in [BowlingProtocol.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/BowlingProtocol.cs).

They are:

- `1` = `Hello`
- `2` = `SessionConfig`
- `3` = `LaneCalibration`
- `4` = `FramePacket`
- `5` = `ShotMarker`
- `6` = `TrackerStatus`
- `7` = `ShotResult`
- `8` = `Ping`
- `9` = `Pong`
- `10` = `Error`

Note:

- `FramePacket` exists as a conceptual packet type in the shared enum
- but actual frame bytes are carried over UDP, not TCP

## 11. What Actually Goes Over TCP

### Quest -> Laptop

The Quest sends JSON payloads over TCP for:

- `hello`
- `session_config`
- `lane_calibration`
- `shot_marker`
- `ping`
- local tracker/debug status mirrors

Examples:

- `hello`: identifies the device and session
- `session_config`: declares frame size, intrinsics, codec, target FPS
- `lane_calibration`: tells the laptop where the lane is in Quest-space
- `shot_marker`: `session_started`, `armed`, `shot_started`, `shot_ended`, `tracker_reset`

### Laptop -> Quest

The laptop sends JSON payloads over TCP for:

- `tracker_status`
- `shot_result`
- `pong`
- `error`

The key point is:

- TCP carries the "meaning" of the session
- UDP carries the high-volume visual data

## 12. Exact UDP Datagram Header Format

The UDP frame datagram header is defined in:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)
- [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)

It is **26 bytes** total.

The fields are:

1. `magic` - 4 bytes
2. `version` - 2 bytes
3. `packet_type` - 2 bytes
4. `frame_id` - 8 bytes
5. `chunk_index` - 2 bytes
6. `chunk_count` - 2 bytes
7. `payload_length` - 2 bytes
8. `total_payload_length` - 4 bytes

This is application-level fragmentation.

That means:

- one logical encoded frame payload may be too large for one UDP datagram
- so the app splits it into smaller chunks itself
- each chunk carries enough metadata for the laptop to reassemble the whole frame

This is important:

- we are not relying on IP fragmentation
- we are doing our own fragmentation at the application layer

## 13. Why We Fragment At The App Layer

Encoded JPEG frames are much larger than a safe single UDP payload.

So the Quest code:

1. builds one full binary frame payload
2. computes how many UDP chunks are needed
3. sends each chunk with the `26-byte` header

This is controlled here:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)

The active configured `maxDatagramPayloadBytes` has been around `1400`, which is a practical size to avoid oversized datagrams on normal networks.

The laptop then reassembles by:

- sender endpoint
- `frame_id`

## 14. What The UDP Payload Contains After Reassembly

After the laptop has all chunks for one `frame_id`, it rebuilds the full frame payload and decodes it with `decode_frame_packet(...)`.

That payload contains:

1. `session_id`
2. `shot_id`
3. `frame_id`
4. `timestamp_us`
5. `camera_position`
6. `camera_rotation`
7. `head_position`
8. `head_rotation`
9. encoded JPEG length
10. encoded JPEG bytes

This is why the transport is more than "just sending images."
Each frame is a bundle of:

- image bytes
- time
- camera pose
- head pose
- session identity
- shot identity

That is important for later analytics and replay.

## 15. Why Session IDs Matter

UDP is connectionless.

So when a UDP frame arrives, the laptop cannot rely on a TCP connection object to know which logical session the frame belongs to.

Instead:

- Quest first registers itself over TCP with `hello` / `session_config`
- the laptop stores the `session_id`
- each UDP frame payload also includes `session_id`
- on the laptop, the reassembled frame is routed to the correct session by `session_id`

This is why `session_config` must happen before frame processing can fully succeed.

If the laptop gets a frame for an unknown `session_id`, it reports:

- `udp_unknown_session_frame`

## 16. Quest Connection Sequence

On Quest, the rough order is:

1. Decide stream source.
2. Open TCP connection to `serverHost:serverPort`.
3. Set up UDP client to the same host/port.
4. Mark transport ready.
5. Send `hello`.
6. Send `session_config`.
7. Send `lane_calibration` if available.
8. Start frame sending loop.

This lives in:

- [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)

Key implementation details:

- TCP has `NoDelay = true` to reduce latency for small control messages.
- UDP client is connected to the configured server host/port.

## 17. Quest Frame Send Sequence

For each frame send attempt, the Quest does:

1. Check that TCP control is ready.
2. Render/copy the current source frame into the stream texture.
3. Read the GPU frame back to CPU memory.
4. JPEG encode the frame.
5. Build the binary frame payload with metadata.
6. Split that payload into UDP chunks.
7. Send each UDP datagram.

That is why the current bottleneck is mostly Quest-side frame preparation, not networking itself.

## 18. Laptop Receive Sequence

On the laptop, UDP processing looks like this:

1. Receive one UDP datagram.
2. Check header size and protocol fields.
3. Group the chunk into a pending frame bucket.
4. Wait until all chunks for that `frame_id` arrive.
5. Reassemble the payload.
6. Decode the frame packet.
7. Find the correct session by `session_id`.
8. Route the frame into the current shot / analysis path.

The pending-frame buffer also expires old incomplete frames after about `5 seconds`, so partial stale fragments do not accumulate forever.

## 19. Reliability Model

This design is intentionally mixed:

### Reliable Pieces

- TCP control messages
- session metadata
- shot markers
- final shot results

### Best-Effort Pieces

- UDP frame chunks
- individual JPEG frames

What this means in practice:

- control correctness is protected
- frame loss is possible
- if one UDP chunk of a frame is lost, the whole logical frame is lost

That is a crucial thing to understand for presentations:

- we do not retransmit lost frame chunks
- we accept some frame loss to keep latency and complexity down

## 20. Why This Design Matches Bowling Better Than A Generic Video Stack

For bowling analysis, a late frame is often worse than a dropped frame.

Why:

- the action is short
- the useful event window is limited
- analysis wants timely data
- we do not want retransmission backlog to push the whole shot later and later

So the transport is designed around:

- preserving control correctness
- preferring timeliness over perfect frame reliability

## 21. Shot Lifecycle On The Wire

The actual shot flow looks like this:

1. Quest connects.
2. Quest sends `hello`.
3. Quest sends `session_config`.
4. Quest may send `lane_calibration`.
5. Quest streams frame payloads over UDP.
6. User presses `X`.
7. Quest sends `shot_started` over TCP.
8. Laptop opens the shot recorder and keeps feeding analysis.
9. User presses `Y`.
10. Quest sends `shot_ended` over TCP.
11. Laptop finalizes the shot and sends `shot_result` over TCP.
12. Quest receives the result and can render replay.

The important conceptual point is:

- the shot boundaries are authoritative over TCP
- the frames themselves are best-effort over UDP

## 22. Why `shot_started` And `shot_ended` Must Not Be UDP

If `shot_started` were a UDP packet and it were lost:

- Quest would think the shot began
- laptop might never open the correct recorder
- frames would arrive but not be associated correctly

If `shot_ended` were lost:

- the laptop might keep the shot open too long
- outputs would be wrong or delayed

So the design keeps shot markers on TCP.

## 23. Current Metadata We Persist

The laptop writes several files per run, including:

- `capture_context.json`
- `session_config.json`
- `lane_calibration.json`
- `shot_events.jsonl`
- `quest_tracker_status.jsonl`
- `raw/frames/*.jpg`
- `raw/frames.jsonl`
- `raw/manifest.json`

This is one of the strengths of the custom transport:

- every stage is inspectable
- we can debug exact frame counts, timestamps, and status events

## 24. Why Debugging Is Easier Than With WebRTC

With this custom transport we can directly inspect:

- whether TCP connected
- whether `hello` arrived
- whether `session_config` arrived
- whether UDP datagrams arrived
- whether chunk reassembly completed
- whether frame decode succeeded
- whether the run folder was created
- whether JPEG files were written

That was a major reason this architecture became the active path.

## 25. Control Timeout: What It Usually Means

A `control timeout` usually means:

- Quest could not establish the TCP connection in time

Common causes:

- wrong laptop IP
- wrong port
- laptop receiver not running
- laptop firewall/network issue
- Quest and laptop not on the same reachable network

This is different from:

- UDP frame loss

If TCP never connects, the pipeline is failing before frame transport even starts.

## 26. Why The Header Sizes Matter In Presentation

You should keep these two facts straight:

### TCP Control Header

- `12 bytes`
- used for framed control messages

### UDP Datagram Header

- `26 bytes`
- used for each UDP fragment of a frame payload

If someone asks "is your custom protocol header 12 bytes or 26 bytes?", the right answer is:

- `12 bytes` for control packets over TCP
- `26 bytes` for per-datagram frame chunk headers over UDP

## 27. Current Performance Reality

The current active transport profile has been roughly:

- target send FPS: `30`
- passthrough send resolution: `960 x 720`
- JPEG quality: `65`

Recent telemetry showed:

- camera source cadence near `30 FPS`
- effective delivered frame rate around `17-18 FPS`
- UDP send time small
- Quest-side GPU readback + JPEG encode as the main bottleneck

So the practical state is:

- the network design is working
- the current throughput cap is mostly Quest-side frame preparation

This matters for Q&A because if someone asks:

- "Is UDP the bottleneck?"

the current honest answer is:

- probably not
- the current dominant cost is Quest-side readback plus JPEG encode

## 28. Why Not Just Max Out The Camera To 60 FPS

Because the camera request rate and the end-to-end delivered useful rate are not the same thing.

Even if the camera API accepts a higher requested max:

- the Quest still has to read back frames
- JPEG encode them
- fragment them
- send them

If the pipeline after capture cannot keep up, requesting `60` can make things worse instead of better.

The correct optimization target is:

- highest stable, useful delivered FPS on the laptop

not:

- highest requested camera FPS in isolation

## 29. Why We Considered Buffering

A Quest-side buffer could help preserve more source frames during the short bowling shot.

But buffering does **not** magically increase sustained throughput.

It only helps if:

- capture is faster than encode/send
- the shot is short
- we are okay flushing buffered frames after the shot ends

So buffering is a product choice:

- better shot fidelity
- but possibly with a short post-shot drain delay

## 30. Why The Laptop Does Not Send Video Back To Quest

The current design sends compact results back, not replay video.

Quest should receive:

- status
- path samples
- shot result
- confidence / failure info

and then render the replay locally.

That is better because:

- Quest is the display device
- shipping rendered replay video back would waste bandwidth
- sending compact result data is cheaper and more flexible

## 31. Common Questions You Might Get

### Q: Why not just use TCP for frames too?

Because reliable retransmission and ordered delivery would increase latency and backlog for frame streaming. For video-like traffic, late frames are often less useful than dropped frames.

### Q: Why not use UDP for everything?

Because control and shot markers must not disappear silently. Losing `shot_started` is much more damaging than losing a frame.

### Q: Why not use WebRTC?

We tried the stack that matched browser/media-style streaming, but in this repo and setup the simpler local TCP+UDP transport was more controllable and more reliable to debug.

### Q: Why do you need both `session_id` and `shot_id`?

`session_id` identifies the Quest/laptop session. `shot_id` identifies a specific bowling shot within that session.

### Q: Why same port for TCP and UDP?

Because TCP and UDP are separate transport namespaces. `5799/TCP` and `5799/UDP` are different sockets.

### Q: What happens if a UDP chunk is lost?

That entire frame is lost, because the laptop cannot reconstruct the full payload without all chunks.

### Q: Why fragment at the application layer?

Because full JPEG frame payloads are too large for one safe UDP datagram, and app-level fragmentation gives us explicit control over chunking and reassembly.

### Q: What is currently limiting your FPS?

Mostly the Quest-side frame preparation path: GPU readback plus JPEG encoding, not the UDP send itself.

### Q: Is the transport solved?

For collection and analysis bring-up: yes, well enough.
For final optimized production performance: not yet.

## 32. The Most Important Truths To Remember

If you only remember a few things for the presentation, remember these:

1. We deliberately split the system into:
   - TCP control plane
   - UDP frame plane

2. TCP protects correctness-critical metadata:
   - session setup
   - calibration
   - shot markers
   - results

3. UDP moves frame data because timeliness matters more than perfect reliability for video-like traffic.

4. The TCP control header is `12 bytes`; the UDP frame-chunk header is `26 bytes`.

5. The current bottleneck is not mostly networking; it is the Quest-side frame readback + JPEG path.

6. The transport is good enough for real alley collection and laptop-side tracking, which is why it replaced the earlier WebRTC-first attempt.

## 33. Code Pointers

If you want to trace this in code before presenting:

- Quest sender:
  - [QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)

- Shared protocol framing:
  - [BowlingProtocol.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/BowlingProtocol.cs)

- Laptop receiver:
  - [quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)

- Higher-level transport spec:
  - [QUEST_LAPTOP_PIPELINE_SPEC.md](C:/Users/student/Quest3BowlingBallTracking/QUEST_LAPTOP_PIPELINE_SPEC.md)

- Pause-state findings:
  - [FINDINGS_SO_FAR.md](C:/Users/student/Quest3BowlingBallTracking/FINDINGS_SO_FAR.md)
