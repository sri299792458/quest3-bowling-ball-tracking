# Bowling Ball YOLO26s Detector

This folder is the repo-local detector artifact used by the standalone laptop receiver.

## Runtime Checkpoint

- `weights/best.pt`
- Trained run: `bowling_ball_yolo26s_img1280_lightaug_v3`
- Base model: `yolo26s.pt`
- Image size: `1280`
- Class: `bowling_ball`

The checkpoint is a local/downloaded artifact and is ignored by Git. The laptop receiver default points at this local path after the Drive bundle is extracted, so teammates can run:

```powershell
.\.venv\Scripts\python.exe -m laptop_receiver.run_yolo_seed_on_artifact C:\path\to\clip_<session>_<shot>
```

## Training Metadata

- `training/YOLO26S_TRAINING_DECISIONS.md`
- `training/args.yaml`
- `training/results.csv`

## Dataset Artifact

The checkpoint and image/label dataset used for training are intentionally not committed directly. See `dataset/README.md` for the shared Google Drive bundle and expected download/extract layout.

Shared bundle:

```text
https://drive.google.com/file/d/1NC0y6ds9-QXV-j-rVcolQ3ij5DCxdgBl/view?usp=sharing
```
