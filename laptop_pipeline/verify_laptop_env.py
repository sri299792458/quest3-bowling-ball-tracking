import importlib
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAM2_ROOT = PROJECT_ROOT / "third_party" / "sam2"
CHECKPOINT_PATH = SAM2_ROOT / "checkpoints" / "sam2.1_hiera_tiny.pt"
MIN_CHECKPOINT_BYTES = 100_000_000

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def import_module(name: str):
    module = importlib.import_module(name)
    print(f"ok import {name}")
    return module


def main() -> None:
    print(f"python={sys.version.split()[0]}")
    require(sys.version_info >= (3, 10), "Python 3.10+ is required.")

    torch = import_module("torch")
    torchvision = import_module("torchvision")
    cv2 = import_module("cv2")
    hydra = import_module("hydra")
    omegaconf = import_module("omegaconf")
    iopath = import_module("iopath")
    triton = import_module("triton")

    print(f"torch={torch.__version__}")
    print(f"torchvision={torchvision.__version__}")
    print(f"opencv={cv2.__version__}")
    print(f"hydra={hydra.__version__}")
    print(f"omegaconf={omegaconf.__version__}")
    print(f"triton={triton.__version__}")

    require(torch.cuda.is_available(), "CUDA is not available in this venv.")
    require(torch.version.cuda is not None, "This torch build is CPU-only.")
    gpu_name = torch.cuda.get_device_name(0)
    print(f"cuda={torch.version.cuda}")
    print(f"gpu={gpu_name}")

    require(SAM2_ROOT.exists(), f"Vendored SAM2 root not found: {SAM2_ROOT}")
    require(CHECKPOINT_PATH.exists(), f"SAM2 checkpoint missing: {CHECKPOINT_PATH}")
    require(
        CHECKPOINT_PATH.stat().st_size >= MIN_CHECKPOINT_BYTES,
        f"SAM2 checkpoint looks incomplete: {CHECKPOINT_PATH}",
    )
    print(f"checkpoint={CHECKPOINT_PATH.name} ({CHECKPOINT_PATH.stat().st_size} bytes)")

    sys.path.insert(0, str(SAM2_ROOT))
    os.environ.setdefault("SAM2_REPO_ROOT", str(SAM2_ROOT))

    build_sam = import_module("sam2.build_sam")
    require(
        hasattr(build_sam, "build_sam2_video_predictor"),
        "sam2.build_sam is missing build_sam2_video_predictor",
    )
    require(
        hasattr(build_sam, "build_sam2_camera_predictor"),
        "sam2.build_sam is missing build_sam2_camera_predictor",
    )

    import_module("laptop_pipeline.path_config")
    import_module("laptop_pipeline.warm_sam2_tracker")
    import_module("laptop_pipeline.live_sam2_camera_tracker")
    import_module("laptop_pipeline.sam2_bowling_bridge")

    print("")
    print("Laptop env verification passed.")


if __name__ == "__main__":
    main()
