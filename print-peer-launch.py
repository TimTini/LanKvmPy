from __future__ import annotations

from pathlib import Path
import sys

from lankvm.cli import main


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.toml"
DEFAULT_ADVERTISE_HOST = "192.168.50.230"


if __name__ == "__main__":
    sys.argv = [
        sys.argv[0],
        "--config",
        str(DEFAULT_CONFIG),
        "--print-peer-launch",
        "--advertise-host",
        DEFAULT_ADVERTISE_HOST,
        *sys.argv[1:],
    ]
    raise SystemExit(main())
