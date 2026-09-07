"""仪表盘模式切换与设置页独立性的回归测试。"""

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.gui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


def _close(window: MainWindow) -> None:
    """关闭测试窗口，避免托盘退出流程重复处理。"""
    window._exit_requested = True
    window.close()


def test_saved_tank_mode_initializes_dashboard_and_settings_page(tmp_path):
    """保存为陆战时，仪表盘和初始查看页均恢复陆战。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    manager.config.app.mode = "tank"
    callback = Mock()
    window = MainWindow(manager, on_mode_changed=callback)
    try:
        assert window.dashboard.mode_tank_button.isChecked()
        assert window.get_mode() == "tank"
        assert window.settings_panel.pages.currentIndex() == 1
        callback.assert_not_called()
    finally:
        _close(window)


def test_dashboard_click_notifies_once_and_deduplicates(tmp_path):
    """从空战切到陆战只通知一次，重复点击不通知。"""
    callback = Mock()
    window = MainWindow(
        ConfigManager(str(tmp_path / "config.json")),
        on_mode_changed=callback,
    )
    try:
        window.dashboard.mode_tank_button.click()
        assert window.get_mode() == "tank"
        callback.assert_called_once_with()

        window.dashboard.mode_tank_button.click()
        callback.assert_called_once_with()
    finally:
        _close(window)


def test_dashboard_programmatic_mode_is_silent_and_sized(tmp_path):
    """程序化设置不回调，按钮尺寸和对象名符合紧凑布局。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    callback = Mock()
    window.dashboard.set_mode_callback(callback)
    try:
        assert window.dashboard.mode_air_button.objectName() == "dashboardModeButton"
        assert window.dashboard.mode_tank_button.objectName() == "dashboardModeButton"
        assert window.dashboard.mode_air_button.size().width() == 52
        assert window.dashboard.mode_air_button.size().height() == 26

        window.dashboard.set_mode("tank")
        assert window.dashboard.get_mode() == "tank"
        assert window.dashboard.mode_tank_button.isChecked()
        callback.assert_not_called()

        window.dashboard.set_mode("unknown")
        assert window.dashboard.get_mode() == "aircraft"
        assert window.dashboard.mode_air_button.isChecked()
        callback.assert_not_called()
    finally:
        _close(window)


def test_settings_buttons_only_switch_pages(tmp_path):
    """设置按钮只改变查看页和文字，不触发业务模式切换。"""
    callback = Mock()
    window = MainWindow(
        ConfigManager(str(tmp_path / "config.json")),
        on_mode_changed=callback,
    )
    try:
        panel = window.settings_panel
        assert panel.air_button.text() == "空战设置"
        assert panel.tank_button.text() == "陆战设置"

        panel.tank_button.click()
        assert panel.pages.currentIndex() == 1
        assert window.get_mode() == "aircraft"
        callback.assert_not_called()

        panel.air_button.click()
        assert panel.pages.currentIndex() == 0
        assert window.get_mode() == "aircraft"
        callback.assert_not_called()
    finally:
        _close(window)


def test_dashboard_and_settings_page_do_not_follow_each_other(tmp_path):
    """仪表盘业务模式和设置查看页允许保持不同。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    try:
        panel = window.settings_panel
        assert panel.get_mode_page() == "aircraft"

        window.dashboard.mode_tank_button.click()
        assert window.get_mode() == "tank"
        assert panel.get_mode_page() == "aircraft"

        panel.tank_button.click()
        assert panel.get_mode_page() == "tank"
        assert window.get_mode() == "tank"
    finally:
        _close(window)


def test_dashboard_mode_is_persisted_immediately(tmp_path):
    """仪表盘模式切换后立即写入配置文件。"""
    path = tmp_path / "config.json"
    manager = ConfigManager(str(path))
    window = MainWindow(manager)
    try:
        window.dashboard.mode_tank_button.click()
        assert manager.config.app.mode == "tank"
        assert ConfigManager(str(path)).load().app.mode == "tank"
    finally:
        _close(window)


def test_reset_restores_dashboard_mode_and_page(tmp_path):
    """恢复默认同时恢复仪表盘和设置查看页，并通知业务层一次。"""
    path = tmp_path / "config.json"
    manager = ConfigManager(str(path))
    manager.config.app.mode = "tank"
    callback = Mock()
    window = MainWindow(manager, on_mode_changed=callback)
    try:
        callback.reset_mock()
        window.settings_panel._on_reset()

        assert window.get_mode() == "aircraft"
        assert window.dashboard.mode_air_button.isChecked()
        assert window.settings_panel.get_mode_page() == "aircraft"
        assert ConfigManager(str(path)).load().app.mode == "aircraft"
        callback.assert_called_once_with()
    finally:
        _close(window)


def test_auxiliary_pages_preserve_independent_mode_and_page(tmp_path):
    """波形页、背景页往返不重置业务模式或当前查看页。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    try:
        panel = window.settings_panel
        panel.tank_button.click()
        window.dashboard.mode_tank_button.click()
        assert panel.get_mode_page() == "tank"
        assert window.get_mode() == "tank"

        panel._open_waveform_dialog()
        panel._show_parameter_page()
        assert panel.get_mode_page() == "tank"
        assert window.get_mode() == "tank"

        panel._open_appearance_page()
        panel._show_parameter_page()
        assert panel.get_mode_page() == "tank"
        assert window.get_mode() == "tank"
    finally:
        _close(window)
