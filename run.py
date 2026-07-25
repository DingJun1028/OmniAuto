"""Entry point helpers for AI Station.

Canonical ways to start the control center (all reach src.app:app / main):
  - `ai-station`            (console script from `pip install -e .`)
  - `python -m src.app`     (module execution)
  - `uvicorn src.app:app`   (ASGI server, used by the Dockerfile)
  - `python run.py`         (this thin wrapper, kept for convenience)
"""
import sys
from pathlib import Path

# allow `python run.py` from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main

if __name__ == "__main__":
    main()
