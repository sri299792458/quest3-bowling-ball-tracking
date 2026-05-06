# YOLO26s Training Dataset Artifact

The training dataset and checkpoint are shared external artifacts instead of Git-tracked files.

Public Hugging Face dataset:

```text
https://huggingface.co/datasets/sri299792458/quest-bowling-ball-yolo
```

The Hugging Face repo contains the YOLO images/labels, split metadata, export summary, and training notes. It does not include the runtime checkpoint.

Google Drive bundle:

```text
https://drive.google.com/file/d/1NC0y6ds9-QXV-j-rVcolQ3ij5DCxdgBl/view?usp=sharing
```

The Drive bundle includes both the dataset and `weights/best.pt`.

When you download `bowling_ball_yolo26s_training_bundle.zip`, extract it into:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/
```

Do not extract it inside `dataset/`; the zip contains both `dataset/` and `weights/` top-level folders.

## Expected Layout After Download

Extract or copy the dataset here:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/dataset/bowling_ball_oracle_yolo/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
```

Extract or copy the checkpoint here:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/weights/best.pt
```

Then train/evaluate with:

```powershell
yolo detect train model=yolo26s.pt data=models/bowling_ball_yolo26s_img1280_lightaug_v3/dataset/dataset.yaml imgsz=1280
```

## Metadata Included In Git

- `dataset.yaml`: relative dataset config for this repo layout
- `export_summary.json`: export settings and per-run counts
- `bowling_ball_combined_v2_split.json`: train/val/test run split

Historical absolute paths may appear in the committed training metadata, but normal use should follow the repo-local layout above after extracting the bundle.
