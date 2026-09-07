"""关于对话框与版本单一来源回归测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.gui import about_dialog, main_window
from src.gui.about_dialog import (
    APP_NAME,
    APP_VERSION,
    BILIBILI_URL,
    GITHUB_URL,
    AUTHOR_NAME,
    AboutDialog,
)
from src.gui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


def test_about_dialog_shows_author_bilibili_and_github():
    """对话框展示作者、B 站主页、GitHub 仓库和开源声明。"""
    dialog = AboutDialog()

    assert AUTHOR_NAME in dialog.author_label.text()
    assert "作者" in dialog.author_label.text()
    assert "B 站主页" in dialog.bilibili_label.text()
    assert BILIBILI_URL in dialog.bilibili_label.text()
    assert "GitHub 仓库" in dialog.github_label.text()
    assert GITHUB_URL in dialog.github_label.text()
    assert "MIT License" in dialog.note_label.text()
    dialog.close()


def test_about_dialog_is_modal_with_correct_title():
    """对话框为模态，标题遵循“关于 - 应用名”格式。"""
    dialog = AboutDialog()

    assert dialog.isModal() is True
    assert dialog.windowTitle() == f"关于 - {APP_NAME}"
    dialog.close()


def test_about_dialog_version_matches_single_source():
    """对话框版本、窗口标题与打包脚本都引用同一版本常量。"""
    from build import VERSION

    dialog = AboutDialog()

    assert dialog.version_label.text() == f"版本 {APP_VERSION}"
    assert APP_VERSION == "v1.0"
    assert VERSION == APP_VERSION
    dialog.close()


def test_main_window_title_uses_version_constant(tmp_path):
    """窗口标题由 APP_NAME + APP_VERSION 拼接，输出保持不变。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager)

    assert window.windowTitle() == f"{APP_NAME} {APP_VERSION}"
    assert window.windowTitle() == "郊狼雷霆 v1.0"
    window.close()


def test_status_bar_has_about_button_and_opens_dialog(tmp_path, monkeypatch):
    """顶部状态栏“关于”按钮点击后打开关于对话框。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager)
    calls = []
    monkeypatch.setattr(
        main_window, "show_about_dialog",
        lambda parent: calls.append(parent),
    )

    assert window.status_bar.about_button.text() == "关于"
    assert window.status_bar.about_button.objectName() == "aboutButton"

    window.status_bar.about_button.click()

    assert calls == [window]
    window.close()


def test_clicking_links_opens_system_browser(monkeypatch):
    """点击 B 站 / GitHub 链接会把对应 URL 交给系统浏览器打开。"""
    opened = []
    monkeypatch.setattr(
        about_dialog, "open_external_url",
        lambda url: opened.append(url),
    )
    dialog = AboutDialog()

    dialog.bilibili_label.linkActivated.emit(BILIBILI_URL)
    dialog.github_label.linkActivated.emit(GITHUB_URL)

    assert opened == [BILIBILI_URL, GITHUB_URL]
    dialog.close()
