"""悬浮窗字号预设回归测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.overlay import OverlayWindow, SIZES


def test_large_overlay_is_bigger_without_affecting_other_presets():
    """大档适合 2K 屏，中小档继续照顾 1080P 屏。"""
    assert SIZES["大"] == {"value": 40, "channel": 20, "mode": 15}
    assert SIZES["中"] == {"value": 26, "channel": 14, "mode": 11}
    assert SIZES["小"] == {"value": 19, "channel": 12, "mode": 10}

    for key in ("value", "channel", "mode"):
        assert SIZES["大"][key] > SIZES["中"][key]
        assert SIZES["大"][key] < SIZES["中"][key] * 2


def test_large_overlay_preset_applies_immediately():
    """切换大档后，所有文字区域立即采用新字号。"""
    overlay = OverlayWindow()
    overlay.set_size("大")

    assert overlay.get_size() == "大"
    assert "font-size:40px" in overlay.value_label.styleSheet()
    assert "font-size:20px" in overlay.a_label.styleSheet()
    assert "font-size:20px" in overlay.b_label.styleSheet()
    assert "font-size:15px" in overlay.mode_label.styleSheet()
    assert "font-size:15px" in overlay.unit_label.styleSheet()
    assert "font-size:15px" in overlay.event_label.styleSheet()
    overlay.destroy()
