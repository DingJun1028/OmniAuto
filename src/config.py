"""Central configuration + pluggable-feature flags for AI Station.

All cloud integrations are OPTIONAL. Each `use_*` flag flips on only
when the relevant key is present in the environment, so the station
runs end-to-end on free local tooling by default.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# ---- Rendering ----
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1280"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "720"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))

# ---- 2. Text parsing (LLM brain) ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
USE_OPENAI = bool(OPENAI_API_KEY)

# ---- 3. TTS ----
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
USE_ELEVENLABS = bool(ELEVENLABS_API_KEY)

# ---- 4. Visuals ----
RUNWAY_API_KEY = os.getenv("RUNWAY_API_KEY", "")
USE_RUNWAY = bool(RUNWAY_API_KEY)

# ---- 6. Cloud storage ----
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
USE_S3 = all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET])

# ---- 7. Provenance DB ----
NCBDB_BASE_URL = os.getenv("NCBDB_BASE_URL", "")
NCBDB_TOKEN = os.getenv("NCBDB_TOKEN", "")
USE_NCBDB = bool(NCBDB_BASE_URL and NCBDB_TOKEN)

# ---- Server ----
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))


def feature_summary() -> dict:
    """Human-readable map of which modules are live vs. using free fallback."""
    return {
        "llm_brain": "openai" if USE_OPENAI else "builtin-free-parser",
        "tts": "elevenlabs" if USE_ELEVENLABS else "edge-tts (free)",
        "visuals": "runway" if USE_RUNWAY else "pillow-gradient (free)",
        "storage": "s3" if USE_S3 else "local",
        "provenance_db": "ncbdb" if USE_NCBDB else "sqlite (local)",
    }
