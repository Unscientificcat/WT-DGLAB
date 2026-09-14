"""本次运行日志窗口，批量刷新并在后台导出文件。"""

import logging
import queue
import threading

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..runtime_logging import MAX_LINES, RuntimeLogSession


class RuntimeLogDialog(QDialog):
    """可与主界面同时操作的单次运行日志查看器。"""

    def __init__(self, session: RuntimeLogSession | None, parent=None):
        super().__init__(parent)
        self.session = session
        self._cursor = 0
        self._worker = None
        self._results = queue.Queue()
        self.setObjectName("runtimeLogDialog")
        self.setWindowTitle("运行日志 - 郊狼雷霆")
        self.setModal(False)
        self.resize(900, 560)
        self.setMinimumSize(620, 380)
        layout = QVBoxLayout(self)
        self.location = QLabel(
            f"日志文件夹：{session.directory}" if session else "日志服务尚未启动")
        self.location.setObjectName("runtimeLogLocation")
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.location)
        self.viewer = QPlainTextEdit()
        self.viewer.setObjectName("runtimeLogViewer")
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.viewer.setMaximumBlockCount(MAX_LINES)
        layout.addWidget(self.viewer, 1)
        self.hint = QLabel("窗口仅显示最近记录，导出包含本次完整日志")
        self.hint.setObjectName("runtimeLogHint")
        layout.addWidget(self.hint)
        self.storage_status = QLabel()
        self.storage_status.setObjectName("runtimeLogStorageStatus")
        self.storage_status.setWordWrap(True)
        layout.addWidget(self.storage_status)
        self.feedback = QLabel()
        self.feedback.setObjectName("runtimeLogFeedback")
        self.feedback.setWordWrap(True)
        self.feedback.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("导出本次日志")
        self.export_button.setObjectName("exportRuntimeLogButton")
        self.export_button.clicked.connect(self._export)
        self.folder_button = QPushButton("打开日志文件夹")
        self.folder_button.setObjectName("openLogFolderButton")
        self.folder_button.clicked.connect(self._open_folder)
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("closeRuntimeLogButton")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.export_button.setEnabled(session is not None)
        self.folder_button.setEnabled(session is not None)
        self.timer = QTimer(self)
        self.timer.setObjectName("runtimeLogRefreshTimer")
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """批量更新新记录，翻阅历史时保持滚动位置和文本选区。"""
        if self.session is None:
            return
        sequence, lines, truncated = self.session.recent(self._cursor)
        self._cursor = sequence
        if lines:
            bar = self.viewer.verticalScrollBar()
            follow = bar.value() >= bar.maximum()
            old_value = bar.value()
            removed = 0
            if truncated:
                self.viewer.setPlainText("\n".join(lines))
            else:
                old_count = (0 if self.viewer.document().isEmpty()
                             else self.viewer.document().blockCount())
                removed = max(0, old_count + len(lines) - MAX_LINES)
                cursor = QTextCursor(self.viewer.document())
                cursor.movePosition(QTextCursor.End)
                prefix = "\n" if not self.viewer.document().isEmpty() else ""
                cursor.insertText(prefix + "\n".join(lines))
            bar.setValue(bar.maximum() if follow else max(0, old_value - removed))
        self.storage_status.setText(self.session.error)
        self.hint.setText(
            "日志保存失败，导出仅包含仍可用的最近记录"
            if self.session.error else
            "窗口仅显示最近记录，导出包含本次完整日志")
        try:
            success, text = self._results.get_nowait()
        except queue.Empty:
            return
        self.feedback.setText(text)
        self.export_button.setEnabled(True)
        if not success:
            logging.getLogger("WT-DGLAB").warning(text)

    def _export(self) -> None:
        if self.session is None or (self._worker and self._worker.is_alive()):
            return
        self.export_button.setEnabled(False)
        self.feedback.setText("正在导出…")
        snapshot = self.session.snapshot()
        session = self.session
        results = self._results

        def work():
            try:
                path = session.export(snapshot)
                label = "导出成功" if snapshot.complete else "已导出不完整日志"
                results.put((True, f"{label}：{path}"))
            except Exception as error:
                results.put((False, f"导出失败：{error}；请检查文件夹权限后重试。"))

        self._worker = threading.Thread(target=work, name="日志导出", daemon=True)
        try:
            self._worker.start()
        except Exception as error:
            snapshot.close()
            self.feedback.setText(f"导出失败：{error}")
            self.export_button.setEnabled(True)

    def _open_folder(self) -> None:
        try:
            self.session.directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(
                    str(self.session.directory.resolve()))):
                raise OSError("系统无法打开文件夹")
        except OSError as error:
            self.feedback.setText(f"打开日志文件夹失败：{error}")

    def showEvent(self, event) -> None:
        """重开窗口后补齐关闭期间的记录并恢复刷新。"""
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event) -> None:
        """隐藏仅暂停界面刷新，日志服务与正在进行的导出不停止。"""
        self.timer.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        """停止界面刷新并等待导出释放文件，再允许会话清理。"""
        self.timer.stop()
        self.close()
        if self._worker is not None:
            self._worker.join(timeout=10)
            if self._worker.is_alive():
                self.session.mark_abnormal("日志导出尚未完成，保留自动日志")
