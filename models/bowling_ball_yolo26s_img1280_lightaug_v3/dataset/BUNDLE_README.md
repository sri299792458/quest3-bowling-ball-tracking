# Bowling Ball YOLO26s Training Bundle

This bundle is shared with teammates through Google Drive:

```text
https://drive.google.com/file/d/1NC0y6ds9-QXV-j-rVcolQ3ij5DCxdgBl/view?usp=sharing
```

Extract this zip into:

```text
models/bowling_ball_yolo26s_img1280_lightaug_v3/
```

## Contents

- `dataset/bowling_ball_oracle_yolo/`: exported YOLO images and labels
- `dataset/dataset.yaml`: relative YOLO dataset config
- `metadata/export_summary.json`: export settings and per-run counts
- `metadata/bowling_ball_combined_v2_split.json`: train/val/test run split
- `metadata/manual_seed_and_review/`: manual seed and oracle review bookkeeping
- `training_run/`: args, results, and training decision notes for the selected YOLO26s run
- `training_tools/`: scripts used to annotate manual seeds, run oracle SAM2, review tracks, export YOLO data, and train the detector
- `weights/best.pt`: selected YOLO26s checkpoint

## Train Again

From a repo clone with dependencies installed:

```powershell
.\.venv\Scripts\python.exe .\models\bowling_ball_yolo26s_img1280_lightaug_v3\training_tools\training\train_bowling_ball_yolo.py --data .\models\bowling_ball_yolo26s_img1280_lightaug_v3\dataset\dataset.yaml --export-summary .\models\bowling_ball_yolo26s_img1280_lightaug_v3\metadata\export_summary.json --model yolo26s.pt --project .\models\bowling_ball_yolo26s_img1280_lightaug_v3\runs\yolo_training --name bowling_ball_yolo26s_img1280_lightaug_v3 --imgsz 1280 --epochs 120 --patience 25 --batch 2 --optimizer auto --hsv-h 0.01 --hsv-s 0.3 --hsv-v 0.3 --translate 0.05 --scale 0.15 --fliplr 0.5 --mosaic 0.0 --mixup 0.0 --copy-paste 0.0 --erasing 0.0
```

The original selected training run was:

```text
bowling_ball_yolo26s_img1280_lightaug_v3
```
