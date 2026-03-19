from __future__ import annotations

import argparse
import logging
import os

from .app import LanKvmApp
from .config import load_config
from .preset import build_peer_launch_command, decode_preset


def main() -> int:
    parser = argparse.ArgumentParser(description="LAN KVM for two Windows machines")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--log-level", default="DEBUG", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--preset", help="Base64 preset token for no-config peer startup")
    parser.add_argument("--print-peer-launch", action="store_true", help="Print a ready-to-run peer command derived from the local config")
    parser.add_argument("--advertise-host", help="Override the host/IP that should be embedded into --print-peer-launch")
    parser.add_argument("--peer-python", default="python", help="Python command to include in --print-peer-launch output")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.print_peer_launch:
        config = load_config(args.config)
        print(
            build_peer_launch_command(
                config,
                advertise_host=args.advertise_host,
                python_command=args.peer_python,
            )
        )
        return 0

    if os.name != "nt":
        raise SystemExit("This application only supports Windows hosts")

    config = decode_preset(args.preset) if args.preset else load_config(args.config)
    app = LanKvmApp(config)
    app.run()
    return 0
