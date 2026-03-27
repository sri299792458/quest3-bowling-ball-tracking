import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAPTOP_PIPELINE_ROOT = PROJECT_ROOT / "laptop_pipeline"
THIRD_PARTY_ROOT = PROJECT_ROOT / "third_party"
DEFAULT_SAM2_ROOT = Path(os.environ.get("SAM2_REPO_ROOT", THIRD_PARTY_ROOT / "sam2"))
DEFAULT_CHECKPOINTS_ROOT = DEFAULT_SAM2_ROOT / "checkpoints"
