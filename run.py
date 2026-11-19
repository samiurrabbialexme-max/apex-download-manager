#!/usr/bin/env python3
"""Convenience execution launcher for Apex Download Manager."""
import sys
from pathlib import Path

# Ensure root directory is on pythonpath
sys.path.insert(0, str(Path(__file__).parent))

from app.main import main

if __name__ == "__main__":
    main()
