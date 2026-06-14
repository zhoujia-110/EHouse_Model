# -*- coding: utf-8 -*-
"""PyCharm-friendly preprocessing GUI entry."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ehouse_model.gui.preprocess_app import main


if __name__ == "__main__":
    raise SystemExit(main())
