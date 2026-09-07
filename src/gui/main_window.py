"""PySide6 主窗口，包含实时状态、设置和设备连接区域。"""

import ctypes
import os
import sys
from typing import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QDialog,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QSlider,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .disclaimer_dialog import show_disclaimer_dialog
from .about_dialog import show_about_dialog
from .glass import BackgroundCatalog, BackdropCanvas, GlassCard
from .styles import COLORS, setup_styles
from ..version import APP_NAME, APP_VERSION
from ..config_manager import (
    OVERLAY_VALUE_PX_DEFAULT,
    OVERLAY_VALUE_PX_MAX,
    OVERLAY_VALUE_PX_MIN,
    ConfigManager,
)
from ..runtime_paths import resource_path
from ..output_telemetry import display_waveform_name
from ..waveforms import WaveformCatalog
from .overlay import OVERLAY_CONTENT_FLAGS


def _resource_path(filename: str) -> str:
    """返回源码或 PyInstaller 环境中的资源文件路径。"""
    return resource_path(filename)


def _set_windows_app_id() -> None:
    """为 Windows Shell 设置可区分旧版本的应用标识。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WT-DGLAB.v1.0.tubiao1"
        )
    except (AttributeError, OSError):
        pass


class ValueProxy:
    """为旧主控制器保留 get/set 风格的轻量值接口。"""

    def __init__(self, value, on_change: Callable | None = None):
        self._value = value
        self._on_change = on_change

    def get(self):
        """返回当前值。"""
        return self._value

    def set(self, value) -> None:
        """设置值并同步关联控件。"""
        if value == self._value:
            return
        self._value = value
        if self._on_change:
            self._on_change(value)


class NoWheelSpinBox(QSpinBox):
    """忽略滚轮，避免浏览设置页时误改整数参数。"""

    def wheelEvent(self, event) -> None:
        """将滚轮事件交还给外层滚动区域。"""
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """忽略滚轮，避免浏览设置页时误改小数参数。"""

    def wheelEvent(self, event) -> None:
        """将滚轮事件交还给外层滚动区域。"""
        event.ignore()


class NoWheelComboBox(QComboBox):
    """忽略滚轮，避免浏览设置页时误切换波形。"""

    def wheelEvent(self, event) -> None:
        """将滚轮事件交还给外层滚动区域。"""
        event.ignore()


class StatusPill(QFrame):
    """单个连接状态指示控件。"""

    def __init__(self, name: str):
        super().__init__()
        self.setObjectName("statusPill")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(6)

        self.dot = QLabel("●")
        self.dot.setObjectName("statusDot")
        self.name_label = QLabel(name)
        self.name_label.setObjectName("statusName")
        self.value_label = QLabel("未连接")
        self.value_label.setObjectName("statusValue")
        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addWidget(self.value_label)
        self.set_connected(False)

    def set_connected(self, connected: bool) -> None:
        """更新状态文字和颜色。"""
        color = COLORS["success"] if connected else COLORS["error"]
        self.dot.setStyleSheet(f"color: {color};")
        self.value_label.setText("已连接" if connected else "未连接")


class StatusBar(GlassCard):
    """顶部状态栏，展示游戏和设备的连接状态。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("headerBar")
        self._build()

    def _build(self) -> None:
        """创建顶部状态栏内容。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        self.brand_mark = QLabel()
        self.brand_mark.setObjectName("brandMark")
        self.brand_mark.setAlignment(Qt.AlignCenter)
        cover = QPixmap(_resource_path("tubiao_ui.jpg"))
        if not cover.isNull():
            self.brand_mark.setPixmap(cover.scaled(
                38,
                38,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            ))
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("郊狼雷霆")
        title.setObjectName("brandTitle")
        subtitle = QLabel("WAR THUNDER × DG-LAB")
        subtitle.setObjectName("brandSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.wt_pill = StatusPill("战争雷霆")
        self.dg_pill = StatusPill("郊狼设备")
        self.address_label = QLabel("")
        self.address_label.setObjectName("addressText")
        self.address_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.disclaimer_button = QPushButton("注意事项")
        self.disclaimer_button.setObjectName("textButton")
        self.disclaimer_button.clicked.connect(
            lambda: show_disclaimer_dialog(self.window())
        )

        self.about_button = QPushButton("关于")
        self.about_button.setObjectName("aboutButton")
        self.about_button.clicked.connect(
            lambda: show_about_dialog(self.window())
        )

        layout.addWidget(self.brand_mark)
        layout.addLayout(title_box)
        layout.addSpacing(18)
        layout.addWidget(self.wt_pill)
        layout.addWidget(self.dg_pill)
        layout.addWidget(self.address_label, 1)
        layout.addWidget(self.disclaimer_button)
        layout.addWidget(self.about_button)

    def set_wt_status(self, connected: bool) -> None:
        """更新战争雷霆连接状态。"""
        self.wt_pill.set_connected(connected)

    def set_coyote_status(self, connected: bool, address: str = "") -> None:
        """更新郊狼连接状态和连接地址。"""
        self.dg_pill.set_connected(connected)
        self.address_label.setText(address)


class ChannelCard(GlassCard):
    """单通道实时强度卡片，点击打开该通道输出电压曲线窗口。"""

    clicked = Signal(str)

    def __init__(self, channel: str, progress_name: str):
        super().__init__()
        self._channel = channel
        self._wave_display = display_waveform_name("恒定")
        self.setObjectName("channelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        heading = QHBoxLayout()
        name = QLabel(f"{channel} 通道")
        name.setObjectName("channelName")
        self.value = QLabel("0")
        self.value.setObjectName("channelValue")
        heading.addWidget(name)
        heading.addStretch()
        heading.addWidget(self.value)

        self.progress = QProgressBar()
        self.progress.setObjectName(progress_name)
        self.progress.setRange(0, 200)
        self.progress.setTextVisible(False)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self.progress.setValue)

        wave_row = QHBoxLayout()
        wave_row.setSpacing(4)
        self.wave_label = QLabel("波形：恒定")
        self.wave_label.setObjectName("channelWaveName")
        self.wave_hint = QLabel("📈")
        self.wave_hint.setObjectName("channelWaveHint")
        self.wave_hint.setToolTip("点击卡片查看输出电压曲线")
        wave_row.addWidget(self.wave_label)
        wave_row.addStretch()
        wave_row.addWidget(self.wave_hint)

        layout.addLayout(heading)
        layout.addWidget(self.progress)
        layout.addLayout(wave_row)

        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"点击查看 {channel} 通道输出电压曲线")

    def set_value(self, value: int) -> None:
        """显示强度数值与进度。"""
        value = max(0, min(200, int(value)))
        self.value.setText(str(value))
        current = self.progress.value()
        self._animation.stop()
        self._animation.setStartValue(current)
        self._animation.setEndValue(value)
        self._animation.start()

    def set_wave_name(self, name: str) -> None:
        """显示当前输出波形名，名称不变时不重绘。"""
        display = display_waveform_name(name)
        if display == self._wave_display:
            return
        self._wave_display = display
        self.wave_label.setText(f"波形：{display}")

    def mousePressEvent(self, event) -> None:
        """左键点击卡片时发出通道点击信号。"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._channel)
            event.accept()
            return
        super().mousePressEvent(event)


class Dashboard(QFrame):
    """实时遥测与悬浮窗控制面板。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("dashboardPanel")
        self._overlay_var = ValueProxy(False)
        self._overlay_size_var = ValueProxy(OVERLAY_VALUE_PX_DEFAULT)
        self._overlay_callback: Callable | None = None
        self._overlay_content_callback: Callable | None = None
        self._scope_callback: Callable | None = None
        self._mode_callback: Callable | None = None
        self._current_mode = "aircraft"
        self._event_animation = QPropertyAnimation(self, b"eventGlow")
        self._event_animation.setDuration(900)
        self._event_animation.setStartValue(0.2)
        self._event_animation.setEndValue(1.0)
        self._event_animation.setLoopCount(-1)
        self._event_animation.setEasingCurve(QEasingCurve.InOutSine)
        self.setProperty("eventGlow", 0.0)
        self._event_animation.valueChanged.connect(self._update_event_style)
        self._build()

    @property
    def overlay_var(self) -> ValueProxy:
        """返回悬浮窗开关值接口。"""
        return self._overlay_var

    def _build(self) -> None:
        """创建实时状态面板。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        root_card = GlassCard(self)
        root_card.setObjectName("dashboardCard")
        root_layout = QVBoxLayout(root_card)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(8)
        layout.addWidget(root_card)
        layout = root_layout

        telemetry_card = GlassCard(self)
        telemetry_card.setProperty("glassDisabled", True)
        telemetry_card.setObjectName("telemetryCard")
        telemetry_layout = QVBoxLayout(telemetry_card)
        telemetry_layout.setContentsMargins(14, 14, 14, 14)
        telemetry_layout.setSpacing(6)

        eyebrow = QLabel("REAL-TIME TELEMETRY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("实时状态")
        title.setObjectName("sectionTitle")
        telemetry_layout.addWidget(eyebrow)
        telemetry_layout.addWidget(title)

        value_row = QHBoxLayout()
        self.value_label = QLabel("--.-")
        self.value_label.setObjectName("liveValue")
        self.unit_label = QLabel("G")
        self.unit_label.setObjectName("liveUnit")
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label, alignment=Qt.AlignBottom)
        value_row.addStretch()

        mode_col = QVBoxLayout()
        mode_col.setSpacing(4)
        self.mode_air_button = QToolButton()
        self.mode_air_button.setObjectName("dashboardModeButton")
        self.mode_air_button.setText("空战")
        self.mode_air_button.setCheckable(True)
        self.mode_air_button.setFixedSize(52, 26)
        self.mode_tank_button = QToolButton()
        self.mode_tank_button.setObjectName("dashboardModeButton")
        self.mode_tank_button.setText("陆战")
        self.mode_tank_button.setCheckable(True)
        self.mode_tank_button.setFixedSize(52, 26)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.mode_air_button)
        self._mode_group.addButton(self.mode_tank_button)
        self.mode_air_button.clicked.connect(
            lambda: self._on_mode_button_clicked("aircraft")
        )
        self.mode_tank_button.clicked.connect(
            lambda: self._on_mode_button_clicked("tank")
        )
        mode_col.addWidget(self.mode_air_button)
        mode_col.addWidget(self.mode_tank_button)
        value_row.addLayout(mode_col)
        telemetry_layout.addLayout(value_row)
        self.set_mode("aircraft")

        self.event_label = QLabel("")
        self.event_label.setObjectName("eventText")
        self.event_label.setWordWrap(True)
        telemetry_layout.addWidget(self.event_label)
        layout.addWidget(telemetry_card)

        self.channel_a = ChannelCard("A", "channelA")
        self.channel_b = ChannelCard("B", "channelB")
        self.channel_a.clicked.connect(self._on_channel_clicked)
        self.channel_b.clicked.connect(self._on_channel_clicked)
        layout.addWidget(self.channel_a)
        layout.addWidget(self.channel_b)
        layout.addStretch(1)

        overlay_card = GlassCard(self)
        overlay_card.setProperty("glassDisabled", True)
        overlay_card.setObjectName("overlaySettingsCard")
        overlay_layout = QVBoxLayout(overlay_card)
        overlay_layout.setContentsMargins(14, 14, 14, 14)
        overlay_layout.setSpacing(6)

        overlay_title = QLabel("游戏内悬浮窗")
        overlay_title.setObjectName("sectionTitle")
        self.overlay_check = QCheckBox("显示实时数据")
        self.overlay_check.setObjectName("overlayEnabled")
        self.overlay_check.toggled.connect(self._on_overlay_toggled)
        overlay_layout.addWidget(overlay_title)
        overlay_layout.addWidget(self.overlay_check)

        size_row = QHBoxLayout()
        size_hint = QLabel("显示大小")
        size_hint.setObjectName("hintText")
        size_row.addWidget(size_hint)
        self.overlay_size_slider = QSlider(Qt.Horizontal)
        self.overlay_size_slider.setObjectName("overlaySizeSlider")
        self.overlay_size_slider.setRange(OVERLAY_VALUE_PX_MIN, OVERLAY_VALUE_PX_MAX)
        self.overlay_size_slider.setValue(self._overlay_size_var.get())
        self.overlay_size_value = QLabel(f"{self._overlay_size_var.get()}px")
        self.overlay_size_value.setObjectName("overlaySizeValue")
        self.overlay_size_value.setMinimumWidth(40)
        self.overlay_size_slider.valueChanged.connect(self._set_value_font)
        size_row.addWidget(self.overlay_size_slider, 1)
        size_row.addWidget(self.overlay_size_value)
        overlay_layout.addLayout(size_row)

        content_button = QPushButton("悬浮窗显示内容…")
        content_button.setObjectName("overlayContentButton")
        content_button.clicked.connect(self._on_content_button)
        overlay_layout.addWidget(content_button)
        layout.addWidget(overlay_card)

        refresh_card = GlassCard(self)
        refresh_card.setProperty("glassDisabled", True)
        refresh_card.setObjectName("refreshSettingsCard")
        refresh_layout = QVBoxLayout(refresh_card)
        refresh_layout.setContentsMargins(14, 14, 14, 14)
        refresh_layout.setSpacing(6)

        refresh_title = QLabel("数据刷新")
        refresh_title.setObjectName("sectionTitle")
        refresh_layout.addWidget(refresh_title)
        refresh_row = QHBoxLayout()
        refresh_hint = QLabel("刷新间隔")
        refresh_hint.setObjectName("hintText")
        self.refresh_ms = NoWheelSpinBox()
        self.refresh_ms.setObjectName("refreshIntervalInput")
        self.refresh_ms.setRange(50, 1000)
        self.refresh_ms.setSuffix(" ms")
        refresh_row.addWidget(refresh_hint)
        refresh_row.addStretch()
        refresh_row.addWidget(self.refresh_ms)
        refresh_layout.addLayout(refresh_row)
        layout.addWidget(refresh_card)

    def _set_value_font(self, px: int) -> None:
        """更新悬浮窗主字号，并立即通知主控制器。"""
        px = max(OVERLAY_VALUE_PX_MIN, min(OVERLAY_VALUE_PX_MAX, int(px)))
        self._overlay_size_var.set(px)
        self.overlay_size_slider.blockSignals(True)
        self.overlay_size_slider.setValue(px)
        self.overlay_size_slider.blockSignals(False)
        self.overlay_size_value.setText(f"{px}px")
        self._notify_overlay_change()

    def _on_overlay_toggled(self, enabled: bool) -> None:
        """同步悬浮窗开关，并立即通知主控制器。"""
        self._overlay_var.set(enabled)
        self._notify_overlay_change()

    def set_overlay_callback(self, callback: Callable | None) -> None:
        """设置悬浮窗开关和大小改变时的处理回调。"""
        self._overlay_callback = callback

    def set_overlay_content_callback(self, callback: Callable | None) -> None:
        """设置悬浮窗显示内容设置按钮的处理回调。"""
        self._overlay_content_callback = callback

    def set_scope_callback(self, callback: Callable | None) -> None:
        """设置通道卡点击后打开输出电压曲线窗口的处理回调。"""
        self._scope_callback = callback

    def get_mode(self) -> str:
        """返回当前业务模式。"""
        return self._current_mode

    def set_mode(self, mode: str) -> None:
        """静默设置业务模式及按钮选中态。"""
        normalized = mode if mode in {"aircraft", "tank"} else "aircraft"
        self._current_mode = normalized
        self.mode_air_button.blockSignals(True)
        self.mode_tank_button.blockSignals(True)
        self.mode_air_button.setChecked(normalized == "aircraft")
        self.mode_tank_button.setChecked(normalized == "tank")
        self.mode_air_button.blockSignals(False)
        self.mode_tank_button.blockSignals(False)

    def set_mode_callback(self, callback: Callable | None) -> None:
        """设置仪表盘模式切换回调。"""
        self._mode_callback = callback

    def _on_mode_button_clicked(self, mode: str) -> None:
        """处理仪表盘模式按钮点击并过滤重复点击。"""
        if mode == self._current_mode:
            return
        self._current_mode = mode
        if self._mode_callback:
            self._mode_callback()

    def _on_channel_clicked(self, channel: str) -> None:
        """通道卡被点击 — 通知主控制器打开对应曲线窗口。"""
        if self._scope_callback:
            self._scope_callback(channel)

    def _on_content_button(self) -> None:
        """显示内容设置按钮被点击。"""
        if self._overlay_content_callback:
            self._overlay_content_callback()

    def _notify_overlay_change(self) -> None:
        """通知主控制器立即应用悬浮窗设置。"""
        if self._overlay_callback:
            self._overlay_callback()

    def set_overlay_enabled(self, enabled: bool) -> None:
        """从配置同步悬浮窗开关。"""
        self._overlay_var.set(enabled)
        self.overlay_check.blockSignals(True)
        self.overlay_check.setChecked(enabled)
        self.overlay_check.blockSignals(False)

    def set_overlay_value_font(self, px: int) -> None:
        """从配置同步悬浮窗主字号。"""
        self._set_value_font(px)

    def update_aircraft(self, gforce: float, intensity_a: int, intensity_b: int) -> None:
        """展示空战实时数据。"""
        self.value_label.setText(f"{gforce:.1f}")
        self.unit_label.setText("G")
        self._set_channels(intensity_a, intensity_b)

    def update_tank(self, speed: float, intensity_a: int, intensity_b: int) -> None:
        """展示陆战实时数据。"""
        self.value_label.setText(f"{speed:.0f}")
        self.unit_label.setText("km/h")
        self._set_channels(intensity_a, intensity_b)

    def update_event(self, label: str, intensity_a: int,
                     intensity_b: int) -> None:
        """展示事件覆盖期间的名称与双通道强度。"""
        self.value_label.setText(label)
        self.unit_label.setText("")
        self._set_channels(intensity_a, intensity_b)

    def _set_channels(self, intensity_a: int, intensity_b: int) -> None:
        """更新双通道显示。"""
        self.channel_a.set_value(intensity_a)
        self.channel_b.set_value(intensity_b)

    def show_event(self, text: str) -> None:
        """显示或清除当前事件提示。"""
        self.event_label.setText(text)
        if text and self._event_animation.state() != QPropertyAnimation.Running:
            self._event_animation.start()
        elif not text:
            self._event_animation.stop()
            self.setProperty("eventGlow", 0.0)
            self._update_event_style()

    def _update_event_style(self) -> None:
        """更新事件期间的呼吸边框。"""
        glow = float(self.property("eventGlow") or 0.0)
        self.setStyleSheet(
            f"QFrame#dashboardPanel {{ border: 1px solid rgba(236, 141, 167, {0.35 + glow * 0.45:.2f}); }}"
            if self.event_label.text() else ""
        )

    def clear(self, mode: str = "aircraft") -> None:
        """清空无效游戏数据。"""
        self.value_label.setText("--" if mode == "tank" else "--.-")
        self.unit_label.setText("km/h" if mode == "tank" else "G")
        self._set_channels(0, 0)
        self.show_event("")


class OverlayContentDialog(QDialog):
    """悬浮窗显示内容设置 — 分组复选框，勾选即时生效并持久化。"""

    FLAG_LABELS = {
        "mode": "显示模式（空战/陆战）",
        "gforce": "显示实时过载 (G)",
        "speed": "显示实时速度 (km/h)",
        "event": "显示事件提示",
        "strength_a": "显示输出强度",
        "wave_a": "显示输出波形名",
        "strength_b": "显示输出强度",
        "wave_b": "显示输出波形名",
    }
    GROUPS = (
        ("基础信息", ("mode", "gforce", "speed", "event")),
        ("A 通道", ("strength_a", "wave_a")),
        ("B 通道", ("strength_b", "wave_b")),
    )

    def __init__(self, flags: dict, on_change: Callable,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("overlayContentDialog")
        self.setWindowTitle("悬浮窗显示内容")
        self.setModal(False)
        self._on_change = on_change
        self._checkboxes: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        for title, keys in self.GROUPS:
            section = QLabel(title)
            section.setObjectName("sectionTitle")
            layout.addWidget(section)
            for key in keys:
                checkbox = QCheckBox(self.FLAG_LABELS[key])
                checkbox.toggled.connect(self._on_toggled)
                layout.addWidget(checkbox)
                self._checkboxes[key] = checkbox

        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addStretch()
        reset_button = QPushButton("恢复默认")
        reset_button.setObjectName("secondaryButton")
        reset_button.clicked.connect(self._reset_defaults)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        buttons.addWidget(reset_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.set_flags(flags)

    def set_flags(self, flags: dict) -> None:
        """同步复选框状态（不触发变更回调）。"""
        for key, checkbox in self._checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(flags.get(key, True)))
            checkbox.blockSignals(False)

    def flags(self) -> dict:
        """返回当前勾选状态。"""
        return {key: box.isChecked() for key, box in self._checkboxes.items()}

    def _on_toggled(self) -> None:
        """任一复选框变化 — 立即应用并持久化。"""
        self._on_change(self.flags())

    def _reset_defaults(self) -> None:
        """恢复全部显示并应用。"""
        self.set_flags({key: True for key in OVERLAY_CONTENT_FLAGS})
        self._on_change(self.flags())


class SettingsPanel(QFrame):
    """所有既有参数的设置面板。"""

    def __init__(self, parent: QWidget, config_mgr: ConfigManager,
                 waveform_catalog: WaveformCatalog | None = None,
                 on_save: Callable | None = None,
                 overlay_var: ValueProxy | None = None,
                 overlay_size_var: ValueProxy | None = None,
                 connection_widget=None,
                 dashboard_widget=None,
                 appearance_changed: Callable | None = None,
                 background_catalog: BackgroundCatalog | None = None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self._config_mgr = config_mgr
        self._on_save_callback = on_save
        self._overlay_var = overlay_var
        self._overlay_size_var = overlay_size_var
        self._connection_widget = connection_widget
        self._dashboard_widget = dashboard_widget
        self._appearance_changed = appearance_changed
        self._background_catalog = background_catalog or BackgroundCatalog()
        self._waveform_catalog = waveform_catalog or WaveformCatalog()
        self._waveform_catalog.reload()
        self._waveforms = self._waveform_catalog.choices()
        self._build()
        self._load_config(sync_mode=True)

    def _build(self) -> None:
        """构建模式切换、参数页和保存操作。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header_card = GlassCard(self)
        header_card.setObjectName("settingsHeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(4)
        title_row = QHBoxLayout()
        self.parameter_button = QPushButton("触发设置")
        self.parameter_button.setObjectName("modeButton")
        self.parameter_button.setCheckable(True)
        self.parameter_button.clicked.connect(self._show_parameter_page)
        title_row.addWidget(self.parameter_button)
        self.waveform_button = QPushButton("波形设置")
        self.waveform_button.setObjectName("modeButton")
        self.waveform_button.setCheckable(True)
        self.waveform_button.clicked.connect(self._open_waveform_dialog)
        title_row.addWidget(self.waveform_button)
        self.appearance_button = QPushButton("背景设置")
        self.appearance_button.setObjectName("modeButton")
        self.appearance_button.setCheckable(True)
        self.appearance_button.clicked.connect(self._open_appearance_page)
        title_row.addWidget(self.appearance_button)
        title_row.addStretch()
        header_layout.addLayout(title_row)
        layout.addWidget(header_card)

        modes = GlassCard()
        modes.setObjectName("sectionCard")
        mode_layout = QHBoxLayout(modes)
        mode_layout.setContentsMargins(6, 6, 6, 6)
        self.air_button = QToolButton()
        self.air_button.setObjectName("modeButton")
        self.air_button.setText("空战设置")
        self.air_button.setCheckable(True)
        self.tank_button = QToolButton()
        self.tank_button.setObjectName("modeButton")
        self.tank_button.setText("陆战设置")
        self.tank_button.setCheckable(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.air_button)
        self._mode_group.addButton(self.tank_button)
        self.air_button.clicked.connect(
            lambda: self._show_mode_page("aircraft")
        )
        self.tank_button.clicked.connect(
            lambda: self._show_mode_page("tank")
        )
        mode_layout.addWidget(self.air_button)
        mode_layout.addWidget(self.tank_button)
        mode_layout.addStretch()
        layout.addWidget(modes)
        self.modes = modes

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        self.pages.addWidget(self._make_air_page())
        self.pages.addWidget(self._make_tank_page())
        layout.addWidget(self.pages, 1)

        self._waveform_view = WaveformSettingsDialog(
            self, self._config_mgr, self._waveform_catalog,
            on_saved=self._show_parameter_page,
        )
        self._waveform_view.setWindowFlags(Qt.Widget)
        layout.addWidget(self._waveform_view, 1)
        self._waveform_view.hide()
        self._appearance_view = self._make_appearance_page()
        layout.addWidget(self._appearance_view, 1)
        self._appearance_view.hide()
        self.parameter_button.setChecked(True)

        actions_widget = GlassCard(self)
        actions_widget.setObjectName("settingsActionsCard")
        actions = QHBoxLayout(actions_widget)
        self.save_button = QPushButton("保存设置")
        self.save_button.setObjectName("saveButton")
        self.save_button.clicked.connect(self._on_save)
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.setObjectName("secondaryButton")
        self.reset_button.clicked.connect(self._on_reset)
        self.save_feedback = QLabel("")
        self.save_feedback.setObjectName("hintText")
        actions.addWidget(self.save_button)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.save_feedback)
        actions.addStretch()
        layout.addWidget(actions_widget)
        self.actions_widget = actions_widget

    def _make_scroll_page(self, builder: Callable[[QVBoxLayout], None]) -> QScrollArea:
        """创建可滚动设置页。"""
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(10)
        builder(layout)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _make_appearance_page(self) -> QWidget:
        """创建壁纸和背景设置页。"""
        page = QFrame()
        page.setObjectName("appearancePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        card = GlassCard()
        card.setObjectName("sectionCard")
        form = QFormLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)
        self.background_enabled = QCheckBox("启用壁纸背景")
        self.background_enabled.setObjectName("backgroundEnabled")
        self.background_combo = NoWheelComboBox()
        self.background_combo.setObjectName("backgroundSelector")
        self.background_combo.addItems(self._background_catalog.choices())
        self.background_open = QPushButton("打开背景文件夹")
        self.background_open.setObjectName("secondaryButton")
        self.background_enabled.toggled.connect(self._on_background_changed)
        self.background_combo.currentTextChanged.connect(self._on_background_selected)
        self.background_open.clicked.connect(self._open_background_folder)
        self.card_opacity_slider = QSlider(Qt.Horizontal)
        self.card_opacity_slider.setObjectName("cardOpacitySlider")
        self.card_opacity_slider.setRange(20, 90)
        self.card_opacity_slider.setSingleStep(1)
        self.card_opacity_value = QLabel("72%")
        self.card_opacity_value.setObjectName("cardOpacityValue")
        self.card_opacity_slider.valueChanged.connect(self._on_card_opacity_changed)
        form.addRow(self.background_enabled)
        form.addRow("背景图", self.background_combo)
        form.addRow("自定义壁纸", self.background_open)
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(self.card_opacity_slider, 1)
        opacity_layout.addWidget(self.card_opacity_value)
        form.addRow("卡片不透明度", opacity_row)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _make_air_page(self) -> QScrollArea:
        """创建空战设置页。"""
        return self._make_scroll_page(self._build_air_content)

    def _build_air_content(self, layout: QVBoxLayout) -> None:
        """填充空战设置。"""
        card, form = self._make_section("空战触发", "过载与通道")
        self.air_trigger_card = card
        self.ac_enabled = QCheckBox("启用过载触发")
        self.ac_enabled.setObjectName("aircraftEnabled")
        self.gforce_min = self._double_box(0, 20, 0.5, " G")
        self.gforce_max = self._double_box(0, 20, 0.5, " G")
        self.ac_ch_a = self._int_box(0, 200)
        self.ac_ch_b = self._int_box(0, 200)
        self.ac_wf_a = self._combo(self._waveforms)
        self.ac_wf_b = self._combo(self._waveforms)
        self.ac_wf_interval = self._int_box(5, 300, " 秒")
        form.addRow(self.ac_enabled)
        self._add_row(form, "过载下限", self.gforce_min)
        self._add_row(form, "过载上限", self.gforce_max)
        self._add_row(form, "A 通道最大强度", self.ac_ch_a)
        self._add_row(form, "B 通道最大强度", self.ac_ch_b)
        layout.addWidget(card)

        event_card, event_layout = self._make_event_section("事件设置", "空战击杀与坠毁反馈")
        self.air_event_card = event_card
        self.air_event_name = QLineEdit()
        self.air_event_name.setObjectName("airEventName")
        self._add_row(event_layout, "游戏昵称", self.air_event_name)
        self._make_event_controls(event_layout, "air_kill", "击杀提醒")
        self._make_event_controls(event_layout, "air_death", "被击落/坠毁惩罚")
        layout.addWidget(event_card)

    def _make_tank_page(self) -> QScrollArea:
        """创建陆战设置页。"""
        return self._make_scroll_page(self._build_tank_content)

    def _build_tank_content(self, layout: QVBoxLayout) -> None:
        """填充陆战与 CAS 设置。"""
        card, form = self._make_section("陆战触发", "速度与通道")
        self.tank_trigger_card = card
        self.tank_enabled = QCheckBox("启用速度触发")
        self.tank_enabled.setObjectName("tankEnabled")
        self.speed_min = self._double_box(0, 200, 1, " km/h")
        self.speed_max = self._double_box(0, 200, 1, " km/h")
        self.tank_ch_a = self._int_box(0, 200)
        self.tank_ch_b = self._int_box(0, 200)
        self.tank_wf_a = self._combo(self._waveforms)
        self.tank_wf_b = self._combo(self._waveforms)
        self.tank_wf_interval = self._int_box(5, 300, " 秒")
        form.addRow(self.tank_enabled)
        self._add_row(form, "速度下限", self.speed_min)
        self._add_row(form, "速度上限", self.speed_max)
        self._add_row(form, "A 通道最大强度", self.tank_ch_a)
        self._add_row(form, "B 通道最大强度", self.tank_ch_b)
        layout.addWidget(card)

        cas_card, cas_form = self._make_section("CAS 设置", "陆战模式上飞机时使用")
        self.cas_card = cas_card
        self.cas_enabled = QCheckBox("启用 CAS 触发")
        self.cas_enabled.setObjectName("casEnabled")
        self.cas_gforce_min = self._double_box(0, 20, 0.5, " G")
        self.cas_gforce_max = self._double_box(0, 20, 0.5, " G")
        self.cas_ch_a = self._int_box(0, 200)
        self.cas_ch_b = self._int_box(0, 200)
        self.cas_wf_a = self._combo(self._waveforms)
        self.cas_wf_b = self._combo(self._waveforms)
        self.cas_wf_interval = self._int_box(5, 300, " 秒")
        cas_form.addRow(self.cas_enabled)
        self._add_row(cas_form, "过载下限", self.cas_gforce_min)
        self._add_row(cas_form, "过载上限", self.cas_gforce_max)
        self._add_row(cas_form, "A 通道最大强度", self.cas_ch_a)
        self._add_row(cas_form, "B 通道最大强度", self.cas_ch_b)
        layout.addWidget(cas_card)

        event_card, event_layout = self._make_event_section("事件设置", "陆战击杀、被击毁与维修反馈")
        self.tank_event_card = event_card
        self.tank_event_name = QLineEdit()
        self.tank_event_name.setObjectName("tankEventName")
        self._add_row(event_layout, "游戏昵称", self.tank_event_name)
        self._make_event_controls(event_layout, "tank_kill", "击杀提醒")
        self._make_event_controls(event_layout, "tank_death", "被击毁惩罚")
        repair = self._make_repair_controls(event_layout)
        self.tank_repair_enabled = repair["enabled"]
        self.tank_repair_a = repair["a"]
        self.tank_repair_b = repair["b"]
        self.tank_repair_wf_a = repair["wf_a"]
        self.tank_repair_wf_b = repair["wf_b"]
        layout.addWidget(event_card)

    def _make_section(self, title: str, subtitle: str) -> tuple[QFrame, QFormLayout]:
        """创建常规设置区块。"""
        card = GlassCard()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        hint = QLabel(subtitle)
        hint.setObjectName("hintText")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addSpacing(3)
        layout.addLayout(form)
        return card, form

    def _make_event_section(self, title: str, subtitle: str) -> tuple[QFrame, QFormLayout]:
        """创建始终展开的事件设置区块。"""
        card = GlassCard()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        hint = QLabel(subtitle)
        hint.setObjectName("hintText")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addLayout(form)
        return card, form

    def _make_event_controls(self, form: QFormLayout, prefix: str, title: str) -> None:
        """创建击杀或死亡事件的完整控件组。"""
        enabled = QCheckBox(title)
        enabled.setObjectName(f"{prefix}Enabled")
        a_value = self._int_box(0, 200)
        b_value = self._int_box(0, 200)
        duration = self._double_box(0.1, 30, 0.5, " 秒")
        waveform_a = self._combo(self._waveforms)
        waveform_b = self._combo(self._waveforms)
        setattr(self, f"{prefix}_enabled", enabled)
        setattr(self, f"{prefix}_a", a_value)
        setattr(self, f"{prefix}_b", b_value)
        setattr(self, f"{prefix}_duration", duration)
        setattr(self, f"{prefix}_wf_a", waveform_a)
        setattr(self, f"{prefix}_wf_b", waveform_b)
        form.addRow(enabled)
        self._add_row(form, "  A 通道强度", a_value)
        self._add_row(form, "  B 通道强度", b_value)
        self._add_row(form, "  持续时间", duration)

    def _make_repair_controls(self, form: QFormLayout) -> dict:
        """创建维修事件控件组。"""
        controls = {
            "enabled": QCheckBox("维修惩罚"),
            "a": self._int_box(0, 200),
            "b": self._int_box(0, 200),
            "wf_a": self._combo(self._waveforms),
            "wf_b": self._combo(self._waveforms),
        }
        controls["enabled"].setObjectName("tankRepairEnabled")
        form.addRow(controls["enabled"])
        self._add_row(form, "  A 通道强度", controls["a"])
        self._add_row(form, "  B 通道强度", controls["b"])
        return controls

    def _add_row(self, form: QFormLayout, label: str, widget: QWidget) -> None:
        """为表单添加统一样式标签。"""
        label_widget = QLabel(label)
        label_widget.setObjectName("formLabel")
        form.addRow(label_widget, widget)

    def _int_box(self, minimum: int, maximum: int,
                 suffix: str = "") -> NoWheelSpinBox:
        """创建整数输入框。"""
        box = NoWheelSpinBox()
        box.setObjectName("numberInput")
        box.setRange(minimum, maximum)
        box.setSuffix(suffix)
        return box

    def _double_box(self, minimum: float, maximum: float, step: float,
                    suffix: str = "") -> NoWheelDoubleSpinBox:
        """创建小数输入框。"""
        box = NoWheelDoubleSpinBox()
        box.setObjectName("decimalInput")
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setDecimals(1)
        box.setSuffix(suffix)
        return box

    def _combo(self, values: list[str]) -> NoWheelComboBox:
        """创建下拉选项框。"""
        combo = NoWheelComboBox()
        combo.setObjectName("waveformInput")
        combo.addItems(values)
        return combo

    def _show_mode_page(self, mode: str) -> None:
        """切换空战或陆战设置页，不改变业务模式。"""
        is_air = mode != "tank"
        self.air_button.blockSignals(True)
        self.tank_button.blockSignals(True)
        self.air_button.setChecked(is_air)
        self.tank_button.setChecked(not is_air)
        self.air_button.blockSignals(False)
        self.tank_button.blockSignals(False)
        self.pages.setCurrentIndex(0 if is_air else 1)

    def get_mode_page(self) -> str:
        """返回当前查看的设置页。"""
        return "aircraft" if self.air_button.isChecked() else "tank"

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        """设置下拉项，旧配置未知时回退到第一项。"""
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_config(self, sync_mode: bool = False) -> None:
        """将当前配置写入控件。"""
        cfg = self._config_mgr.config
        ac = cfg.aircraft
        self.ac_enabled.setChecked(ac.enabled)
        self.gforce_min.setValue(ac.gforce_min)
        self.gforce_max.setValue(ac.gforce_max)
        self.ac_ch_a.setValue(ac.channel_a_max)
        self.ac_ch_b.setValue(ac.channel_b_max)
        self._set_combo_value(self.ac_wf_a, ac.waveform_a)
        self._set_combo_value(self.ac_wf_b, ac.waveform_b)
        self.ac_wf_interval.setValue(ac.random_min_a)

        tank = cfg.tank
        self.tank_enabled.setChecked(tank.enabled)
        self.speed_min.setValue(tank.speed_min)
        self.speed_max.setValue(tank.speed_max)
        self.tank_ch_a.setValue(tank.channel_a_max)
        self.tank_ch_b.setValue(tank.channel_b_max)
        self._set_combo_value(self.tank_wf_a, tank.waveform_a)
        self._set_combo_value(self.tank_wf_b, tank.waveform_b)
        self.tank_wf_interval.setValue(tank.random_min_a)

        cas = cfg.cas
        self.cas_enabled.setChecked(cas.enabled)
        self.cas_gforce_min.setValue(cas.gforce_min)
        self.cas_gforce_max.setValue(cas.gforce_max)
        self.cas_ch_a.setValue(cas.channel_a_max)
        self.cas_ch_b.setValue(cas.channel_b_max)
        self._set_combo_value(self.cas_wf_a, cas.waveform_a)
        self._set_combo_value(self.cas_wf_b, cas.waveform_b)
        self.cas_wf_interval.setValue(cas.random_min_a)

        self._load_event_controls("air_kill", cfg.events, "kill")
        self._load_event_controls("air_death", cfg.events, "death")
        self.air_event_name.setText(cfg.events.player_name)
        self._load_event_controls("tank_kill", cfg.tank_events, "kill")
        self._load_event_controls("tank_death", cfg.tank_events, "death")
        self.tank_event_name.setText(cfg.tank_events.player_name)
        self.tank_repair_enabled.setChecked(cfg.tank_events.repair_enabled)
        self.tank_repair_a.setValue(cfg.tank_events.repair_ch_a)
        self.tank_repair_b.setValue(cfg.tank_events.repair_ch_b)
        self._set_combo_value(self.tank_repair_wf_a, cfg.tank_events.repair_wf_a)
        self._set_combo_value(self.tank_repair_wf_b, cfg.tank_events.repair_wf_b)

        self._connection_widget.ws_port.setValue(cfg.app.ws_port)
        self._connection_widget.v4_relay_url.setText(cfg.app.v4_relay_url)
        self._connection_widget.set_protocol(cfg.app.dglab_protocol)
        self._dashboard_widget.refresh_ms.setValue(
            cfg.app.refresh_interval_ms
        )
        if sync_mode:
            self._dashboard_widget.set_mode(cfg.app.mode)
            self._show_mode_page(cfg.app.mode)
        if hasattr(self, "background_enabled"):
            self.background_enabled.blockSignals(True)
            self.background_combo.blockSignals(True)
            self.background_enabled.setChecked(cfg.app.background_enabled)
            self.card_opacity_slider.blockSignals(True)
            self.card_opacity_slider.setValue(max(20, min(90, cfg.app.card_opacity)))
            self.card_opacity_value.setText(f"{self.card_opacity_slider.value()}%")
            self.card_opacity_slider.blockSignals(False)
            index = self.background_combo.findText(
                "默认壁纸" if not cfg.app.background_image else cfg.app.background_image
            )
            self.background_combo.setCurrentIndex(index if index >= 0 else 0)
            self.background_combo.blockSignals(False)
            self.background_enabled.blockSignals(False)

    def _load_event_controls(self, prefix: str, config, kind: str) -> None:
        """将事件配置加载到一组控件。"""
        getattr(self, f"{prefix}_enabled").setChecked(getattr(config, f"{kind}_enabled"))
        getattr(self, f"{prefix}_a").setValue(getattr(config, f"{kind}_ch_a"))
        getattr(self, f"{prefix}_b").setValue(getattr(config, f"{kind}_ch_b"))
        getattr(self, f"{prefix}_duration").setValue(getattr(config, f"{kind}_duration"))
        self._set_combo_value(getattr(self, f"{prefix}_wf_a"), getattr(config, f"{kind}_wf_a"))
        self._set_combo_value(getattr(self, f"{prefix}_wf_b"), getattr(config, f"{kind}_wf_b"))

    def _save_event_controls(self, prefix: str, config, kind: str) -> None:
        """从一组控件保存事件配置。"""
        setattr(config, f"{kind}_enabled", getattr(self, f"{prefix}_enabled").isChecked())
        setattr(config, f"{kind}_ch_a", getattr(self, f"{prefix}_a").value())
        setattr(config, f"{kind}_ch_b", getattr(self, f"{prefix}_b").value())
        setattr(config, f"{kind}_duration", getattr(self, f"{prefix}_duration").value())

    def _on_save(self) -> None:
        """处理用户点击“保存设置”。"""
        self.save_settings()

    def save_settings(self, show_feedback: bool = True,
                      notify: bool = True,
                      strict_connection: bool = True) -> bool:
        """采集全部控件并保存，返回是否完成保存。"""
        protocol = self._connection_widget.get_protocol()
        relay_url = self._connection_widget.v4_relay_url.text().strip()
        if protocol == "v4":
            parsed_relay = urlsplit(relay_url)
            if parsed_relay.scheme not in {"ws", "wss"} or not parsed_relay.netloc:
                if strict_connection:
                    if show_feedback:
                        self._show_feedback("Relay 地址无效")
                    self._connection_widget.v4_relay_url.setFocus()
                    return False
                relay_url = self._config_mgr.config.app.v4_relay_url

        cfg = self._config_mgr.config
        ac = cfg.aircraft
        ac.enabled = self.ac_enabled.isChecked()
        ac.gforce_min = self.gforce_min.value()
        ac.gforce_max = self.gforce_max.value()
        ac.channel_a_max = self.ac_ch_a.value()
        ac.channel_b_max = self.ac_ch_b.value()

        tank = cfg.tank
        tank.enabled = self.tank_enabled.isChecked()
        tank.speed_min = self.speed_min.value()
        tank.speed_max = self.speed_max.value()
        tank.channel_a_max = self.tank_ch_a.value()
        tank.channel_b_max = self.tank_ch_b.value()

        cas = cfg.cas
        cas.enabled = self.cas_enabled.isChecked()
        cas.gforce_min = self.cas_gforce_min.value()
        cas.gforce_max = self.cas_gforce_max.value()
        cas.channel_a_max = self.cas_ch_a.value()
        cas.channel_b_max = self.cas_ch_b.value()

        cfg.events.player_name = self.air_event_name.text().strip()
        self._save_event_controls("air_kill", cfg.events, "kill")
        self._save_event_controls("air_death", cfg.events, "death")
        cfg.tank_events.player_name = self.tank_event_name.text().strip()
        self._save_event_controls("tank_kill", cfg.tank_events, "kill")
        self._save_event_controls("tank_death", cfg.tank_events, "death")
        cfg.tank_events.repair_enabled = self.tank_repair_enabled.isChecked()
        cfg.tank_events.repair_ch_a = self.tank_repair_a.value()
        cfg.tank_events.repair_ch_b = self.tank_repair_b.value()

        cfg.app.ws_port = self._connection_widget.ws_port.value()
        cfg.app.dglab_protocol = protocol
        cfg.app.v4_relay_url = (
            relay_url or "wss://trex.dungeon-lab.cn/v4"
        )
        cfg.app.refresh_interval_ms = self._dashboard_widget.refresh_ms.value()
        cfg.app.mode = self._dashboard_widget.get_mode()
        if self._overlay_var:
            cfg.app.overlay_enabled = self._overlay_var.get()
        if self._overlay_size_var:
            cfg.app.overlay_size_px = self._overlay_size_var.get()
        self._config_mgr.save()
        if show_feedback:
            self._show_feedback("已保存")
        if notify and self._on_save_callback:
            self._on_save_callback()
        return True

    def _on_reset(self) -> None:
        """恢复默认配置并刷新控件。"""
        self._config_mgr.reset_defaults()
        self._load_config(sync_mode=True)
        self._config_mgr.save()
        self._show_feedback("已恢复默认")
        if self._on_save_callback:
            self._on_save_callback()
        if self._appearance_changed:
            self._appearance_changed()

    def _open_appearance_page(self) -> None:
        """切换到背景设置页面。"""
        self.parameter_button.setChecked(False)
        self.waveform_button.setChecked(False)
        self.appearance_button.setChecked(True)
        self.pages.hide()
        self.modes.hide()
        self.actions_widget.hide()
        self._waveform_view.hide()
        self._appearance_view.show()

    def _on_background_selected(self, text: str) -> None:
        """选择壁纸后立即应用并保存。"""
        if not hasattr(self, "background_enabled"):
            return
        cfg = self._config_mgr.config.app
        cfg.background_image = "" if text == "默认壁纸" else text
        cfg.background_enabled = self.background_enabled.isChecked()
        self._config_mgr.save()
        if self._appearance_changed:
            self._appearance_changed()

    def _on_background_changed(self, enabled: bool) -> None:
        """切换背景开关后立即应用并保存。"""
        cfg = self._config_mgr.config.app
        cfg.background_enabled = bool(enabled)
        cfg.background_image = "" if self.background_combo.currentText() == "默认壁纸" else self.background_combo.currentText()
        self._config_mgr.save()
        if self._appearance_changed:
            self._appearance_changed()

    def _on_card_opacity_changed(self, value: int) -> None:
        """拖动滑条时立即应用并保存卡片不透明度。"""
        value = max(20, min(90, int(value)))
        self.card_opacity_value.setText(f"{value}%")
        self._config_mgr.config.app.card_opacity = value
        if self._appearance_changed:
            self._appearance_changed()
        self._config_mgr.save()

    def _open_background_folder(self) -> None:
        """打开用户壁纸目录并刷新下拉选项。"""
        self._background_catalog.reload()
        current = self.background_combo.currentText()
        self.background_combo.blockSignals(True)
        self.background_combo.clear()
        self.background_combo.addItems(self._background_catalog.choices())
        self.background_combo.setCurrentText(current if current in self._background_catalog.choices() else "默认壁纸")
        self.background_combo.blockSignals(False)
        self._background_catalog.ensure_directory()
        if sys.platform == "win32":
            os.startfile(str(self._background_catalog.directory))
        else:
            QFileDialog.getOpenFileName(self, "背景文件夹", str(self._background_catalog.directory))

    def _show_feedback(self, text: str) -> None:
        """短暂显示保存反馈。"""
        self.save_feedback.setText(text)
        QTimer.singleShot(1800, lambda: self.save_feedback.setText(""))

    def _open_waveform_dialog(self) -> None:
        """切换到主界面内的波形设置页面。"""
        self.parameter_button.setChecked(False)
        self.appearance_button.setChecked(False)
        self.waveform_button.setChecked(True)
        self.pages.hide()
        self.modes.hide()
        self.actions_widget.hide()
        self._appearance_view.hide()
        self._waveform_view.show()

    def _show_parameter_page(self) -> None:
        """切换回主界面的触发设置页面。"""
        self.parameter_button.setChecked(True)
        self.waveform_button.setChecked(False)
        self.appearance_button.setChecked(False)
        self._waveform_view.hide()
        self._appearance_view.hide()
        self.pages.show()
        self.modes.show()
        self.actions_widget.show()
        self._load_config()
        if self._on_save_callback:
            self._on_save_callback()


class WaveformSettingsDialog(QDialog):
    """主界面内嵌的波形资源与随机策略设置页。"""

    SCENES = {
        "aircraft": [("常规过载", "aircraft", False), ("击杀", "events", "kill"), ("被击落 / 坠毁", "events", "death")],
        "tank": [("常规速度", "tank", False), ("CAS 过载", "cas", False), ("击杀", "tank_events", "kill"), ("被击毁", "tank_events", "death"), ("维修", "tank_events", "repair")],
    }

    def __init__(self, parent: QWidget, config_mgr: ConfigManager,
                 catalog: WaveformCatalog,
                 on_saved: Callable | None = None):
        super().__init__(parent)
        self.setObjectName("waveformPage")
        self._config_mgr = config_mgr
        self._catalog = catalog
        self._on_saved = on_saved
        self._mode = "aircraft"
        self._scene_index = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        header = GlassCard(self); header.setObjectName("waveformHeader")
        header_layout = QHBoxLayout(header); header_layout.setContentsMargins(14, 10, 14, 10)
        heading = QVBoxLayout(); heading.setSpacing(2)
        title = QLabel("波形资源"); title.setObjectName("sectionTitle")
        hint = QLabel("选择场景并分别配置 A / B 通道"); hint.setObjectName("hintText")
        heading.addWidget(title); heading.addWidget(hint); header_layout.addLayout(heading); header_layout.addStretch()
        self.air_button = QToolButton(); self.air_button.setObjectName("modeButton"); self.air_button.setText("空战模式"); self.air_button.setCheckable(True)
        self.tank_button = QToolButton(); self.tank_button.setObjectName("modeButton"); self.tank_button.setText("陆战模式"); self.tank_button.setCheckable(True)
        group = QButtonGroup(self); group.setExclusive(True); group.addButton(self.air_button); group.addButton(self.tank_button)
        self.air_button.clicked.connect(lambda: self._set_mode("aircraft")); self.tank_button.clicked.connect(lambda: self._set_mode("tank"))
        header_layout.addWidget(self.air_button); header_layout.addWidget(self.tank_button); root.addWidget(header)

        body = QHBoxLayout(); body.setSpacing(10)
        nav = GlassCard(self); nav.setObjectName("waveformNav"); nav_layout = QVBoxLayout(nav); nav_layout.setContentsMargins(10, 10, 10, 10); nav_layout.setSpacing(6)
        nav_title = QLabel("场景"); nav_title.setObjectName("formLabel"); nav_layout.addWidget(nav_title)
        self.scene_list = QListWidget(); self.scene_list.setObjectName("waveformSceneList"); self.scene_list.setMinimumWidth(145); self.scene_list.setMaximumWidth(190); self.scene_list.currentRowChanged.connect(self._on_scene_changed); nav_layout.addWidget(self.scene_list, 1); body.addWidget(nav)

        self.editor = QFrame(); self.editor.setObjectName("waveformEditor"); self.editor_layout = QVBoxLayout(self.editor); self.editor_layout.setContentsMargins(14, 12, 14, 12); self.editor_layout.setSpacing(10); body.addWidget(self.editor, 1); root.addLayout(body, 1)

        footer = GlassCard(self); footer.setObjectName("waveformFooter"); footer_layout = QHBoxLayout(footer); footer_layout.setContentsMargins(12, 8, 12, 8)
        self.resource_label = QLabel(); self.resource_label.setObjectName("hintText"); footer_layout.addWidget(self.resource_label); footer_layout.addStretch()
        refresh = QPushButton("刷新波形"); refresh.setObjectName("secondaryButton"); refresh.clicked.connect(self._refresh); open_folder = QPushButton("打开文件夹"); open_folder.setObjectName("secondaryButton"); open_folder.clicked.connect(self._open_folder); footer_layout.addWidget(refresh); footer_layout.addWidget(open_folder)
        save = QPushButton("保存设置"); save.setObjectName("waveformSaveButton"); save.clicked.connect(self._save); footer_layout.addWidget(save); root.addWidget(footer)
        self._set_mode("aircraft")

    def _set_mode(self, mode: str) -> None:
        if hasattr(self, "combo_a"):
            self._commit_scene()
        self._mode = mode; self.air_button.setChecked(mode == "aircraft"); self.tank_button.setChecked(mode == "tank")
        self.scene_list.blockSignals(True); self.scene_list.clear(); self.scene_list.addItems([item[0] for item in self.SCENES[mode]]); self.scene_list.setCurrentRow(0); self.scene_list.blockSignals(False); self._scene_index = 0; self._load_scene()

    def _on_scene_changed(self, row: int) -> None:
        if row >= 0:
            self._commit_scene(); self._scene_index = row; self._load_scene()

    def _clear_editor(self) -> None:
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()

    @staticmethod
    def _card(channel: str) -> tuple[QFrame, QVBoxLayout]:
        card = GlassCard(); card.setObjectName("waveformChannelCard"); layout = QVBoxLayout(card); layout.setContentsMargins(12, 10, 12, 12); layout.setSpacing(8)
        title_row = QHBoxLayout(); title = QLabel(f"{channel} 通道"); title.setObjectName("channelName"); title_row.addWidget(title); title_row.addStretch(); layout.addLayout(title_row)
        return card, layout

    def _load_scene(self) -> None:
        self._clear_editor(); scene = self.SCENES[self._mode][self._scene_index]; target = getattr(self._config_mgr.config, scene[1]); suffix = scene[2]; event = suffix is not False
        self.combo_a = QComboBox(); self.combo_b = QComboBox(); self.combo_a.setObjectName("waveformInput"); self.combo_b.setObjectName("waveformInput"); choices = self._catalog.choices(); self.combo_a.addItems(choices); self.combo_b.addItems(choices)
        self._set_dialog_combo(self.combo_a, getattr(target, "waveform_a" if not event else f"{suffix}_wf_a", "恒定")); self._set_dialog_combo(self.combo_b, getattr(target, "waveform_b" if not event else f"{suffix}_wf_b", "恒定"))
        card_a, layout_a = self._card("A"); row_a = QHBoxLayout(); row_a.addWidget(QLabel("波形")); row_a.addWidget(self.combo_a, 1); layout_a.addLayout(row_a)
        card_b, layout_b = self._card("B"); row_b = QHBoxLayout(); row_b.addWidget(QLabel("波形")); row_b.addWidget(self.combo_b, 1); layout_b.addLayout(row_b)
        if event:
            self.random_a = QCheckBox("触发时随机选择"); self.random_b = QCheckBox("触发时随机选择"); self.random_a.setChecked(getattr(target, f"{suffix}_random_a", False)); self.random_b.setChecked(getattr(target, f"{suffix}_random_b", False)); layout_a.addWidget(self.random_a); layout_b.addWidget(self.random_b)
        else:
            self.random_a = QCheckBox("启用随机切换"); self.random_b = QCheckBox("启用随机切换"); self.min_a = self._spin(); self.max_a = self._spin(); self.min_b = self._spin(); self.max_b = self._spin(); self.random_a.setChecked(target.random_enabled_a); self.random_b.setChecked(target.random_enabled_b); self.min_a.setValue(target.random_min_a); self.max_a.setValue(target.random_max_a); self.min_b.setValue(target.random_min_b); self.max_b.setValue(target.random_max_b); layout_a.addWidget(self.random_a); layout_a.addWidget(self._range_widget(self.min_a, self.max_a)); layout_b.addWidget(self.random_b); layout_b.addWidget(self._range_widget(self.min_b, self.max_b))
        self.editor_layout.addWidget(card_a); self.editor_layout.addWidget(card_b); self.editor_layout.addStretch(); self.resource_label.setText(f"波形资源  ·  已加载 {len(self._catalog.definitions)} 个")

    @staticmethod
    def _spin() -> QSpinBox:
        box = QSpinBox(); box.setRange(5, 300); box.setSuffix(" 秒"); box.setObjectName("numberInput"); return box

    @staticmethod
    def _range_widget(min_box, max_box) -> QWidget:
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(5); layout.addWidget(QLabel("间隔")); layout.addWidget(min_box); layout.addWidget(QLabel("至")); layout.addWidget(max_box); return widget

    @staticmethod
    def _set_dialog_combo(combo: QComboBox, value: str) -> None:
        index = combo.findText(value); combo.setCurrentIndex(index if index >= 0 else 0)

    def _commit_scene(self) -> bool:
        scene = self.SCENES[self._mode][self._scene_index]; target = getattr(self._config_mgr.config, scene[1]); event = scene[2] is not False; suffix = scene[2]
        if not event and (self.min_a.value() > self.max_a.value() or self.min_b.value() > self.max_b.value()): return False
        if event:
            setattr(target, f"{suffix}_wf_a", self.combo_a.currentText()); setattr(target, f"{suffix}_wf_b", self.combo_b.currentText()); setattr(target, f"{suffix}_random_a", self.random_a.isChecked()); setattr(target, f"{suffix}_random_b", self.random_b.isChecked())
        else:
            target.waveform_a = self.combo_a.currentText(); target.waveform_b = self.combo_b.currentText(); target.random_enabled_a = self.random_a.isChecked(); target.random_enabled_b = self.random_b.isChecked(); target.random_min_a = self.min_a.value(); target.random_max_a = self.max_a.value(); target.random_min_b = self.min_b.value(); target.random_max_b = self.max_b.value()
        return True

    def _save(self) -> None:
        if not self._commit_scene(): QMessageBox.warning(self, "波形设置", "随机间隔最小值不能大于最大值"); return
        self._config_mgr.save()
        if self._on_saved: self._on_saved()

    def _refresh(self) -> None:
        result = self._catalog.reload(); self._load_scene()
        if result.errors: QMessageBox.warning(self, "波形刷新", "部分文件未加载：\n" + "\n".join(f"{n}: {e}" for n, e in result.errors))

    def _open_folder(self) -> None:
        self._catalog.ensure_directory()
        if sys.platform == "win32": os.startfile(str(self._catalog.directory))
        else: QFileDialog.getOpenFileName(self, "波形文件夹", str(self._catalog.directory))


class QRWidget(QFrame):
    """设备二维码与连接状态面板。"""

    def __init__(self, parent: QWidget,
                 on_protocol_changed: Callable | None = None):
        super().__init__(parent)
        self.setObjectName("connectionPanel")
        self._qr_image_ref: QPixmap | None = None
        self._protocol = "v3"
        self._on_protocol_changed = on_protocol_changed
        self._build()

    def _build(self) -> None:
        """创建二维码和连接状态控件。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        root_card = GlassCard(self)
        root_card.setObjectName("connectionCard")
        root_layout = QVBoxLayout(root_card)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(8)
        layout.addWidget(root_card)
        layout = root_layout
        eyebrow = QLabel("DEVICE CONNECTION")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("连接郊狼")
        title.setObjectName("sectionTitle")
        intro_card = GlassCard(self)
        intro_card.setProperty("glassDisabled", True)
        intro_card.setObjectName("connectionIntroCard")
        intro_layout = QVBoxLayout(intro_card)
        intro_layout.setContentsMargins(12, 10, 12, 10)
        intro_layout.setSpacing(4)
        intro_layout.addWidget(eyebrow)
        intro_layout.addWidget(title)
        layout.addWidget(intro_card)

        self.qr_frame = QFrame()
        self.qr_frame.setObjectName("qrFrame")
        qr_layout = QVBoxLayout(self.qr_frame)
        qr_layout.setContentsMargins(12, 12, 12, 12)
        self.qr_canvas = QLabel("二维码\n等待启动")
        self.qr_canvas.setObjectName("qrImage")
        self.qr_canvas.setAlignment(Qt.AlignCenter)
        self.qr_canvas.setMinimumSize(176, 176)
        qr_layout.addWidget(self.qr_canvas)
        layout.addWidget(self.qr_frame)

        self.status_text = QLabel("等待 WebSocket 服务启动...")
        self.status_text.setObjectName("sectionTitle")
        self.status_text.setWordWrap(True)
        self.url_text = QLabel("")
        self.url_text.setObjectName("addressText")
        self.url_text.setWordWrap(True)
        self.url_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # 连接地址是含长不可断行片段的 URL，其最小宽度提示会锁死分栏无法调窄，
        # 改为忽略水平宽度提示，由换行自行适应分栏宽度
        self.url_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        status_card = GlassCard(self)
        status_card.setProperty("glassDisabled", True)
        status_card.setObjectName("connectionStatusCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)
        status_layout.addWidget(self.status_text)
        status_layout.addWidget(self.url_text)
        layout.addWidget(status_card)

        connection_card = GlassCard()
        connection_card.setProperty("glassDisabled", True)
        connection_card.setObjectName("sectionCard")
        connection_layout = QVBoxLayout(connection_card)
        connection_layout.setContentsMargins(12, 12, 12, 12)
        connection_layout.setSpacing(7)
        connection_title = QLabel("连接设置")
        connection_title.setObjectName("sectionTitle")
        connection_hint = QLabel("协议与服务地址")
        connection_hint.setObjectName("hintText")

        protocol_row = QFrame()
        protocol_row.setObjectName("protocolSelector")
        protocol_layout = QHBoxLayout(protocol_row)
        protocol_layout.setContentsMargins(4, 4, 4, 4)
        protocol_layout.setSpacing(4)
        self.v3_button = QToolButton()
        self.v3_button.setObjectName("modeButton")
        self.v3_button.setText("V3 App")
        self.v3_button.setCheckable(True)
        self.v4_button = QToolButton()
        self.v4_button.setObjectName("modeButton")
        self.v4_button.setText("V4 App")
        self.v4_button.setCheckable(True)
        self._protocol_group = QButtonGroup(self)
        self._protocol_group.setExclusive(True)
        self._protocol_group.addButton(self.v3_button)
        self._protocol_group.addButton(self.v4_button)
        self.v3_button.clicked.connect(
            lambda: self._apply_protocol_choice("v3")
        )
        self.v4_button.clicked.connect(
            lambda: self._apply_protocol_choice("v4")
        )
        protocol_layout.addWidget(self.v3_button)
        protocol_layout.addWidget(self.v4_button)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        self.ws_port = NoWheelSpinBox()
        self.ws_port.setObjectName("wsPortInput")
        self.ws_port.setRange(1024, 65535)
        self.v4_relay_url = QLineEdit()
        self.v4_relay_url.setObjectName("v4RelayUrlInput")
        self.v4_relay_url.setPlaceholderText(
            "wss://trex.dungeon-lab.cn/v4"
        )
        self.port_label = QLabel("本机服务端端口")
        self.port_label.setObjectName("formLabel")
        self.relay_label = QLabel("V4 Relay")
        self.relay_label.setObjectName("formLabel")
        form.addRow(self.port_label, self.ws_port)
        form.addRow(self.relay_label, self.v4_relay_url)
        connection_layout.addWidget(connection_title)
        connection_layout.addWidget(connection_hint)
        connection_layout.addWidget(protocol_row)
        connection_layout.addLayout(form)
        layout.addWidget(connection_card)
        layout.addStretch()

    def set_protocol(self, protocol: str) -> None:
        """切换 V3/V4 设置项的显示状态。"""
        is_v4 = protocol == "v4"
        self._protocol = "v4" if is_v4 else "v3"
        self.v3_button.setChecked(not is_v4)
        self.v4_button.setChecked(is_v4)
        self.port_label.setVisible(not is_v4)
        self.ws_port.setVisible(not is_v4)
        self.relay_label.setVisible(is_v4)
        self.v4_relay_url.setVisible(is_v4)

    def get_protocol(self) -> str:
        """返回当前选择的 DG-LAB App 协议。"""
        return self._protocol

    def _apply_protocol_choice(self, protocol: str) -> None:
        """即时应用用户点击的协议，失败时恢复原选择。"""
        previous = self._protocol
        self.set_protocol(protocol)
        if (self._on_protocol_changed
                and self._on_protocol_changed(protocol) is False):
            self.set_protocol(previous)

    def set_qr_image(self, image) -> None:
        """将 Pillow 图片转换为 QPixmap 并显示。"""
        rgba = image.convert("RGBA").resize((160, 160))
        qimage = QImage(
            rgba.tobytes("raw", "RGBA"),
            rgba.width,
            rgba.height,
            rgba.width * 4,
            QImage.Format_RGBA8888,
        ).copy()
        self._qr_image_ref = QPixmap.fromImage(qimage)
        self.qr_canvas.setPixmap(self._qr_image_ref)
        self.qr_canvas.setText("")

    def clear_qr_image(self) -> None:
        """清除旧协议二维码并恢复等待占位。"""
        self._qr_image_ref = None
        self.qr_canvas.clear()
        self.qr_canvas.setText("二维码\n等待启动")

    def set_status(self, text: str, url: str = "") -> None:
        """更新连接状态，连接成功后收起二维码。"""
        self.status_text.setText(text)
        self.url_text.setText(url)
        self.qr_frame.setVisible("已连接" not in text)


class MainWindow(QMainWindow):
    """PySide6 主窗口控制器。"""

    def __init__(self, config_manager: ConfigManager,
                 waveform_catalog: WaveformCatalog | None = None,
                 on_mode_changed: Callable | None = None):
        _set_windows_app_id()
        existing = QApplication.instance()
        self._app = existing or QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        setup_styles(self._app)
        super().__init__()
        self.root = self
        self.setObjectName("appWindow")
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        app_icon = QIcon(_resource_path("tubiao.ico"))
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
            self._app.setWindowIcon(app_icon)
        self.resize(1280, 780)
        self.setMinimumSize(1080, 660)
        self._config_mgr = config_manager
        self._waveform_catalog = waveform_catalog or WaveformCatalog()
        self._background_catalog = BackgroundCatalog()
        self._on_mode_changed = on_mode_changed
        self._close_callback: Callable | None = None
        self._startup_topmost = False
        self._exit_requested = False
        self._tray_notice_shown = False
        self._build()
        self._build_tray(app_icon)

    def _build(self) -> None:
        """组装主界面的三栏布局。"""
        surface = BackdropCanvas(self, self._background_catalog)
        self.backdrop = surface
        self.setCentralWidget(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.status_bar = StatusBar(surface)
        layout.addWidget(self.status_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")
        self.dashboard = Dashboard(splitter)
        self.dashboard.set_overlay_enabled(self._config_mgr.config.app.overlay_enabled)
        self.dashboard.set_overlay_value_font(
            self._config_mgr.config.app.overlay_size_px
        )
        self.dashboard.set_mode(self._config_mgr.config.app.mode)
        self.qr_widget = QRWidget(
            splitter,
            on_protocol_changed=self._apply_protocol_immediately,
        )
        self.settings_panel = SettingsPanel(
            splitter,
            self._config_mgr,
            waveform_catalog=self._waveform_catalog,
            on_save=self._on_settings_saved,
            overlay_var=self.dashboard.overlay_var,
            overlay_size_var=self.dashboard._overlay_size_var,
            connection_widget=self.qr_widget,
            dashboard_widget=self.dashboard,
            appearance_changed=self._apply_appearance,
            background_catalog=self._background_catalog,
        )
        self.dashboard.set_mode_callback(self._on_dashboard_mode_changed)
        splitter.addWidget(self.dashboard)
        splitter.addWidget(self.settings_panel)
        splitter.addWidget(self.qr_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([355, 535, 350])
        layout.addWidget(splitter, 1)
        self._apply_appearance()

    def _apply_appearance(self) -> None:
        """应用并校正配置中的壁纸设置。"""
        cfg = self._config_mgr.config.app
        self._background_catalog.reload()
        canonical = self._background_catalog.canonical_name(cfg.background_image)
        if canonical is None:
            cfg.background_image = ""
            self._config_mgr.save()
        elif canonical != cfg.background_image:
            cfg.background_image = canonical
            self._config_mgr.save()
        self.backdrop.set_background(cfg.background_enabled, cfg.background_image)
        self.backdrop.set_card_opacity(cfg.card_opacity)

    def _build_tray(self, icon: QIcon) -> None:
        """创建系统托盘图标、菜单和恢复交互。"""
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setObjectName("systemTrayIcon")
        self.tray_icon.setToolTip("郊狼雷霆")

        self.tray_menu = QMenu()
        self.tray_menu.setObjectName("trayMenu")
        self.show_window_action = QAction("显示主窗口", self)
        self.show_window_action.setObjectName("showWindowAction")
        self.exit_program_action = QAction("退出程序", self)
        self.exit_program_action.setObjectName("exitProgramAction")
        self.show_window_action.triggered.connect(self.restore_from_tray)
        self.exit_program_action.triggered.connect(self._request_exit)
        self.tray_menu.addAction(self.show_window_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.exit_program_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self.tray_icon.show()

    def _on_tray_activated(
            self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """双击托盘图标时恢复主窗口。"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self) -> None:
        """从系统托盘恢复、提升并激活主窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()

    def save_current_settings(self) -> bool:
        """静默保存界面当前设置，自动保存时保留无效 Relay 旧值。"""
        return self.settings_panel.save_settings(
            show_feedback=False,
            notify=False,
            strict_connection=False,
        )

    def _request_exit(self) -> None:
        """响应托盘退出命令并交给主控制器清理资源。"""
        if self._exit_requested:
            return
        self._exit_requested = True
        self.save_current_settings()
        self.tray_icon.hide()
        if self._close_callback:
            callback = self._close_callback
            QTimer.singleShot(0, callback)
        else:
            self.quit()

    def _on_settings_saved(self) -> None:
        """设置保存后通知业务控制器。"""
        if self._on_mode_changed:
            self._on_mode_changed()

    def _on_dashboard_mode_changed(self) -> None:
        """仪表盘切换模式后立即持久化并通知业务控制器。"""
        mode = self.dashboard.get_mode()
        if self._config_mgr.config.app.mode != mode:
            self._config_mgr.config.app.mode = mode
            self._config_mgr.save()
        if self._on_mode_changed:
            self._on_mode_changed()

    def _apply_protocol_immediately(self, protocol: str) -> bool:
        """持久化协议选择并立即通知业务控制器重建连接。"""
        cfg = self._config_mgr.config.app
        if protocol == "v4":
            relay_url = self.qr_widget.v4_relay_url.text().strip()
            parsed_relay = urlsplit(relay_url)
            if (parsed_relay.scheme not in {"ws", "wss"}
                    or not parsed_relay.netloc):
                self.qr_widget.set_status("⚠ Relay 地址无效")
                self.qr_widget.v4_relay_url.setFocus()
                return False
            cfg.v4_relay_url = relay_url
        else:
            cfg.ws_port = self.qr_widget.ws_port.value()

        if cfg.dglab_protocol == protocol:
            return True
        cfg.dglab_protocol = protocol
        self._config_mgr.save()
        if self._on_mode_changed:
            self._on_mode_changed()
        return True

    def set_close_callback(self, callback: Callable) -> None:
        """设置托盘“退出程序”时的资源清理回调。"""
        self._close_callback = callback

    def get_mode(self) -> str:
        """返回当前模式。"""
        return self.dashboard.get_mode()

    @property
    def overlay_enabled(self) -> bool:
        """返回悬浮窗是否开启。"""
        return self.dashboard.overlay_var.get()

    @property
    def overlay_value_font(self) -> int:
        """返回悬浮窗主字号（像素）。"""
        return self.dashboard._overlay_size_var.get()

    def get_config(self):
        """返回当前配置对象。"""
        return self._config_mgr.config

    def run(self) -> int:
        """显示窗口并进入 Qt 主事件循环。"""
        self.show_startup()
        return self._app.exec()

    def show_startup(self) -> None:
        """在启动阶段临时置顶并请求 Windows 激活窗口。"""
        self._startup_topmost = True
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.showNormal()
        self._request_startup_activation()
        QTimer.singleShot(0, self._request_startup_activation)
        QTimer.singleShot(15000, self._release_startup_topmost)

    def _request_startup_activation(self) -> None:
        """提升主窗口并向桌面窗口管理器请求前台焦点。"""
        if not self.isVisible():
            return
        self.raise_()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()

    def _release_startup_topmost(self) -> None:
        """获得关注后解除启动置顶，避免持续遮挡游戏。"""
        if not self._startup_topmost:
            return
        was_active = self.isActiveWindow()
        self._startup_topmost = False
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.showNormal()
        if was_active:
            self._request_startup_activation()

    def event(self, event) -> bool:
        """窗口激活后延迟解除启动置顶状态。"""
        if (event.type() == QEvent.WindowActivate
                and getattr(self, "_startup_topmost", False)):
            QTimer.singleShot(500, self._release_startup_topmost)
        return super().event(event)

    def after(self, ms: int, callback: Callable) -> None:
        """兼容旧控制器的延迟回调接口。"""
        QTimer.singleShot(ms, callback)

    def quit(self) -> None:
        """关闭窗口和 Qt 事件循环。"""
        self._exit_requested = True
        self._close_callback = None
        self.tray_icon.hide()
        self.hide()
        self._app.quit()

    def closeEvent(self, event) -> None:
        """关闭按钮隐藏到托盘，托盘不可用时才真正退出。"""
        if self._exit_requested:
            event.accept()
            return
        if not self._tray_available:
            event.ignore()
            self._request_exit()
            return

        self.save_current_settings()
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self.tray_icon.showMessage(
                "郊狼雷霆仍在运行",
                "双击托盘图标可恢复窗口，右键选择“退出程序”才会完全退出。",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
