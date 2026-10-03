"""悬浮窗字号线性调节回归测试。"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.config_manager import (
    OVERLAY_VALUE_PX_DEFAULT,
    OVERLAY_VALUE_PX_MAX,
    OVERLAY_VALUE_PX_MIN,
    ConfigManager,
)
from src.gui.overlay import OverlayWindow

_APP = QApplication.instance() or QApplication([])


def test_anchor_40px_matches_legacy_large_preset():
    """40px 与旧版"大"档字号完全一致，迁移用户外观不变。"""
    overlay = OverlayWindow()
    overlay.set_value_font(40)

    assert overlay.get_value_font() == 40
    assert "font-size:40px" in overlay.g_value_label.styleSheet()
    assert "font-size:20px" in overlay.a_label.styleSheet()
    assert "font-size:20px" in overlay.b_label.styleSheet()
    assert "font-size:15px" in overlay.mode_label.styleSheet()
    assert "font-size:15px" in overlay.g_unit_label.styleSheet()
    assert "font-size:15px" in overlay.event_label.styleSheet()
    overlay.dispose()


def test_default_overlay_uses_26px():
    """默认 26px，A/B 通道与小字按固定比例跟随。"""
    overlay = OverlayWindow()

    assert overlay.get_value_font() == OVERLAY_VALUE_PX_DEFAULT == 26
    assert "font-size:26px" in overlay.g_value_label.styleSheet()
    assert "font-size:13px" in overlay.a_label.styleSheet()
    assert "font-size:13px" in overlay.b_label.styleSheet()
    assert "font-size:10px" in overlay.mode_label.styleSheet()
    overlay.dispose()


def test_value_font_clamped_to_range():
    """超出 13..65 的主字号被钳制，最小档启用小字可读性下限。"""
    overlay = OverlayWindow()

    overlay.set_value_font(999)
    assert overlay.get_value_font() == OVERLAY_VALUE_PX_MAX == 65

    overlay.set_value_font(0)
    assert overlay.get_value_font() == OVERLAY_VALUE_PX_MIN == 13
    assert "font-size:13px" in overlay.g_value_label.styleSheet()
    assert "font-size:10px" in overlay.a_label.styleSheet()
    assert "font-size:9px" in overlay.mode_label.styleSheet()
    overlay.dispose()


def test_same_instance_resizes_immediately_on_switch():
    """同一悬浮窗实例连续切换字号时窗口尺寸立即跟随（回归：adjustSize 滞后一拍）。"""
    overlay = OverlayWindow()
    overlay.show()

    overlay.set_value_font(52)
    big = (overlay.width(), overlay.height())
    overlay.set_value_font(26)
    small = (overlay.width(), overlay.height())
    overlay.set_value_font(52)
    big_again = (overlay.width(), overlay.height())

    assert big == big_again
    assert small[0] < big[0] and small[1] < big[1]
    overlay.dispose()


def test_slider_change_emits_signal_and_updates_label():
    """右键滑块拖动会更新标签、应用字号并广播信号；程序化设置不广播。"""
    overlay = OverlayWindow()
    seen = []
    overlay.value_font_changed.connect(seen.append)

    label = QLabel("40px")
    overlay._on_size_slider_changed(label, 30)

    assert label.text() == "30px"
    assert overlay.get_value_font() == 30
    assert seen == [30]

    seen.clear()
    overlay.set_value_font(20)
    assert seen == []
    overlay.dispose()


def _write_config(tmp_path, app_overrides: dict) -> str:
    """写入仅含 app 段的临时配置文件。"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"app": app_overrides}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def test_legacy_size_string_migrates(tmp_path):
    """旧版"大/中/小"字符串自动换算为对应主字号。"""
    for legacy, expected in (("小", 19), ("中", 26), ("大", 40)):
        path = _write_config(tmp_path, {"overlay_size": legacy})
        cfg = ConfigManager(path).load()
        assert cfg.app.overlay_size_px == expected


def test_size_px_key_wins_and_clamped(tmp_path):
    """新键 overlay_size_px 优先于旧字符串，并钳制到有效范围。"""
    path = _write_config(
        tmp_path, {"overlay_size": "大", "overlay_size_px": 33}
    )
    cfg = ConfigManager(path).load()
    assert cfg.app.overlay_size_px == 33

    cfg = ConfigManager(
        _write_config(tmp_path, {"overlay_size_px": 999})
    ).load()
    assert cfg.app.overlay_size_px == OVERLAY_VALUE_PX_MAX

    cfg = ConfigManager(_write_config(tmp_path, {"overlay_size_px": 1})).load()
    assert cfg.app.overlay_size_px == OVERLAY_VALUE_PX_MIN


def test_migrated_config_saves_px_key(tmp_path):
    """迁移后的配置保存时写入 overlay_size_px，旧键不再输出。"""
    path = _write_config(
        tmp_path, {"overlay_enabled": True, "overlay_size": "大"}
    )
    mgr = ConfigManager(path)
    mgr.load()
    assert mgr.config.app.overlay_size_px == 40

    mgr.save()
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["app"]["overlay_size_px"] == 40
    assert "overlay_size" not in saved["app"]


def test_font_change_does_not_reenter_event_loop(monkeypatch):
    """调字号不再调用 processEvents 重入事件循环（C2）。"""
    overlay = OverlayWindow()
    overlay.show()
    calls = []
    monkeypatch.setattr(QApplication, "processEvents",
                        lambda *args: calls.append(args))
    overlay.set_value_font(52)
    big = overlay.height()
    overlay.set_value_font(26)
    assert calls == []
    assert overlay.height() < big
    overlay.dispose()


def test_app_overlay_font_save_is_debounced(tmp_path):
    """悬浮窗字号连续变化只更新内存配置，防抖后写一次文件（C1）。"""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from main import App

    manager = ConfigManager(str(tmp_path / "config.json"))
    manager.save = Mock()
    app = App.__new__(App)
    app.config_mgr = manager
    app.overlay = SimpleNamespace(visible=False, show=Mock(), hide=Mock(),
                                  get_value_font=lambda: 26,
                                  set_value_font=Mock())
    for px in (30, 31, 32):
        app.window = SimpleNamespace(
            dashboard=SimpleNamespace(overlay_var=SimpleNamespace(get=lambda: False)),
            overlay_value_font=px)
        app._apply_overlay_settings()
    assert manager.config.app.overlay_size_px == 32
    manager.save.assert_not_called()
    assert app._config_save_timer.isActive()
    app._config_save_timer.timeout.emit()
    app._config_save_timer.stop()
    manager.save.assert_called_once_with()


def test_offscreen_position_returns_to_primary_screen():
    """保存的位置不在任何屏幕上（如外接显示器已拔除）时显示回主屏（C4）。"""
    overlay = OverlayWindow()
    overlay.move(-50000, -50000)
    overlay.show()
    area = QApplication.primaryScreen().availableGeometry()
    assert area.contains(overlay.pos())
    overlay.dispose()


def test_onscreen_position_is_kept():
    """位置在屏幕内时保持不动。"""
    overlay = OverlayWindow()
    area = QApplication.primaryScreen().availableGeometry()
    target = area.topLeft() + QPoint(20, 30)
    overlay.move(target)
    overlay.show()
    assert overlay.pos() == target
    overlay.dispose()


def test_overlay_does_not_shadow_qwidget_methods():
    """update / destroy 不再被遮蔽，数据刷新改用 update_values（C4）。"""
    assert OverlayWindow.update is QWidget.update
    assert OverlayWindow.destroy is QWidget.destroy
