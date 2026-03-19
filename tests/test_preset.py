from __future__ import annotations

from lankvm.config import AppConfig
from lankvm.preset import build_peer_preset, decode_preset, encode_preset


def _sample_listener_config() -> AppConfig:
    return AppConfig(
        machine_id="pc-main",
        role="listener",
        peer_host="192.168.1.31",
        listen_host="0.0.0.0",
        listen_port=24801,
        handoff_edge="right",
        entry_edge="right",
        switch_delay_ms=200,
        shared_secret="lan-kvm-2026",
        heartbeat_ms=400,
        dead_zone_px=4,
        max_mouse_hz=120,
        reconnect_ms=1000,
        failsafe_hotkey=("ctrl", "alt", "f12"),
    )


def test_encode_decode_preset_round_trip() -> None:
    config = _sample_listener_config()

    token = encode_preset(config)
    decoded = decode_preset(token)

    assert decoded == config


def test_build_peer_preset_inverts_edges_and_sets_dialer() -> None:
    token = build_peer_preset(_sample_listener_config(), advertise_host="192.168.50.230")
    peer = decode_preset(token)

    assert peer.role == "dialer"
    assert peer.peer_host == "192.168.50.230"
    assert peer.handoff_edge == "left"
    assert peer.entry_edge == "left"
