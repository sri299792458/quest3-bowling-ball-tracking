# Findings So Far

As of 2026-03-29.

## Executive Summary

- The Quest-to-laptop transport problem is solved well enough for collection.
- The WebRTC/Render Streaming path was the wrong path for this repo and setup.
- The active capture path is now `Quest -> TCP control + UDP JPEG frames -> laptop`.
- The classical/lane-first initializer is too brittle to be the main ball-acquisition path.
- A manually reviewed `oracle seed -> SAM2` workflow worked well enough to bootstrap a one-class detector.
- A fine-tuned YOLO initializer plus `SAM2.1 tiny` is the best current direction.
- The current YOLO model works well on our reviewed alley runs and held-out alley clips, but only partially generalizes to the older open-source clips.

## 1. Platform And Transport Findings

- `Unity WebRTC` / Render Streaming was not the right bet here.
- In the Quest WebRTC smoke tests, signaling and data channels worked, but outbound video never encoded or sent.
- The project was then moved to a simpler local architecture:
  - `TCP` for control/session packets
  - `UDP` for JPEG frame payloads
- That path is now working end-to-end in this repo.

Current active implementation:

- Quest sender: [Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs](C:/Users/student/Quest3BowlingBallTracking/Assets/BallTracking/Runtime/QuestBowlingStreamClient.cs)
- Laptop UDP/TCP receiver: [laptop_pipeline/quest_bowling_udp_server.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/quest_bowling_udp_server.py)

## 2. Capture Findings

- Real alley capture is working.
- We recorded `21` Quest runs in [laptop_pipeline/runs/bowling_tests](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bowling_tests).
- The current useful capture profile is:
  - target send FPS: `30`
  - passthrough send resolution: `960 x 720`
  - JPEG quality: `65`
- In practice, delivered/saved FPS is lower than nominal 30 FPS and should be treated as timestamp-driven rather than fixed-FPS ground truth.
- The pipeline now records:
  - raw JPG frames
  - per-frame timestamps
  - camera pose
  - head pose
  - session intrinsics/metadata

Important consequence:

- For analytics, use recorded timestamps, not the nominal configured FPS.

## 3. Tracking Findings Before YOLO

- The original classical initializer was too brittle.
- The main failure mode was not SAM2 tracking itself; it was seeding the wrong object.
- Lane-first selection was also brittle because multiple adjacent lanes are often visible and the system cannot reliably know which lane is “ours” before it knows where the ball is.
- Grounding DINO was not reliable enough as the primary initializer for this exact setup.

Practical conclusion:

- `SAM2` should stay the robust temporal tracker.
- The main problem to solve is one good initial prompt, not replacing SAM2.

## 4. Oracle Workflow Findings

We built an oracle workflow:

- manually box one seed frame per run
- run `SAM2` once from that seed
- review the results
- export reviewed tracks into a detector dataset

Key files:

- [laptop_pipeline/annotate_manual_seeds.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/annotate_manual_seeds.py)
- [laptop_pipeline/batch_track_manual_seeds.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/batch_track_manual_seeds.py)
- [laptop_pipeline/review_oracle_previews.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/review_oracle_previews.py)
- [laptop_pipeline/export_oracle_yolo_dataset.py](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/export_oracle_yolo_dataset.py)

Review state:

- `20 accepted`
- `1 needs_work`

Review file:

- [laptop_pipeline/runs/bowling_tests/oracle_reviews.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bowling_tests/oracle_reviews.json)

Important interpretation:

- The `20` accepted oracle runs are the best current source of “good enough” labels.
- The `needs_work` clip should not be used as a clean replay benchmark until fixed, but the run may still be useful for partial detector work depending on where the failure happens.

## 5. Detector Dataset Findings

Current exported detector dataset:

- [laptop_pipeline/datasets/bowling_ball_oracle_yolo/export_summary.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/datasets/bowling_ball_oracle_yolo/export_summary.json)

Current counts:

- `20` accepted runs exported
- `322` positive images
- `80` negative images

Important design choice:

- We are training a one-class `bowling_ball` detector only to get the initial seed.
- We are not trying to replace `SAM2` with YOLO-only full tracking.

## 6. YOLO Training Findings

We ran a small first-principles hill climb with fixed-budget comparisons.

Summary:

- [laptop_pipeline/runs/yolo_hillclimb/20260329_165618/summary.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_hillclimb/20260329_165618/summary.json)

Compared runs:

- `YOLO11s`, `1280`, no aug
- `YOLO11s`, `1280`, light aug
- `YOLO11n`, `1280`, no aug

Winner:

- `YOLO11s + light aug`

Best hill-climb metrics:

- `mAP50 = 0.98661`
- `recall = 0.96348`
- `mAP50-95 = 0.74135`

Best checkpoint from that sweep:

- [best.pt](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_hillclimb/20260329_165618/training_runs/e02_yolo11s_img1280_lightaug/weights/best.pt)

## 7. Hold-Out Split Findings

We then created a proper run-level hold-out split:

- [laptop_pipeline/datasets/bowling_ball_oracle_yolo_holdout_v1_split.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/datasets/bowling_ball_oracle_yolo_holdout_v1_split.json)

Split:

- `12 train`
- `4 val`
- `4 test`

Hold-out training run:

- [laptop_pipeline/runs/yolo_training_holdout/bowling_ball_yolo11s_img1280_lightaug_holdout_v1/results.csv](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_training_holdout/bowling_ball_yolo11s_img1280_lightaug_holdout_v1/results.csv)

Best validation point:

- best epoch: `51`
- best `mAP50 = 0.96619`
- best recall: `0.93651`

Current practical checkpoint:

- [best.pt](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_training_holdout/bowling_ball_yolo11s_img1280_lightaug_holdout_v1/weights/best.pt)

## 8. Held-Out Alley Evaluation Findings

Held-out seed evaluation summary:

- [laptop_pipeline/runs/yolo_eval/holdout_test_eval_20260329/summary.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_eval/holdout_test_eval_20260329/summary.json)

Result:

- `4 / 4` unseen test runs succeeded

Success rule:

- detector finds an acceptable seed within `seed_frame + 10`
- success threshold used in that eval:
  - confidence >= `0.25`
  - IoU >= `0.25`

Interpretation:

- The model is not just memorizing training clips.
- It does generalize across unseen clips from this same alley/session-style dataset.
- It is still not proven to generalize broadly across different alleys or capture domains.

## 9. Causal YOLO -> SAM2 Findings On Our Alley Runs

We then switched from oracle-assisted frame choice to a more runtime-like behavior:

- YOLO scans forward frame by frame
- stops at the first confident seed
- SAM2 takes over from there

Current batch summary:

- [laptop_pipeline/runs/bowling_tests/yolo_batch_summary.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/bowling_tests/yolo_batch_summary.json)

Current result:

- `20 / 20` accepted runs completed successfully with causal first-lock seeding

Important fix:

- Early causal attempts were wrong because the seed confidence threshold was too low.
- Raising the causal seed threshold to `0.8` fixed the obvious premature false locks.

Current aggregate numbers:

- average seed search time: `2.25 s`
- median seed search time: `2.446 s`
- average searched frames before lock: `43.0`
- median searched frames before lock: `44.0`
- average tracked frames: `34.1`
- median tracked frames: `36.0`
- tracked frame range: `19 -> 64`

Interpretation:

- This is much closer to the intended runtime behavior than the earlier oracle-assisted prompt selection.
- It is good enough to treat `YOLO -> SAM2` as the leading runtime direction.

## 10. Open-Source Clip Generalization Findings

We also ran the current hold-out checkpoint on the two older open-source clips from:

- `C:\\Users\\student\\sam2_bowling_eval\\videos\\bowling_test.mp4`
- `C:\\Users\\student\\sam2_bowling_eval\\videos\\bowling_test_2.mp4`

Result summary:

- [laptop_pipeline/runs/open_source_generalization/20260329_193209/summary.json](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/open_source_generalization/20260329_193209/summary.json)

Outcome:

- `bowling_test_2.mp4`: workable
  - seed at frame `97`
  - seed confidence `0.864`
  - tracked `51` frames (`97 -> 147`)
- `bowling_test.mp4`: weak
  - seed at frame `163`
  - seed confidence `0.815`
  - tracked `27` frames (`163 -> 189`)

Interpretation:

- The model has partial external generalization.
- It does not yet generalize strongly enough to call the problem solved beyond our current Quest alley dataset.
- This is the strongest reason not to overclaim generalization right now.

## 11. What Seems True Right Now

- The transport stack is in a good enough state for collection.
- The classical initializer should not be the main path anymore.
- Grounding DINO is not the best current primary initializer for this setup.
- `YOLO + SAM2` is the best current practical architecture:
  - YOLO for acquisition
  - SAM2 for robust temporal tracking
- The current YOLO model is good on our dataset and held-out alley clips.
- The current YOLO model is not yet broadly generalized.

## 12. Recommended “Pause State”

If the project is on hold, the clean state to remember is:

- Active collection path:
  - Quest -> TCP/UDP -> laptop
- Best current tracking architecture:
  - `YOLO seed -> SAM2.1 tiny`
- Best current checkpoint:
  - [best.pt](C:/Users/student/Quest3BowlingBallTracking/laptop_pipeline/runs/yolo_training_holdout/bowling_ball_yolo11s_img1280_lightaug_holdout_v1/weights/best.pt)
- Best current known limitations:
  - actual delivered FPS is below nominal 30 FPS
  - model generalization outside the current alley/domain is still mixed
  - world-aligned lane replay/analytics are not finished yet

## 13. If We Resume Later

The next sensible resumptions would be:

1. Integrate the current YOLO checkpoint into the live laptop pipeline as the default seeder.
2. Collect more cross-domain data if broader generalization matters.
3. Build lane-space replay/analytics on top of the tracked trajectory after ball acquisition is stable.
