import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAPTOP_PIPELINE_ROOT = PROJECT_ROOT / "laptop_pipeline"
DEFAULT_EVAL_ROOT = Path(os.environ.get("SAM2_BOWLING_EVAL_ROOT", r"C:\Users\student\sam2_bowling_eval"))
