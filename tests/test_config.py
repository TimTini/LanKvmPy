from __future__ import annotations

from pathlib import Path

from lankvm.config import load_config


def test_load_config_parses_expected_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'machine_id = "machine-a"',
                'role = "dialer"',
                'peer_host = "192.168.1.31"',
                'listen_host = "0.0.0.0"',
                "listen_port = 24801",
                'handoff_edge = "right"',
                'entry_edge = "right"',
                "switch_delay_ms = 200",
                'shared_secret = "secret"',
                "heartbeat_ms = 400",
                "dead_zone_px = 4",
                "max_mouse_hz = 120",
                "reconnect_ms = 1000",
                'failsafe_hotkey = ["ctrl", "alt", "f12"]',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.machine_id == "machine-a"
    assert config.role == "dialer"
    assert config.listen_port == 24801
    assert config.failsafe_hotkey == ("ctrl", "alt", "f12")
