from __future__ import annotations

from collections.abc import Mapping
import hashlib
import hmac
import struct
from typing import Any


PROTOCOL_VERSION = 1

try:
    import msgpack  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised indirectly when dependency is missing
    msgpack = None


class ProtocolError(RuntimeError):
    pass


class FrameCodec:
    def __init__(self, shared_secret: str):
        if not shared_secret:
            raise ValueError("shared_secret must not be empty")
        if msgpack is None:
            raise RuntimeError("msgpack is required. Install dependencies with `python -m pip install -e .`")

        self._secret = shared_secret.encode("utf-8")
        self._buffer = bytearray()

    def encode(self, payload: Mapping[str, Any]) -> bytes:
        payload_bytes = msgpack.packb(dict(payload), use_bin_type=True)
        mac = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
        envelope = {
            "payload": payload_bytes,
            "mac": mac,
        }
        body = msgpack.packb(envelope, use_bin_type=True)
        return struct.pack(">I", len(body)) + body

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(chunk)
        frames: list[dict[str, Any]] = []

        while len(self._buffer) >= 4:
            frame_length = struct.unpack(">I", self._buffer[:4])[0]
            if len(self._buffer) < 4 + frame_length:
                break

            raw_body = bytes(self._buffer[4 : 4 + frame_length])
            del self._buffer[: 4 + frame_length]
            envelope = msgpack.unpackb(raw_body, raw=False)
            payload_bytes = envelope.get("payload")
            mac = envelope.get("mac")
            if not isinstance(payload_bytes, (bytes, bytearray)) or not isinstance(mac, (bytes, bytearray)):
                raise ProtocolError("invalid frame envelope")

            expected_mac = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
            if not hmac.compare_digest(mac, expected_mac):
                raise ProtocolError("frame HMAC mismatch")

            payload = msgpack.unpackb(payload_bytes, raw=False)
            if not isinstance(payload, dict):
                raise ProtocolError("frame payload must be a map")
            frames.append(payload)

        return frames
