"""设置页修改不丢失 / 生效的回归测试（代码审查修复 A2~A5）。"""

import os
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.gui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])
_WARNING = "src.gui.main_window.QMessageBox.warning"


def _window(tmp_path, **kwargs) -> MainWindow:
    """创建使用临时配置的主窗口。"""
    return MainWindow(ConfigManager(str(tmp_path / "config.json")), **kwargs)


def _close(window: MainWindow) -> None:
    """关闭测试窗口，避免托盘退出流程重复处理。"""
    window._exit_requested = True
    window.close()


def test_returning_to_parameter_page_keeps_unsaved_edits(tmp_path):
    """A2：波形页切回触发设置页时不重新载入配置。"""
    window = _window(tmp_path)
    panel = window.settings_panel
    try:
        panel.gforce_min.setValue(3.25)
        panel._open_waveform_dialog()
        panel._show_parameter_page()
        assert panel.gforce_min.value() == 3.25
    finally:
        _close(window)


def test_scene_change_with_invalid_range_warns_and_rolls_back(tmp_path):
    """A3：随机间隔非法时切换场景被拒绝，列表选择恢复原场景。"""
    window = _window(tmp_path)
    view = window.settings_panel._waveform_view
    try:
        view.min_a.setValue(60)
        view.max_a.setValue(10)
        with patch(_WARNING) as warning:
            view.scene_list.setCurrentRow(1)
        warning.assert_called_once()
        assert view._scene_index == 0
        assert view.scene_list.currentRow() == 0
        assert view.min_a.value() == 60
    finally:
        _close(window)


def test_mode_change_with_invalid_range_warns_and_keeps_mode(tmp_path):
    """A3：随机间隔非法时切换空战/陆战被拒绝。"""
    window = _window(tmp_path)
    view = window.settings_panel._waveform_view
    try:
        view.min_b.setValue(60)
        view.max_b.setValue(10)
        with patch(_WARNING) as warning:
            view.tank_button.click()
        warning.assert_called_once()
        assert view._mode == "aircraft"
        assert view.air_button.isChecked()
        assert not view.tank_button.isChecked()
    finally:
        _close(window)


def test_silent_save_commits_current_waveform_scene(tmp_path):
    """A3：静默保存时一并写入波形页当前场景的修改。"""
    window = _window(tmp_path)
    view = window.settings_panel._waveform_view
    try:
        view.random_a.setChecked(True)
        view.min_a.setValue(12)
        assert window.save_current_settings()
        saved = ConfigManager(str(tmp_path / "config.json")).load()
        assert saved.aircraft.random_enabled_a is True
        assert saved.aircraft.random_min_a == 12
    finally:
        _close(window)


def test_close_to_tray_saves_with_notify(tmp_path):
    """A4：关到托盘时保存并通知主控制器，使连接设置变更生效。"""
    callback = Mock()
    window = _window(tmp_path)
    window.settings_panel._on_save_callback = callback
    window._tray_available = True
    window._tray_notice_shown = True
    try:
        window.show()
        window.close()
        callback.assert_called_once_with()
        assert window.isHidden()
    finally:
        _close(window)


def test_steepness_box_matches_config_range(tmp_path):
    """A5：陡度输入框范围与配置校验一致（1.0~6.0）。"""
    window = _window(tmp_path)
    panel = window.settings_panel
    try:
        for prefix in ("ac", "tank", "cas"):
            box = getattr(panel, f"{prefix}_curve_steepness")
            assert box.minimum() == 1.0
            assert box.maximum() == 6.0
    finally:
        _close(window)


def test_range_boxes_keep_two_decimals(tmp_path):
    """A5：过载/速度保留两位小数，往返保存不截断。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    manager.config.aircraft.gforce_min = 1.25
    manager.config.tank.speed_max = 55.75
    window = MainWindow(manager)
    try:
        assert window.settings_panel.gforce_min.value() == 1.25
        assert window.settings_panel.speed_max.value() == 55.75
        assert window.save_current_settings()
        assert manager.config.aircraft.gforce_min == 1.25
        assert manager.config.tank.speed_max == 55.75
    finally:
        _close(window)


def test_manual_save_rejects_reversed_range(tmp_path):
    """A5：手动保存时过载最小值大于最大值会提示并中止。"""
    window = _window(tmp_path)
    panel = window.settings_panel
    try:
        panel.gforce_min.setValue(9)
        panel.gforce_max.setValue(3)
        with patch(_WARNING) as warning:
            assert panel.save_settings() is False
        warning.assert_called_once()
        assert window._config_mgr.config.aircraft.gforce_min == 1.0
        assert not os.path.exists(tmp_path / "config.json")
    finally:
        _close(window)


def test_silent_save_keeps_old_reversed_range_but_saves_rest(tmp_path):
    """A5：静默保存时非法范围保留旧值，其余设置照常保存。"""
    window = _window(tmp_path)
    panel = window.settings_panel
    try:
        panel.speed_min.setValue(90)
        panel.speed_max.setValue(10)
        panel.ac_ch_a.setValue(33)
        assert window.save_current_settings()
        saved = ConfigManager(str(tmp_path / "config.json")).load()
        assert saved.tank.speed_min == 0.0
        assert saved.tank.speed_max == 60.0
        assert saved.aircraft.channel_a_max == 33
    finally:
        _close(window)
