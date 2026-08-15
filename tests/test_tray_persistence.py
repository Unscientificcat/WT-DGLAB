"""系统托盘和配置持久化回归测试。"""

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import main
from src.config_manager import ConfigManager
from src.gui.main_window import MainWindow


def test_frozen_config_path_uses_exe_directory(tmp_path, monkeypatch):
    """打包运行时配置路径必须位于 EXE 同目录。"""
    exe_path = tmp_path / "WT-DGLAB.exe"
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "executable", str(exe_path))

    assert main._config_file_path() == str(tmp_path / "config.json")


def test_missing_config_is_created_with_defaults(tmp_path, monkeypatch):
    """首次启动时缺失配置应自动生成默认 JSON。"""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(main, "_config_file_path", lambda: str(config_path))

    manager = main._load_config_manager()

    assert config_path.is_file()
    assert ConfigManager(str(config_path)).load().app.ws_port == 8765
    assert manager.config_path == str(config_path)


def test_close_hides_window_and_saves_current_values(tmp_path):
    """点击关闭按钮只隐藏窗口，并保存尚未点击按钮的控件值。"""
    config_path = tmp_path / "config.json"
    manager = ConfigManager(str(config_path))
    window = MainWindow(manager)
    window._tray_available = True
    window.show()

    window.settings_panel.ac_ch_a.setValue(137)
    window.settings_panel.air_event_name.setText("测试玩家")
    window.settings_panel.air_kill_enabled.setChecked(True)
    window.settings_panel.air_kill_duration.setValue(8.5)
    window.close()

    assert not window.isVisible()
    loaded = ConfigManager(str(config_path)).load()
    assert loaded.aircraft.channel_a_max == 137
    assert loaded.events.player_name == "测试玩家"
    assert loaded.events.kill_enabled is True
    assert loaded.events.kill_duration == 8.5

    window._exit_requested = True
    window.close()


def test_tray_restore_and_explicit_exit(tmp_path):
    """托盘双击恢复窗口，退出菜单才触发主控制器清理。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager)
    window._tray_available = True
    window.hide()
    window.restore_from_tray()
    assert window.isVisible()

    callback = Mock()
    window.set_close_callback(callback)
    window._request_exit()
    QApplication.processEvents()
    assert callback.called

    window.quit()
