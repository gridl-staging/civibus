from __future__ import annotations

import sys
from pathlib import Path


JURISDICTIONS_DIR = Path(__file__).resolve().parent

if str(JURISDICTIONS_DIR) not in sys.path:
    # Make shared test helpers importable without allowing this directory to
    # shadow standard-library or installed modules during pytest startup.
    sys.path.append(str(JURISDICTIONS_DIR))
