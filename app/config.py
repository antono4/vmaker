"""Runtime configuration for the MiniMax H3 Video Maker.

Everything is read from environment variables at import time so the app can be
configured from a systemd unit, docker-compose file, or the ``run.sh`` script.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("H3_DATA_DIR", ROOT / "data"))
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_DIR = DATA_DIR / "uploads"
JOBS_FILE = DATA_DIR / "jobs.json"

HOST = os.environ.get("H3_HOST", "0.0.0.0")
PORT = int(os.environ.get("H3_PORT", "12000"))

# --- Backends -------------------------------------------------------------
# local : an SGLang / vLLM server hosting MiniMax-H3 (POST /v1/videos ...)
# api   : MiniMax Open Platform (https://api.minimax.io or api.minimaxi.com)
# demo  : fully offline renderer, no GPU and no credentials required
LOCAL_BASE_URL = os.environ.get("H3_LOCAL_BASE_URL", "http://127.0.0.1:30010")
LOCAL_BASE_URL_REF = os.environ.get("H3_LOCAL_BASE_URL_REF", "http://127.0.0.1:30011")

MINIMAX_API_BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.io")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")

DEFAULT_BACKEND = os.environ.get("H3_DEFAULT_BACKEND", "demo")

# HTTP timeouts (seconds)
CONNECT_TIMEOUT = float(os.environ.get("H3_CONNECT_TIMEOUT", "10"))
READ_TIMEOUT = float(os.environ.get("H3_READ_TIMEOUT", "600"))

MAX_UPLOAD_MB = int(os.environ.get("H3_MAX_UPLOAD_MB", "64"))

# Official model identifiers, surfaced in the UI so users copy the right ones.
MODEL_ID = "MiniMaxAI/MiniMax-H3"
TURBO_LORA_ID = "MiniMaxAI/MiniMax-H3-Turbo-Lora"

VIDEO_MODEL = "MiniMax-H3"


def ensure_dirs() -> None:
    for path in (DATA_DIR, OUTPUT_DIR, UPLOAD_DIR):
        path.mkdir(parents=True, exist_ok=True)
