"""Entry point: start the AI Station control center."""
import sys
from pathlib import Path

# allow `python run.py` from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main

if __name__ == "__main__":
    main()
