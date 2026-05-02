from __future__ import annotations

import sys
from pathlib import Path


NC_TESTS_DIR = Path(__file__).resolve().parent

if str(NC_TESTS_DIR) not in sys.path:
    sys.path.append(str(NC_TESTS_DIR))
