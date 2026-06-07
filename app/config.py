"""Configuration, driven by environment variables (12-factor style)."""
from __future__ import annotations

import os
from pathlib import Path


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


# --- Paths -----------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_DIR = DATA_DIR / "uploads"
CHECKPOINT_DIR = Path(os.getenv("ACE_CHECKPOINT_DIR", str(DATA_DIR / "checkpoints")))

for d in (OUTPUT_DIR, UPLOAD_DIR, CHECKPOINT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- Model -----------------------------------------------------------------
# Default model variant. The 3.5B v1 model fits comfortably in 16GB VRAM.
# Set ACE_MODEL=ACE-Step/ACE-Step-v1.5-3.5B (or the XL variant) to override.
DEFAULT_MODEL = os.getenv("ACE_MODEL", "ACE-Step/ACE-Step-v1-3.5B")

# Optional Lyric2Vocal LoRA (generates isolated/pure vocal stems from lyrics).
# Left empty by default - base model already sings lyrics. Set to a HuggingFace
# repo id or local path to enable the pure-vocal sub-task.
VOCAL_LORA = os.getenv("ACE_VOCAL_LORA", "").strip()

# Precision / memory knobs (all map onto ACE-Step pipeline args).
DTYPE = os.getenv("ACE_DTYPE", "bfloat16")                 # bfloat16 | float32
TORCH_COMPILE = _bool(os.getenv("ACE_TORCH_COMPILE"), False)
CPU_OFFLOAD = _bool(os.getenv("ACE_CPU_OFFLOAD"), False)    # turn on if VRAM tight
OVERLAPPED_DECODE = _bool(os.getenv("ACE_OVERLAPPED_DECODE"), False)
DEVICE_ID = int(os.getenv("ACE_DEVICE_ID", "0"))

# When true, the backend never tries to import torch/acestep. Useful for
# developing the UI on a machine with no GPU. Generation will return a stub.
DEMO_MODE = _bool(os.getenv("DEMO_MODE"), False)

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
MAX_DURATION = float(os.getenv("MAX_DURATION", "240"))     # seconds, safety cap
