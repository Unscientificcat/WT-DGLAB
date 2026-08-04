"""PySide6 悬浮窗，显示实时游戏数据。"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget


SIZES = {
    "大": {"value": 40, "channel": 20, "mode": 15},
    "中": {"value": 26, "channel": 14, "mode": 11},
    "小": {"value": 19, "channel": 12, "mode": 10},
}


class OverlayWindow(QWidget):
    """透明置顶悬浮窗，支持拖动和右键切换大小。"""

    def __init__(self):
        super().__init__(None)
        self.setObjectName("overlayWindow")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._size = "中"
        self._visible = False
        self._drag_offset = QPoint()
        self._cache = {"mode": "", "value": "", "unit": "", "a": "", "b": "", "event": ""}
        self._build()
        self.move(100, 100)
        self.hide()

    def _build(self) -> None:
        """创建悬浮窗控件。"""
        root = QFrame()
        root.setObjectName("overlaySurface")
        root.setAttribute(Qt.WA_TranslucentBackground)
        root.setAutoFillBackground(False)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(1)

        self.mode_label = QLabel("空战")
        self.mode_label.setObjectName("overlayMode")
        self.value_label = QLabel("--.-")
        self.value_label.setObjectName("overlayValue")
        self.unit_label = QLabel("G")
        self.unit_label.setObjectName("hintText")
        self.a_label = QLabel("A: 0")
        self.a_label.setObjectName("overlayA")
        self.b_label = QLabel("B: 0")
        self.b_label.setObjectName("overlayB")
        self.event_label = QLabel("")
        self.event_label.setObjectName("eventText")

        channels = QHBoxLayout()
        channels.setContentsMargins(0, 4, 0, 0)
        channels.addWidget(self.a_label)
        channels.addSpacing(12)
        channels.addWidget(self.b_label)
        channels.addStretch()

        layout.addWidget(self.mode_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.unit_label)
        layout.addLayout(channels)
        layout.addWidget(self.event_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        self.set_size(self._size)

    def show(self) -> None:
        """显示悬浮窗并清除显示缓存。"""
        self._visible = True
        self._cache = {key: "" for key in self._cache}
        super().show()

    def hide(self) -> None:
        """隐藏悬浮窗。"""
        self._visible = False
        super().hide()

    @property
    def visible(self) -> bool:
        """返回悬浮窗是否显示。"""
        return self._visible

    def set_size(self, size: str) -> None:
        """更新悬浮窗字号预设。"""
        if size not in SIZES:
            return
        self._size = size
        preset = SIZES[size]
        self.value_label.setStyleSheet(f"font-size:{preset['value']}px;")
        for label in (self.a_label, self.b_label):
            label.setStyleSheet(f"font-size:{preset['channel']}px;")
        for label in (self.mode_label, self.unit_label, self.event_label):
            label.setStyleSheet(f"font-size:{preset['mode']}px;")
        self.adjustSize()

    def get_size(self) -> str:
        """返回当前悬浮窗大小。"""
        return self._size

    def update(self, mode: str, value: str, unit: str, ch_a: int, ch_b: int,
               event_text: str = "") -> None:
        """仅更新发生变化的实时字段，减少重绘。"""
        values = {
            "mode": "空战" if mode == "aircraft" else "陆战",
            "value": value,
            "unit": unit,
            "a": f"A: {ch_a}",
            "b": f"B: {ch_b}",
            "event": event_text,
        }
        labels = {
            "mode": self.mode_label,
            "value": self.value_label,
            "unit": self.unit_label,
            "a": self.a_label,
            "b": self.b_label,
            "event": self.event_label,
        }
        for key, text in values.items():
            if text != self._cache[key]:
                self._cache[key] = text
                labels[key].setText(text)

    def destroy(self) -> None:
        """关闭并释放悬浮窗。"""
        self._visible = False
        self.close()
        self.deleteLater()

    def mousePressEvent(self, event) -> None:
        """记录左键拖动起点，或显示右键菜单。"""
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            menu = QMenu(self)
            for size in ("大", "中", "小"):
                action = QAction(size, menu)
                action.setCheckable(True)
                action.setChecked(size == self._size)
                action.triggered.connect(lambda checked=False, value=size: self.set_size(value))
                menu.addAction(action)
            menu.exec(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖动悬浮窗。"""
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)
