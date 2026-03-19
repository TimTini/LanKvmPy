from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .config import AppConfig
from .events import KeyEvent, MouseButtonEvent, MouseMoveEvent, MouseWheelEvent
from .protocol import FrameCodec, PROTOCOL_VERSION
from .screen import EdgeDetector, ScreenInfo, is_at_edge, normalize_on_edge, position_for_entry
from .state import SessionMode, SessionState
from .transport import PeerConnector, TransportSession
from .windows.backend import WindowsInputBackend
from .windows import win32


class MouseMotionCoalescer:
    def __init__(self, max_hz: int, sender: Callable[[int, int], None]) -> None:
        self._interval = 1.0 / max_hz
        self._sender = sender
        self._lock = threading.Lock()
        self._pending_dx = 0
        self._pending_dy = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lan-kvm-mouse-coalescer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def add(self, dx: int, dy: int) -> None:
        with self._lock:
            self._pending_dx += dx
            self._pending_dy += dy

    def reset(self) -> None:
        with self._lock:
            self._pending_dx = 0
            self._pending_dy = 0

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                dx = self._pending_dx
                dy = self._pending_dy
                self._pending_dx = 0
                self._pending_dy = 0
            if dx or dy:
                self._sender(dx, dy)


class LanKvmApp:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("lankvm")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._state = SessionState()
        self._edge_detector = EdgeDetector(
            config.handoff_edge,
            delay_ms=config.switch_delay_ms,
            dead_zone_px=config.dead_zone_px,
        )
        self._backend = WindowsInputBackend(self, self._logger.getChild("windows"))
        self._connector = PeerConnector(
            role=config.role,
            listen_host=config.listen_host,
            listen_port=config.listen_port,
            peer_host=config.peer_host,
            reconnect_ms=config.reconnect_ms,
            codec_factory=lambda: FrameCodec(config.shared_secret),
            logger=self._logger.getChild("transport"),
            on_frame=self._handle_frame,
            on_connected=self._handle_connected,
            on_disconnected=self._handle_disconnected,
        )
        self._motion = MouseMotionCoalescer(config.max_mouse_hz, self._send_mouse_delta)
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="lan-kvm-heartbeat", daemon=True)
        self._peer_machine_id: str | None = None
        self._peer_screen: ScreenInfo | None = None
        self._pressed_tokens: set[str] = set()
        self._last_local_mouse_pt: tuple[int, int] | None = None

    def run(self) -> None:
        self._logger.info("starting LAN KVM app for machine_id=%s role=%s", self._config.machine_id, self._config.role)
        self._backend.start()
        self._motion.start()
        self._connector.start()
        self._heartbeat_thread.start()

        try:
            while not self._stop.wait(0.5):
                continue
        except KeyboardInterrupt:
            self._logger.info("keyboard interrupt received, shutting down")
        finally:
            self._shutdown()

    def stop(self) -> None:
        self._stop.set()

    def handle_mouse_move(self, event: MouseMoveEvent) -> bool:
        with self._lock:
            if self._state.mode == SessionMode.CONTROLLING_PEER:
                if self._last_local_mouse_pt is None:
                    self._last_local_mouse_pt = (event.x, event.y)
                    return True

                dx = event.x - self._last_local_mouse_pt[0]
                dy = event.y - self._last_local_mouse_pt[1]
                self._last_local_mouse_pt = (event.x, event.y)
                if dx or dy:
                    self._motion.add(dx, dy)
                return True

            if self._state.mode == SessionMode.CONTROLLED_BY_PEER:
                return False

            if not self._peer_ready():
                self._edge_detector.reset()
                return False

            screen = self._backend.screen_info()
            normalized = self._edge_detector.update(event.x, event.y, screen, event.monotonic_time)
            if normalized is None:
                return False

            self._begin_local_capture(normalized, event.x, event.y)
            return True

    def handle_mouse_button(self, event: MouseButtonEvent) -> bool:
        with self._lock:
            if self._state.mode != SessionMode.CONTROLLING_PEER:
                return False
            self._connector.send(
                {
                    "type": "mouse_button",
                    "button": event.button,
                    "is_down": event.is_down,
                    "from_machine_id": self._config.machine_id,
                }
            )
            return True

    def handle_mouse_wheel(self, event: MouseWheelEvent) -> bool:
        with self._lock:
            if self._state.mode != SessionMode.CONTROLLING_PEER:
                return False
            self._connector.send(
                {
                    "type": "wheel",
                    "delta": event.delta,
                    "from_machine_id": self._config.machine_id,
                }
            )
            return True

    def handle_key_event(self, event: KeyEvent) -> bool:
        token = _vk_to_token(event.vk_code)
        with self._lock:
            if event.is_down:
                self._pressed_tokens.add(token)
            else:
                self._pressed_tokens.discard(token)

            if self._state.mode != SessionMode.CONTROLLING_PEER:
                return False

            if self._failsafe_pressed():
                self._logger.warning("failsafe hotkey pressed, reclaiming local control")
                self._release_local_capture(restore_edge=self._config.handoff_edge, normalized=self._state.last_local_handoff_norm)
                return True

            self._connector.send(
                {
                    "type": "key_down" if event.is_down else "key_up",
                    "vk_code": event.vk_code,
                    "scan_code": event.scan_code,
                    "flags": event.flags,
                    "from_machine_id": self._config.machine_id,
                }
            )
            return True

    def _begin_local_capture(self, normalized: float, x: int, y: int) -> None:
        self._state.begin_local_capture(self._peer_machine_id, normalized)
        self._edge_detector.reset()
        self._motion.reset()
        self._last_local_mouse_pt = (x, y)
        local_screen = self._backend.screen_info()
        local_hold_position = position_for_entry(self._config.handoff_edge, normalized, local_screen)
        self._backend.set_cursor_position(*local_hold_position)
        self._connector.send(
            {
                "type": "enter_remote",
                "normalized": normalized,
                "from_machine_id": self._config.machine_id,
            }
        )
        self._logger.info("handoff started toward peer=%s normalized=%.3f", self._peer_machine_id, normalized)

    def _release_local_capture(self, *, restore_edge: str, normalized: float) -> None:
        self._state.release_local_capture()
        self._motion.reset()
        self._edge_detector.reset()
        self._last_local_mouse_pt = None
        self._pressed_tokens.clear()
        restore_pos = position_for_entry(restore_edge, normalized, self._backend.screen_info())
        self._backend.set_cursor_position(*restore_pos)

    def _peer_ready(self) -> bool:
        session = self._connector.session
        return session is not None and session.connected and self._peer_screen is not None and self._peer_machine_id is not None

    def _handle_connected(self, session: TransportSession) -> None:
        with self._lock:
            self._peer_machine_id = None
            self._peer_screen = None

        hello = {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "machine_id": self._config.machine_id,
            "screen": _screen_to_payload(self._backend.screen_info()),
            "handoff_edge": self._config.handoff_edge,
            "entry_edge": self._config.entry_edge,
        }
        session.send(hello)
        self._logger.info("hello sent to %s", session.peer_name)

    def _handle_disconnected(self, reason: str) -> None:
        with self._lock:
            previous = self._state.disconnect()
            self._peer_machine_id = None
            self._peer_screen = None
            self._motion.reset()
            self._edge_detector.reset()
            self._last_local_mouse_pt = None
            self._pressed_tokens.clear()

            if previous == SessionMode.CONTROLLING_PEER:
                restore = self._state.last_local_handoff_norm
                self._backend.set_cursor_position(*position_for_entry(self._config.handoff_edge, restore, self._backend.screen_info()))

        self._logger.warning("connection lost: %s", reason)

    def _handle_frame(self, frame: dict[str, Any]) -> None:
        frame_type = frame.get("type")
        if not isinstance(frame_type, str):
            self._logger.warning("dropping frame without valid type: %s", frame)
            return

        with self._lock:
            if frame_type == "hello":
                self._handle_hello(frame)
                return
            if frame_type == "auth_ok":
                self._logger.info("auth_ok received from peer=%s", frame.get("machine_id"))
                return
            if frame_type == "heartbeat":
                return
            if frame_type == "enter_remote":
                self._handle_enter_remote(frame)
                return
            if frame_type == "exit_remote":
                self._handle_exit_remote(frame)
                return
            if frame_type == "mouse_move":
                self._handle_remote_mouse_move(frame)
                return
            if frame_type == "mouse_button":
                self._handle_remote_mouse_button(frame)
                return
            if frame_type == "wheel":
                self._handle_remote_wheel(frame)
                return
            if frame_type in {"key_down", "key_up"}:
                self._handle_remote_key(frame)
                return
            if frame_type == "disconnect":
                session = self._connector.session
                if session is not None:
                    session.close("peer requested disconnect")
                return
            self._logger.debug("ignoring unsupported frame type=%s", frame_type)

    def _handle_hello(self, frame: dict[str, Any]) -> None:
        machine_id = frame.get("machine_id")
        if not isinstance(machine_id, str):
            self._logger.warning("hello frame missing machine_id")
            return

        try:
            peer_screen = _screen_from_payload(frame.get("screen"))
        except ValueError as exc:
            self._logger.warning("invalid peer screen in hello: %s", exc)
            return

        self._peer_machine_id = machine_id
        self._peer_screen = peer_screen
        self._logger.info("peer hello received from machine_id=%s screen=%s", machine_id, peer_screen)
        self._connector.send(
            {
                "type": "auth_ok",
                "machine_id": self._config.machine_id,
                "protocol_version": PROTOCOL_VERSION,
            }
        )

    def _handle_enter_remote(self, frame: dict[str, Any]) -> None:
        normalized = _coerce_float(frame.get("normalized"), default=0.5)
        from_machine_id = frame.get("from_machine_id")
        if not self._state.can_accept_remote_capture():
            self._logger.warning("ignoring enter_remote while mode=%s", self._state.mode)
            return

        self._state.accept_remote_capture(from_machine_id if isinstance(from_machine_id, str) else None)
        entry_position = position_for_entry(self._config.entry_edge, normalized, self._backend.screen_info())
        self._backend.set_cursor_position(*entry_position)
        self._logger.info("peer control entered at normalized=%.3f", normalized)

    def _handle_exit_remote(self, frame: dict[str, Any]) -> None:
        if self._state.mode != SessionMode.CONTROLLING_PEER:
            return

        normalized = _coerce_float(frame.get("normalized"), default=self._state.last_local_handoff_norm)
        self._release_local_capture(restore_edge=self._config.entry_edge, normalized=normalized)
        self._logger.info("peer returned control at normalized=%.3f", normalized)

    def _handle_remote_mouse_move(self, frame: dict[str, Any]) -> None:
        if self._state.mode != SessionMode.CONTROLLED_BY_PEER:
            return

        dx = _coerce_int(frame.get("dx"), 0)
        dy = _coerce_int(frame.get("dy"), 0)
        if dx == 0 and dy == 0:
            return

        self._backend.move_mouse_relative(dx, dy)
        self._check_remote_exit()

    def _handle_remote_mouse_button(self, frame: dict[str, Any]) -> None:
        if self._state.mode != SessionMode.CONTROLLED_BY_PEER:
            return

        button = frame.get("button")
        is_down = bool(frame.get("is_down"))
        if isinstance(button, str):
            self._backend.inject_mouse_button(button, is_down)

    def _handle_remote_wheel(self, frame: dict[str, Any]) -> None:
        if self._state.mode != SessionMode.CONTROLLED_BY_PEER:
            return
        self._backend.inject_mouse_wheel(_coerce_int(frame.get("delta"), 0))
        self._check_remote_exit()

    def _handle_remote_key(self, frame: dict[str, Any]) -> None:
        if self._state.mode != SessionMode.CONTROLLED_BY_PEER:
            return

        self._backend.inject_key(
            vk_code=_coerce_int(frame.get("vk_code"), 0),
            scan_code=_coerce_int(frame.get("scan_code"), 0),
            is_down=frame.get("type") == "key_down",
            flags=_coerce_int(frame.get("flags"), 0),
        )

    def _check_remote_exit(self) -> None:
        if self._state.mode != SessionMode.CONTROLLED_BY_PEER:
            return

        x, y = self._backend.get_cursor_position()
        screen = self._backend.screen_info()
        if not is_at_edge(x, y, screen, self._config.handoff_edge, self._config.dead_zone_px):
            return

        normalized = normalize_on_edge(x, y, screen, self._config.handoff_edge)
        self._connector.send(
            {
                "type": "exit_remote",
                "normalized": normalized,
                "from_machine_id": self._config.machine_id,
            }
        )
        self._state.release_remote_capture(normalized)
        self._logger.info("remote side hit return edge, control released at normalized=%.3f", normalized)

    def _send_mouse_delta(self, dx: int, dy: int) -> None:
        with self._lock:
            if self._state.mode != SessionMode.CONTROLLING_PEER:
                return
            self._connector.send(
                {
                    "type": "mouse_move",
                    "dx": dx,
                    "dy": dy,
                    "from_machine_id": self._config.machine_id,
                }
            )

    def _heartbeat_loop(self) -> None:
        interval = self._config.heartbeat_ms / 1000.0
        timeout = max(1.0, interval * 3.0)
        while not self._stop.wait(interval):
            session = self._connector.session
            if session is None:
                continue
            if time.monotonic() - session.last_received > timeout:
                session.close("heartbeat timeout")
                continue
            session.send(
                {
                    "type": "heartbeat",
                    "machine_id": self._config.machine_id,
                }
            )

    def _shutdown(self) -> None:
        self._stop.set()
        session = self._connector.session
        if session is not None:
            session.send({"type": "disconnect", "machine_id": self._config.machine_id})
        self._motion.stop()
        self._connector.stop()
        self._backend.stop()

    def _failsafe_pressed(self) -> bool:
        needed = {_normalize_hotkey_token(token) for token in self._config.failsafe_hotkey}
        return needed.issubset(self._pressed_tokens)


def _screen_to_payload(screen: ScreenInfo) -> dict[str, int]:
    return {
        "left": screen.left,
        "top": screen.top,
        "width": screen.width,
        "height": screen.height,
    }


def _screen_from_payload(value: Any) -> ScreenInfo:
    if not isinstance(value, dict):
        raise ValueError("screen payload must be a dict")
    return ScreenInfo(
        left=_coerce_int(value.get("left"), 0),
        top=_coerce_int(value.get("top"), 0),
        width=_coerce_int(value.get("width"), 0),
        height=_coerce_int(value.get("height"), 0),
    )


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_hotkey_token(token: str) -> str:
    token = token.strip().lower()
    aliases = {
        "control": "ctrl",
        "lcontrol": "ctrl",
        "rcontrol": "ctrl",
        "menu": "alt",
        "lmenu": "alt",
        "rmenu": "alt",
        "return": "enter",
        "escape": "esc",
    }
    return aliases.get(token, token)


def _vk_to_token(vk_code: int) -> str:
    vk_code = int(vk_code)
    control_tokens = {
        win32.VK_CONTROL,
        win32.VK_LCONTROL,
        win32.VK_RCONTROL,
    }
    alt_tokens = {
        win32.VK_MENU,
        win32.VK_LMENU,
        win32.VK_RMENU,
    }
    shift_tokens = {
        win32.VK_SHIFT,
        win32.VK_LSHIFT,
        win32.VK_RSHIFT,
    }

    if vk_code in control_tokens:
        return "ctrl"
    if vk_code in alt_tokens:
        return "alt"
    if vk_code in shift_tokens:
        return "shift"
    if win32.VK_F1 <= vk_code <= win32.VK_F24:
        return f"f{vk_code - win32.VK_F1 + 1}"
    if 0x30 <= vk_code <= 0x39:
        return chr(vk_code).lower()
    if 0x41 <= vk_code <= 0x5A:
        return chr(vk_code).lower()

    named = {
        win32.VK_ESCAPE: "esc",
        win32.VK_TAB: "tab",
        win32.VK_RETURN: "enter",
        win32.VK_SPACE: "space",
    }
    return named.get(vk_code, f"vk_{vk_code:02x}")
