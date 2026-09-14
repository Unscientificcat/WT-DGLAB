"""运行日志窗口的入口、滚动、导出和关闭行为。"""

import logging
import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.gui import main_window, runtime_log_dialog
from src.gui.main_window import MainWindow
from src.gui.runtime_log_dialog import RuntimeLogDialog
from src.runtime_logging import RuntimeLogSession


_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def session(tmp_path):
    """提供不写入用户目录的会话。"""
    session = RuntimeLogSession(tmp_path / "logs", install_hooks=False)
    yield session
    session.finish(normal=True)


def test_button_order_singleton_and_nonmodal(session, tmp_path, monkeypatch):
    monkeypatch.setattr(main_window, "current_session", lambda: session)
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    window._tray_available = True
    window.resize(1080, 660)
    window.show()
    _APP.processEvents()
    status = window.status_bar
    assert status.runtime_log_button.geometry().right() < status.disclaimer_button.x()
    assert status.disclaimer_button.geometry().right() < status.about_button.x()
    assert status.about_button.geometry().right() <= status.width()
    status.runtime_log_button.click()
    first = window._runtime_log_dialog
    status.runtime_log_button.click()
    assert first is window._runtime_log_dialog
    assert not first.isModal()
    first.close()
    logging.warning("关闭日志窗口后仍记录")
    window.close()
    assert session.path.exists()
    window.show_runtime_log()
    assert "关闭日志窗口后仍记录" in first.viewer.toPlainText()
    window.stop_runtime_log_view()
    window._exit_requested = True
    window.close()


def test_refresh_scroll_selection_and_reopen(session):
    dialog = RuntimeLogDialog(session)
    dialog.show()
    for index in range(100):
        logging.warning("历史行%s", index)
    dialog.refresh()
    _APP.processEvents()
    bar = dialog.viewer.verticalScrollBar()
    assert bar.value() == bar.maximum()
    bar.setValue(10)
    cursor = dialog.viewer.textCursor()
    cursor.setPosition(0)
    cursor.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, 8)
    dialog.viewer.setTextCursor(cursor)
    bar.setValue(10)
    selected = dialog.viewer.textCursor().selectedText()
    logging.warning("新增日志")
    dialog.refresh()
    assert bar.value() == 10
    assert dialog.viewer.textCursor().selectedText() == selected
    bar.setValue(bar.maximum())
    logging.warning("继续跟随")
    dialog.refresh()
    assert bar.value() == bar.maximum()
    dialog.close()
    assert not dialog.timer.isActive()
    logging.warning("隐藏期间")
    dialog.show()
    assert dialog.timer.isActive()
    assert "隐藏期间" in dialog.viewer.toPlainText()
    dialog.shutdown()


def test_export_is_background_and_reenabled(session, monkeypatch):
    dialog = RuntimeLogDialog(session)
    gate = Event()
    original = session.export
    def delayed(snapshot):
        assert gate.wait(5)
        return original(snapshot)
    monkeypatch.setattr(session, "export", delayed)
    logging.warning("按钮点击前")
    dialog.export_button.click()
    assert not dialog.export_button.isEnabled()
    logging.warning("按钮点击后")
    gate.set()
    dialog._worker.join(timeout=5)
    dialog.refresh()
    assert dialog.export_button.isEnabled()
    assert "导出成功" in dialog.feedback.text()
    text = next(session.directory.glob("export_*.log")).read_text(encoding="utf-8")
    assert "按钮点击前" in text and "按钮点击后" not in text
    dialog.shutdown()


def test_export_failure_and_retry(session, monkeypatch):
    dialog = RuntimeLogDialog(session)
    original = session.export
    def fail(snapshot):
        snapshot.close()
        raise PermissionError("目录只读")
    monkeypatch.setattr(session, "export", fail)
    dialog.export_button.click()
    dialog._worker.join(timeout=5)
    dialog.refresh()
    assert "导出失败" in dialog.feedback.text()
    assert dialog.export_button.isEnabled()
    monkeypatch.setattr(session, "export", original)
    dialog.export_button.click()
    dialog._worker.join(timeout=5)
    dialog.refresh()
    assert "导出成功" in dialog.feedback.text()
    dialog.shutdown()


def test_open_folder_reports_failure(session, monkeypatch):
    dialog = RuntimeLogDialog(session)
    urls = []
    monkeypatch.setattr(runtime_log_dialog.QDesktopServices, "openUrl",
                        lambda url: urls.append(url.toLocalFile()) or False)
    dialog.folder_button.click()
    assert urls == [str(session.directory).replace("\\", "/")]
    assert "打开日志文件夹失败" in dialog.feedback.text()
    dialog.shutdown()


def test_view_limit_preserves_full_export(session):
    for index in range(10050):
        logging.info("完整记录-%s", index)
    dialog = RuntimeLogDialog(session)
    assert dialog.viewer.document().blockCount() == 10000
    text = dialog.viewer.toPlainText()
    assert "完整记录-0\n" not in text
    assert "完整记录-10049" in text
    exported = session.export(session.snapshot()).read_text(encoding="utf-8")
    assert "完整记录-0\n" in exported
    dialog.shutdown()
