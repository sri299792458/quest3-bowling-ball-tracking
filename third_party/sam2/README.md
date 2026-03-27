# Vendored SAM2 Source

This folder contains the vendored `SAM2` source used by the laptop pipeline in this repo.

## Origin

- upstream project: `facebookresearch/sam2`
- local camera-predictor support preserved from the real-time `SAM2` reference implementation we evaluated during development

## Used By

- [`../../laptop_pipeline/warm_sam2_tracker.py`](../../laptop_pipeline/warm_sam2_tracker.py)
- [`../../laptop_pipeline/live_sam2_camera_tracker.py`](../../laptop_pipeline/live_sam2_camera_tracker.py)

## Notes

- the model checkpoint is not committed
- `laptop_pipeline/setup_laptop_env.ps1` downloads `sam2.1_hiera_tiny.pt` into `third_party/sam2/checkpoints`
- the upstream license is included as [`LICENSE`](LICENSE)
