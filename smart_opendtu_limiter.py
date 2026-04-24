#!/usr/bin/env python3
"""Smart Power Limiter for Hoymiles HMS inverters with OpenDTU.

This is a thin backwards-compatible wrapper around the src/ package.
For new code, import directly from src.

Dynamic feedback controller that raises the inverter limit when partially
shaded panels leave headroom on sunny ones — without exceeding the legal
feed-in limit. Uses non-persistent (RAM-only) limit commands, so zero
flash wear on the inverter.

Requires a ``.env`` file next to this script. See ``.env.example``.
"""

import sys
from pathlib import Path

# Add src/ to path for direct execution
sys.path.insert(0, str(Path(__file__).parent))

from src.cli import main

if __name__ == "__main__":
    main()
