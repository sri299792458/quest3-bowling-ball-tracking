# Vendored SAM2 Source

This folder contains the repo-local `SAM2` source used by the standalone laptop receiver.

## Origin

- upstream project: `facebookresearch/sam2`
- checkpoint source: `facebook/sam2.1-hiera-tiny` on Hugging Face
- upstream license: [LICENSE](LICENSE)

## Runtime Artifact

The model checkpoint is intentionally not committed. The expected local file is:

```text
third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt
```

Create it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\laptop_receiver\setup_laptop_env.ps1
```

The laptop receiver also accepts explicit overrides through `--sam2-root`, `--sam2-checkpoint`, or the `SAM2_REPO_ROOT` and `SAM2_CHECKPOINT_PATH` environment variables.
