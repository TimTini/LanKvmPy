from __future__ import annotations

import argparse
import logging
import os

from .app import LanKvmApp
from .config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="LAN KVM for two Windows machines")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if os.name != "nt":
        raise SystemExit("This application only supports Windows hosts")

    config = load_config(args.config)
    app = LanKvmApp(config)
    app.run()
    return 0
