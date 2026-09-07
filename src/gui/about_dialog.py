"""关于对话框 — 展示应用信息、作者与项目链接。"""

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from ..runtime_paths import resource_path
from ..version import APP_NAME, APP_VERSION
from .styles import COLORS

AUTHOR_NAME = "某不科学的猫酱"
BILIBILI_URL = "https://space.bilibili.com/247197404"
GITHUB_URL = "https://github.com/Unscientificcat/WT-DGLAB"

BILIBILI_TEXT = "space.bilibili.com/247197404"
GITHUB_TEXT = "github.com/Unscientificcat/WT-DGLAB"

LICENSE_NOTE = (
    "本项目基于 MIT License 开源发布，为非官方第三方工具，"
    "与 Gaijin Entertainment、War Thunder、DG-LAB 或地牢实验室"
    "不存在隶属或授权关系，相关名称和商标归各自权利人所有。"
)


def open_external_url(url: str) -> None:
    """使用系统默认浏览器打开外部链接。"""
    QDesktopServices.openUrl(QUrl(url))


def _link_anchor(text: str, url: str) -> str:
    """生成与主题同色的富文本链接锚点。"""
    color = COLORS["primary"]
    return f'<a href="{url}" style="color:{color};text-decoration:none;">{text}</a>'


class AboutDialog(QDialog):
    """展示应用品牌、版本、作者与可点击项目链接的模态对话框。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowTitle(f"关于 - {APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(6)

        icon_label = QLabel()
        icon_label.setObjectName("aboutIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        cover = QPixmap(_icon_path())
        if not cover.isNull():
            icon_label.setPixmap(cover.scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(icon_label)

        title = QLabel(APP_NAME)
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("WAR THUNDER × DG-LAB")
        subtitle.setObjectName("aboutSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.version_label = QLabel(f"版本 {APP_VERSION}")
        self.version_label.setObjectName("aboutVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.version_label)

        layout.addSpacing(8)
        separator = QFrame()
        separator.setObjectName("aboutSeparator")
        separator.setFrameShape(QFrame.HLine)
        layout.addWidget(separator)
        layout.addSpacing(4)

        self.author_label = QLabel(f"作者：{AUTHOR_NAME}")
        self.author_label.setObjectName("aboutInfo")
        layout.addWidget(self.author_label)

        self.bilibili_label = QLabel(f"B 站主页：{_link_anchor(BILIBILI_TEXT, BILIBILI_URL)}")
        self.bilibili_label.setObjectName("aboutLink")
        self.bilibili_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.bilibili_label.linkActivated.connect(self._open_link)
        layout.addWidget(self.bilibili_label)

        self.github_label = QLabel(f"GitHub 仓库：{_link_anchor(GITHUB_TEXT, GITHUB_URL)}")
        self.github_label.setObjectName("aboutLink")
        self.github_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.github_label.linkActivated.connect(self._open_link)
        layout.addWidget(self.github_label)

        layout.addSpacing(4)
        separator2 = QFrame()
        separator2.setObjectName("aboutSeparator")
        separator2.setFrameShape(QFrame.HLine)
        layout.addWidget(separator2)
        layout.addSpacing(4)

        self.note_label = QLabel(LICENSE_NOTE)
        self.note_label.setObjectName("aboutNote")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        layout.addSpacing(8)
        buttons = QVBoxLayout()
        close_button = QPushButton("关闭")
        close_button.setObjectName("aboutCloseButton")
        close_button.clicked.connect(self.accept)
        close_button.setDefault(True)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    @staticmethod
    def _open_link(url: str) -> None:
        """点击链接 — 经 open_external_url 打开（测试可替换）。"""
        open_external_url(url)


def _icon_path() -> str:
    """返回源码或 PyInstaller 环境中的品牌图标路径。"""
    return resource_path("tubiao_ui.jpg")


def show_about_dialog(parent: QWidget | None) -> None:
    """显示关于对话框（模态）。"""
    AboutDialog(parent).exec()
