from __future__ import annotations

import pytest


pytest.importorskip("msgpack")

from lankvm.protocol import FrameCodec, ProtocolError


def test_frame_codec_round_trip() -> None:
    codec = FrameCodec("secret")
    payload = {"type": "mouse_move", "dx": 12, "dy": -6}

    encoded = codec.encode(payload)
    decoded = codec.feed(encoded)

    assert decoded == [payload]


def test_frame_codec_rejects_tampered_payload() -> None:
    codec = FrameCodec("secret")
    encoded = bytearray(codec.encode({"type": "heartbeat"}))
    encoded[-1] ^= 0x01

    with pytest.raises(ProtocolError):
        codec.feed(bytes(encoded))
