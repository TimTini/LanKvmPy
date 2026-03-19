from __future__ import annotations

import base64
import json
import socket

from .config import AppConfig, ConfigError, config_to_mapping, parse_config_mapping


class PresetError(ValueError):
    pass


def encode_preset(config: AppConfig) -> str:
    payload = {
        "version": 1,
        "config": config_to_mapping(config),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_preset(token: str) -> AppConfig:
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PresetError(f"invalid preset token: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise PresetError("unsupported preset version")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise PresetError("preset payload missing config")

    try:
        return parse_config_mapping(config)
    except ConfigError as exc:
        raise PresetError(f"invalid preset config: {exc}") from exc


def build_peer_preset(main_config: AppConfig, *, advertise_host: str | None = None) -> str:
    if main_config.role != "listener":
        raise PresetError("peer preset generation expects the current machine to run as listener")

    host = advertise_host or detect_advertise_host(main_config.peer_host, main_config.listen_port)
    peer_config = AppConfig(
        machine_id="peer-auto",
        role="dialer",
        peer_host=host,
        listen_host="0.0.0.0",
        listen_port=main_config.listen_port,
        handoff_edge=_opposite_edge(main_config.handoff_edge),
        entry_edge=_opposite_edge(main_config.entry_edge),
        switch_delay_ms=main_config.switch_delay_ms,
        shared_secret=main_config.shared_secret,
        heartbeat_ms=main_config.heartbeat_ms,
        dead_zone_px=main_config.dead_zone_px,
        max_mouse_hz=main_config.max_mouse_hz,
        reconnect_ms=main_config.reconnect_ms,
        failsafe_hotkey=main_config.failsafe_hotkey,
    )
    return encode_preset(peer_config)


def build_peer_launch_command(
    main_config: AppConfig,
    *,
    advertise_host: str | None = None,
    python_command: str = "python",
) -> str:
    token = build_peer_preset(main_config, advertise_host=advertise_host)
    return f'{python_command} main.py --preset "{token}"'


def detect_advertise_host(peer_host: str, peer_port: int) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer_host, peer_port))
        return probe.getsockname()[0]
    except OSError as exc:
        raise PresetError(
            "could not auto-detect the local host IP for the peer preset; pass --advertise-host explicitly"
        ) from exc
    finally:
        probe.close()


def _opposite_edge(edge: str) -> str:
    mapping = {
        "left": "right",
        "right": "left",
        "top": "bottom",
        "bottom": "top",
    }
    return mapping[edge]
