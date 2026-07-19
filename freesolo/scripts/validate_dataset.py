#!/usr/bin/env python3
"""Validate Praxis train and held-out datasets against CONTRACT.md rules."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Dataset paths in evaluate.py are relative to the project root.
os.chdir(ROOT)

sys.argv = [str(SCRIPTS / "evaluate.py"), "--validate-dataset"]
from evaluate import main  # noqa: E402

if __name__ == "__main__":
    main()
