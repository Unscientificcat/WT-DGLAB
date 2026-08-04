"""注意事项对话框。"""

import html
import os
import re
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def _get_project_root() -> str:
    """返回项目根目录，兼容源码和 PyInstaller 环境。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read_notice_text() -> str:
    """读取注意事项全文。"""
    path = os.path.join(_get_project_root(), "注意事项.txt")
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return "注意事项\n\n请务必阅读程序目录下的《注意事项.txt》。"


def _format_notice(content: str) -> str:
    """将双星号包裹的关键字转换为安全的富文本。"""
    escaped = html.escape(content)
    escaped = re.sub(
        r"\*\*(.*?)\*\*",
        r'<span style="color:#E36D7D;font-weight:700;">\1</span>',
        escaped,
    )
    return escaped.replace("\n", "<br>")


def show_disclaimer_dialog(parent: QWidget | None) -> bool:
    """显示注意事项，返回用户是否确认。"""
    dialog = QDialog(parent)
    dialog.setObjectName("disclaimerDialog")
    dialog.setWindowTitle("注意事项 - 郊狼雷霆")
    dialog.setMinimumSize(460, 380)
    dialog.resize(620, 560)
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 20)
    layout.setSpacing(14)

    title = QLabel("使用前请阅读注意事项")
    title.setObjectName("sectionTitle")
    layout.addWidget(title)

    text = QTextBrowser()
    text.setObjectName("noticeText")
    text.setReadOnly(True)
    text.setHtml(_format_notice(_read_notice_text()))
    layout.addWidget(text, 1)

    hint = QLabel("点击确认表示你已阅读并理解以上内容。")
    hint.setObjectName("hintText")
    layout.addWidget(hint)

    buttons = QDialogButtonBox(Qt.Horizontal)
    buttons.setObjectName("noticeBottom")
    confirm = QPushButton("我已阅读并确认")
    confirm.setObjectName("confirmNoticeButton")
    buttons.addButton(confirm, QDialogButtonBox.AcceptRole)
    layout.addWidget(buttons)

    confirm.clicked.connect(dialog.accept)
    confirm.setDefault(True)
    confirm.setFocus()
    return dialog.exec() == QDialog.Accepted
