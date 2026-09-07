"""PySide6 悬浮窗，显示实时游戏数据，支持自定义显示内容。"""

from PySide6.QtCore import QEventLoop, QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..config_manager import (
    OVERLAY_VALUE_PX_DEFAULT,
    OVERLAY_VALUE_PX_MAX,
    OVERLAY_VALUE_PX_MIN,
)
from ..output_telemetry import display_waveform_name

# 悬浮窗可开关的显示项（与配置 overlay_show_* 字段一一对应）
OVERLAY_CONTENT_FLAGS = (
    "mode",        # 当前模式（空战/陆战）
    "gforce",      # 实时过载 (G)
    "speed",       # 实时速度 (km/h)
    "event",       # 事件提示（击杀/坠毁/维修）
    "strength_a",  # A 通道输出强度
    "strength_b",  # B 通道输出强度
    "wave_a",      # A 通道输出波形名
    "wave_b",      # B 通道输出波形名
)

# A/B 通道与模式小字相对主字号的缩放比例，以旧版"大"档 40/20/15 为锚点
CHANNEL_RATIO = 0.5
MODE_RATIO = 0.375
# 小字号下的可读性下限
CHANNEL_PX_MIN = 10
MODE_PX_MIN = 9


def channel_font_px(value_px: int) -> int:
    """根据主字号计算 A/B 通道字号。"""
    return max(CHANNEL_PX_MIN, round(value_px * CHANNEL_RATIO))


def mode_font_px(value_px: int) -> int:
    """根据主字号计算模式/单位/事件小字字号。"""
    return max(MODE_PX_MIN, round(value_px * MODE_RATIO))


class OverlayWindow(QWidget):
    """透明置顶悬浮窗，支持拖动、右键调节大小和自定义显示内容。"""

    value_font_changed = Signal(int)
    content_settings_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setObjectName("overlayWindow")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._value_font = OVERLAY_VALUE_PX_DEFAULT
        self._visible = False
        self._drag_offset = QPoint()
        self._flags = {key: True for key in OVERLAY_CONTENT_FLAGS}
        self._cache = {
            "mode": "", "g": "", "g_unit": "", "speed": "", "speed_unit": "",
            "a": "", "b": "", "wave_a": "", "wave_b": "", "event": "",
        }
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

        # 过载 / 速度两个指标行：显示开关 + 数据有效性共同决定可见性
        self.g_value_label = QLabel("--.-")
        self.g_value_label.setObjectName("overlayValue")
        self.g_unit_label = QLabel("G")
        self.g_unit_label.setObjectName("hintText")
        self.speed_value_label = QLabel("--.-")
        self.speed_value_label.setObjectName("overlayValue")
        self.speed_unit_label = QLabel("km/h")
        self.speed_unit_label.setObjectName("hintText")

        self.a_label = QLabel("A: 0")
        self.a_label.setObjectName("overlayA")
        self.a_wave_label = QLabel("恒定")
        self.a_wave_label.setObjectName("overlayWave")
        self.b_label = QLabel("B: 0")
        self.b_label.setObjectName("overlayB")
        self.b_wave_label = QLabel("恒定")
        self.b_wave_label.setObjectName("overlayWave")
        self.event_label = QLabel("")
        self.event_label.setObjectName("eventText")

        self.g_row = self._make_metric_row(
            self.g_value_label, self.g_unit_label)
        self.speed_row = self._make_metric_row(
            self.speed_value_label, self.speed_unit_label)

        channels = QVBoxLayout()
        channels.setContentsMargins(0, 4, 0, 0)
        channels.setSpacing(0)
        channels.addWidget(self.a_label)
        channels.addWidget(self.a_wave_label)
        channels.addSpacing(5)
        channels.addWidget(self.b_label)
        channels.addWidget(self.b_wave_label)
        channels.addStretch()

        layout.addWidget(self.mode_label)
        layout.addWidget(self.g_row)
        layout.addWidget(self.speed_row)
        layout.addLayout(channels)
        layout.addWidget(self.event_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        self.set_value_font(self._value_font)

    @staticmethod
    def _make_metric_row(value_label: QLabel, unit_label: QLabel) -> QWidget:
        """创建"大数值 + 小单位"纵向排列的指标行容器。"""
        row = QWidget()
        row.setAttribute(Qt.WA_TranslucentBackground)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addWidget(value_label)
        row_layout.addWidget(unit_label)
        return row

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

    def set_value_font(self, px: int) -> None:
        """按主字号（像素）线性更新悬浮窗各文字区域大小。"""
        px = max(OVERLAY_VALUE_PX_MIN, min(OVERLAY_VALUE_PX_MAX, int(px)))
        self._value_font = px
        for label in (self.g_value_label, self.speed_value_label):
            label.setStyleSheet(f"font-size:{px}px;")
        channel = channel_font_px(px)
        mode = mode_font_px(px)
        for label in (self.a_label, self.b_label):
            label.setStyleSheet(f"font-size:{channel}px;")
        for label in (self.mode_label, self.g_unit_label,
                      self.speed_unit_label, self.event_label,
                      self.a_wave_label, self.b_wave_label):
            label.setStyleSheet(f"font-size:{mode}px;")
        # styleSheet 触发的重布局事件是延迟投递的，先排除输入事件冲一遍布局，
        # 否则 adjustSize 会按上一次的旧字号取尺寸，导致悬浮窗大小滞后一拍
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.adjustSize()

    def get_value_font(self) -> int:
        """返回当前悬浮窗主字号（像素）。"""
        return self._value_font

    def set_content_flags(self, flags: dict) -> None:
        """按显示开关更新悬浮窗内容，并立即调整窗口大小。"""
        for key in OVERLAY_CONTENT_FLAGS:
            if key in flags:
                self._flags[key] = bool(flags[key])
        self.mode_label.setVisible(self._flags["mode"])
        self.event_label.setVisible(self._flags["event"])
        self.a_label.setVisible(self._flags["strength_a"])
        self.b_label.setVisible(self._flags["strength_b"])
        self.a_wave_label.setVisible(self._flags["wave_a"])
        self.b_wave_label.setVisible(self._flags["wave_b"])
        self._refresh_metric_row_visibility()
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.adjustSize()

    def _refresh_metric_row_visibility(self) -> None:
        """指标行可见性 = 显示开关 且 该指标当前有数据。"""
        self.g_row.setVisible(self._flags["gforce"] and bool(self._cache["g"]))
        self.speed_row.setVisible(
            self._flags["speed"] and bool(self._cache["speed"]))

    def update(self, mode: str, g_text: str, speed_text: str, ch_a: int,
               ch_b: int, wave_a: str = "", wave_b: str = "",
               event_text: str = "") -> None:
        """仅更新发生变化的实时字段，减少重绘。

        g_text / speed_text 为空字符串表示该指标本轮无数据（隐藏对应行）。
        """
        values = {
            "mode": "空战" if mode == "aircraft" else "陆战",
            "g": g_text or "",
            "g_unit": "G" if g_text else "",
            "speed": speed_text or "",
            "speed_unit": "km/h" if speed_text else "",
            "a": f"A: {ch_a}",
            "b": f"B: {ch_b}",
            "wave_a": display_waveform_name(wave_a) if wave_a else "",
            "wave_b": display_waveform_name(wave_b) if wave_b else "",
            "event": event_text,
        }
        labels = {
            "mode": self.mode_label,
            "g": self.g_value_label,
            "g_unit": self.g_unit_label,
            "speed": self.speed_value_label,
            "speed_unit": self.speed_unit_label,
            "a": self.a_label,
            "b": self.b_label,
            "wave_a": self.a_wave_label,
            "wave_b": self.b_wave_label,
            "event": self.event_label,
        }
        for key, text in values.items():
            if text != self._cache[key]:
                self._cache[key] = text
                labels[key].setText(text)
        self._refresh_metric_row_visibility()

    def destroy(self) -> None:
        """关闭并释放悬浮窗。"""
        self._visible = False
        self.close()
        self.deleteLater()

    def mousePressEvent(self, event) -> None:
        """记录左键拖动起点，或显示右键设置菜单。"""
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self._show_settings_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def _show_settings_menu(self, pos) -> None:
        """弹出右键菜单：显示内容设置 + 带滑块的大小调节。"""
        menu, content_action = self._build_settings_menu()
        chosen = menu.exec(pos)
        if chosen is content_action:
            self.content_settings_requested.emit()

    def _build_settings_menu(self) -> tuple[QMenu, QAction]:
        """构建右键菜单，返回菜单与"显示内容…"动作。"""
        menu = QMenu(self)
        menu.setObjectName("overlaySizeMenu")
        content_action = menu.addAction("显示内容…")
        menu.addSeparator()
        panel = QWidget(menu)
        row = QHBoxLayout(panel)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)
        slider = QSlider(Qt.Horizontal, panel)
        slider.setObjectName("overlaySizeSlider")
        slider.setRange(OVERLAY_VALUE_PX_MIN, OVERLAY_VALUE_PX_MAX)
        slider.setValue(self._value_font)
        slider.setFixedWidth(160)
        value_label = QLabel(f"{self._value_font}px", panel)
        value_label.setObjectName("overlaySizeValue")
        value_label.setFixedWidth(40)
        value_label.setAlignment(Qt.AlignCenter)
        slider.valueChanged.connect(
            lambda value: self._on_size_slider_changed(value_label, value)
        )
        row.addWidget(slider)
        row.addWidget(value_label)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        return menu, content_action

    def _on_size_slider_changed(self, label: QLabel, value: int) -> None:
        """右键菜单滑块拖动：更新数值标签、实时应用字号并通知主控制器。"""
        label.setText(f"{value}px")
        self.set_value_font(value)
        self.value_font_changed.emit(value)

    def mouseMoveEvent(self, event) -> None:
        """拖动悬浮窗。"""
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)
