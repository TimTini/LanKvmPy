from __future__ import annotations

from lankvm.screen import EdgeDetector, ScreenInfo, normalize_on_edge, position_for_entry


def test_position_for_entry_right_edge_stays_inside_screen() -> None:
    screen = ScreenInfo(left=0, top=0, width=1920, height=1080)

    x, y = position_for_entry("right", 0.5, screen)

    assert x < screen.right
    assert 0 <= y <= screen.bottom


def test_normalize_on_edge_uses_orthogonal_axis() -> None:
    screen = ScreenInfo(left=0, top=0, width=100, height=200)

    normalized = normalize_on_edge(99, 100, screen, "right")

    assert normalized == 100 / 199


def test_edge_detector_waits_for_delay() -> None:
    screen = ScreenInfo(left=0, top=0, width=100, height=100)
    detector = EdgeDetector("right", delay_ms=200, dead_zone_px=3)

    assert detector.update(99, 50, screen, 0.00) is None
    assert detector.update(99, 50, screen, 0.10) is None
    assert detector.update(99, 50, screen, 0.21) is not None
