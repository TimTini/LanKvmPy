from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MouseMoveEvent:
    x: int
    y: int
    monotonic_time: float


@dataclass(frozen=True)
class MouseButtonEvent:
    button: str
    is_down: bool
    x: int
    y: int
    monotonic_time: float


@dataclass(frozen=True)
class MouseWheelEvent:
    delta: int
    x: int
    y: int
    monotonic_time: float


@dataclass(frozen=True)
class KeyEvent:
    vk_code: int
    scan_code: int
    flags: int
    is_down: bool
    monotonic_time: float
