from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Edge = Literal["left", "right", "top", "bottom"]
ENTRY_PADDING_PX = 3


@dataclass(frozen=True)
class ScreenInfo:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen dimensions must be positive")

    @property
    def right(self) -> int:
        return self.left + self.width - 1

    @property
    def bottom(self) -> int:
        return self.top + self.height - 1


class EdgeDetector:
    def __init__(self, edge: Edge, *, delay_ms: int, dead_zone_px: int):
        self._edge = edge
        self._delay_seconds = delay_ms / 1000.0
        self._dead_zone_px = dead_zone_px
        self._entered_at: float | None = None

    def reset(self) -> None:
        self._entered_at = None

    def update(self, x: int, y: int, screen: ScreenInfo, monotonic_time: float) -> float | None:
        if not is_at_edge(x, y, screen, self._edge, self._dead_zone_px):
            self._entered_at = None
            return None

        if self._entered_at is None:
            self._entered_at = monotonic_time
            return None

        if monotonic_time - self._entered_at < self._delay_seconds:
            return None

        self._entered_at = None
        return normalize_on_edge(x, y, screen, self._edge)


def normalize_on_edge(x: int, y: int, screen: ScreenInfo, edge: Edge) -> float:
    if edge in ("left", "right"):
        span = max(screen.height - 1, 1)
        return _clamp((y - screen.top) / span, 0.0, 1.0)

    span = max(screen.width - 1, 1)
    return _clamp((x - screen.left) / span, 0.0, 1.0)


def position_for_entry(edge: Edge, normalized: float, screen: ScreenInfo) -> tuple[int, int]:
    normalized = _clamp(normalized, 0.0, 1.0)
    if edge == "left":
        return screen.left + ENTRY_PADDING_PX, _scaled_axis(screen.top, screen.height, normalized)
    if edge == "right":
        return screen.right - ENTRY_PADDING_PX, _scaled_axis(screen.top, screen.height, normalized)
    if edge == "top":
        return _scaled_axis(screen.left, screen.width, normalized), screen.top + ENTRY_PADDING_PX
    return _scaled_axis(screen.left, screen.width, normalized), screen.bottom - ENTRY_PADDING_PX


def is_at_edge(x: int, y: int, screen: ScreenInfo, edge: Edge, dead_zone_px: int) -> bool:
    if edge == "left":
        return x <= screen.left + dead_zone_px
    if edge == "right":
        return x >= screen.right - dead_zone_px
    if edge == "top":
        return y <= screen.top + dead_zone_px
    return y >= screen.bottom - dead_zone_px


def _scaled_axis(start: int, size: int, normalized: float) -> int:
    span = max(size - 1, 1)
    return start + int(round(span * normalized))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
