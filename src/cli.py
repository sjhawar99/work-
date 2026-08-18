"""Run the CLI straight from a fresh clone: `python src/cli.py version`.

The installed `apex` console script is the normal entry point; this shim exists so the
tool runs before anyone has run `pip install -e .` (spec §15).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apex_ads.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
