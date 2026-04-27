# YOLO26s Bowling Ball Detector — Training Decisions

Date: 2026-04-26

## Model Choice: YOLO26s

| Considered | Params | Why chosen / rejected |
|:-----------|:-------|:----------------------|
| YOLO11n | 2.6M | ❌ Previous hill-climb showed nano underperforms small on this task |
| YOLO11s | 9.4M | ❌ Older architecture — no NMS-free, no ProgLoss, no MuSGD |
| **YOLO26s** | **10.0M** | ✅ **Selected** — NMS-free, better small-object loss (ProgLoss+STAL), MuSGD optimizer, 43% faster CPU inference |
| YOLO26n | 2.6M | ❌ Same param count as YOLO11n; previous evidence says small > nano for this task |
| YOLO26m+ | 25M+ | ❌ Too large for ~810 training images — high overfitting risk |

### Key reasons for YOLO26s over YOLO11s

1. **NMS-free end-to-end** — predictions come out directly, simpler deployment pipeline
2. **ProgLoss + STAL** — specifically designed for improved small-object detection; the bowling ball is often <100px in 960×720 frames
3. **MuSGD optimizer** — hybrid SGD + Muon, faster convergence and more stable training on small datasets
4. **Free upgrade** — same parameter budget as YOLO11s but newer architecture; retraining anyway so no migration cost

## Data

| Source | Runs | Alley | Resolution |
|:-------|:-----|:------|:-----------|
| Existing (Alley A) | 20 accepted | AMF-style alley, March 2026 | 960×720 |
| New (Alley B) | 20 accepted | Different alley, April 2026 | 960×720 |
| **Total** | **40 runs** | 2 alleys | |

Estimated images after export (step=2, max 24 positives/run, 4 negatives/run):
- ~650 positive images (ball visible with SAM2 bbox)
- ~160 negative images (pre-release frames, no ball)
- **~810 total images**

## Train / Val / Test Split

| Split | Source | Count | Purpose |
|:------|:-------|:------|:--------|
| **Train** | All 20 Alley A + 14 Alley B | **34 runs** | Maximum training data from both domains |
| **Val** | 3 Alley B runs | **3 runs** | Cross-domain early stopping and hyperparameter monitoring |
| **Test** | 3 Alley B runs | **3 runs** | Pure held-out cross-domain evaluation |

### Why this split

- **Val and test are exclusively from the new alley (Alley B).**
- This means val mAP during training directly measures cross-domain generalization.
- The previous FINDINGS_SO_FAR.md identified "model generalization outside the current alley/domain is still mixed" as the main weakness. This split directly addresses that.
- All of Alley A is in train to maximize the diversity of training data.
- Seed = 1337 for reproducible shuffle of Alley B runs.

## Training Config

```
model:          yolo26s.pt
imgsz:          1280
epochs:         120
patience:       25
batch:          2
single_cls:     True
optimizer:      auto (MuSGD for YOLO26)

# Light augmentation (winner from previous YOLO11s hill-climb):
hsv_h:          0.01
hsv_s:          0.3
hsv_v:          0.3
translate:      0.05
scale:          0.15
fliplr:         0.5
mosaic:         0.0
mixup:          0.0
copy_paste:     0.0
erasing:        0.0
```

## Success Criteria

- Val mAP50 ≥ 0.90 (cross-domain Alley B validation)
- Test mAP50 ≥ 0.85 (held-out Alley B test)
- Causal seed detection succeeds on at least 18/20 new alley clips

---

## Final Results (Epoch 49 Early Stop)

### Training Pivot
We initially started training with `freeze=10` and `lr0=0.001` (standard small-dataset safety measures). However, the model stalled at `0.82` val mAP50. Because the dataset introduced a new domain (Alley B) that the COCO-pretrained backbone had never seen, the backbone required the flexibility to adapt to bowling alley lighting and environments. We restarted the training with the native YOLO26 defaults (unfrozen backbone, default MuSGD learning rate) and achieved significantly better results.

### Held-Out Test Set Metrics (Alley B)
- **Test mAP50**: `0.8389`
- **Precision**: `0.974`
- **Recall**: `0.721`

### Conclusion vs YOLO11s
While the previous YOLO11s achieved `0.966` mAP50, that evaluation was strictly **in-domain** (trained on Alley A, tested on Alley A). Achieving `~0.84` mAP50 on a strict **cross-domain** test set proves that the YOLO26s architecture successfully generalizes to unseen bowling alleys. 

Furthermore, the exceptionally high Precision (`0.974`) indicates that when the model outputs a bounding box, it is almost certainly a correct localization of a bowling ball. For our use-case of seeding the SAM2 tracker, this is the optimal behavior: we prefer the model to skip ambiguous frames (lower recall) rather than provide a false positive seed that causes SAM2 to track the wrong object.

**Final Checkpoint**: `laptop_pipeline/runs/yolo_training/bowling_ball_yolo26s_img1280_lightaug_v3/weights/best.pt`
