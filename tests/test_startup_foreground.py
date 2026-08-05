"""启动窗口和注意事项前台显示回归测试。"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from main import App
from src.config_manager import ConfigManager
from src.gui.disclaimer_dialog import _create_disclaimer_dialog
from src.gui.main_window import MainWindow


def test_main_window_uses_temporary_startup_topmost(tmp_path):
    """主窗口启动时置顶，释放后恢复普通窗口。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))

    window.show_startup()
    assert window.isVisible()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint

    window._release_startup_topmost()
    assert window.isVisible()
    assert not window.windowFlags() & Qt.WindowStaysOnTopHint
    window.close()


def test_disclaimer_is_modal_and_topmost(tmp_path):
    """注意事项在显示期间保持应用模态和置顶。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    dialog = _create_disclaimer_dialog(window)

    assert dialog.isModal()
    assert dialog.windowFlags() & Qt.WindowStaysOnTopHint
    dialog.close()
    window.close()


def test_app_shows_main_window_before_first_disclaimer():
    """首次启动先显示父窗口，再进入注意事项模态流程。"""
    call_order = []
    app = App.__new__(App)
    app.config_mgr = SimpleNamespace(
        config=SimpleNamespace(app=SimpleNamespace(notice_accepted=False))
    )
    app.window = SimpleNamespace(
        show_startup=Mock(side_effect=lambda: call_order.append("window"))
    )
    app._show_disclaimer_dialog = Mock(
        side_effect=lambda: call_order.append("dialog") or False
    )

    app.run()

    assert call_order == ["window", "dialog"]
