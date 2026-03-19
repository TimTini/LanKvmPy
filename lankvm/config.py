from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import tomllib


Edge = Literal["left", "right", "top", "bottom"]
Role = Literal["dialer", "listener"]
VALID_EDGES = {"left", "right", "top", "bottom"}
VALID_ROLES = {"dialer", "listener"}


@dataclass(frozen=True)
class AppConfig:
    machine_id: str
    role: Role
    peer_host: str
    listen_host: str
    listen_port: int
    handoff_edge: Edge
    entry_edge: Edge
    switch_delay_ms: int
    shared_secret: str
    heartbeat_ms: int
    dead_zone_px: int
    max_mouse_hz: int
    reconnect_ms: int
    failsafe_hotkey: tuple[str, ...]


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    return parse_config_mapping(raw)


def parse_config_mapping(raw: dict[str, Any]) -> AppConfig:
    return AppConfig(
        machine_id=_require_str(raw, "machine_id"),
        role=_require_role(raw, "role"),
        peer_host=_require_str(raw, "peer_host"),
        listen_host=_optional_str(raw, "listen_host", "0.0.0.0"),
        listen_port=_require_int(raw, "listen_port", minimum=1, maximum=65535, default=24801),
        handoff_edge=_require_edge(raw, "handoff_edge"),
        entry_edge=_require_edge(raw, "entry_edge"),
        switch_delay_ms=_require_int(raw, "switch_delay_ms", minimum=1, maximum=2000, default=200),
        shared_secret=_require_str(raw, "shared_secret"),
        heartbeat_ms=_require_int(raw, "heartbeat_ms", minimum=100, maximum=5000, default=400),
        dead_zone_px=_require_int(raw, "dead_zone_px", minimum=1, maximum=64, default=4),
        max_mouse_hz=_require_int(raw, "max_mouse_hz", minimum=30, maximum=240, default=120),
        reconnect_ms=_require_int(raw, "reconnect_ms", minimum=100, maximum=10000, default=1000),
        failsafe_hotkey=_require_hotkey(raw, "failsafe_hotkey", ("ctrl", "alt", "f12")),
    )


def config_to_mapping(config: AppConfig) -> dict[str, Any]:
    return {
        "machine_id": config.machine_id,
        "role": config.role,
        "peer_host": config.peer_host,
        "listen_host": config.listen_host,
        "listen_port": config.listen_port,
        "handoff_edge": config.handoff_edge,
        "entry_edge": config.entry_edge,
        "switch_delay_ms": config.switch_delay_ms,
        "shared_secret": config.shared_secret,
        "heartbeat_ms": config.heartbeat_ms,
        "dead_zone_px": config.dead_zone_px,
        "max_mouse_hz": config.max_mouse_hz,
        "reconnect_ms": config.reconnect_ms,
        "failsafe_hotkey": list(config.failsafe_hotkey),
    }


def _require_edge(raw: dict, field: str) -> Edge:
    value = _require_str(raw, field).lower()
    if value not in VALID_EDGES:
        raise ConfigError(f"{field} must be one of {sorted(VALID_EDGES)}")
    return value  # type: ignore[return-value]


def _require_role(raw: dict, field: str) -> Role:
    value = _require_str(raw, field).lower()
    if value not in VALID_ROLES:
        raise ConfigError(f"{field} must be one of {sorted(VALID_ROLES)}")
    return value  # type: ignore[return-value]


def _require_hotkey(raw: dict, field: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if field not in raw:
        return default

    value = raw[field]
    if isinstance(value, str):
        tokens = tuple(part.strip().lower() for part in value.split("+") if part.strip())
    elif isinstance(value, list):
        tokens = tuple(str(part).strip().lower() for part in value if str(part).strip())
    else:
        raise ConfigError(f"{field} must be a string or list of strings")

    if len(tokens) < 2:
        raise ConfigError(f"{field} must contain at least two keys")
    return tokens


def _require_str(raw: dict, field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_str(raw: dict, field: str, default: str) -> str:
    value = raw.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _require_int(
    raw: dict,
    field: str,
    *,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int:
    if field not in raw:
        if default is None:
            raise ConfigError(f"{field} is required")
        return default

    value = raw[field]
    if not isinstance(value, int):
        raise ConfigError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ConfigError(f"{field} must be between {minimum} and {maximum}")
    return value
