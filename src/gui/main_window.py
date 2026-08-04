"""PySide6 主窗口，包含实时状态、设置和设备连接区域。"""

import ctypes
import os
import sys
from typing import Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .disclaimer_dialog import show_disclaimer_dialog
from .styles import COLORS, setup_styles
from ..config_manager import ConfigManager
from ..waveforms import ALL_WAVEFORMS


def _resource_path(filename: str) -> str:
    """返回源码或 PyInstaller 环境中的资源文件路径。"""
    if getattr(sys, "frozen", False):
        root = sys._MEIPASS
    else:
        root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
    return os.path.join(root, filename)


def _set_windows_app_id() -> None:
    """为 Windows Shell 设置可区分旧版本的应用标识。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WT-DGLAB.v1-beta.tubiao"
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


class StatusBar(QFrame):
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

        layout.addWidget(self.brand_mark)
        layout.addLayout(title_box)
        layout.addSpacing(18)
        layout.addWidget(self.wt_pill)
        layout.addWidget(self.dg_pill)
        layout.addWidget(self.address_label, 1)
        layout.addWidget(self.disclaimer_button)

    def set_wt_status(self, connected: bool) -> None:
        """更新战争雷霆连接状态。"""
        self.wt_pill.set_connected(connected)

    def set_coyote_status(self, connected: bool, address: str = "") -> None:
        """更新郊狼连接状态和连接地址。"""
        self.dg_pill.set_connected(connected)
        self.address_label.setText(address)


class ChannelCard(QFrame):
    """单通道实时强度卡片。"""

    def __init__(self, channel: str, progress_name: str):
        super().__init__()
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
        layout.addLayout(heading)
        layout.addWidget(self.progress)

    def set_value(self, value: int) -> None:
        """显示强度数值与进度。"""
        value = max(0, min(200, int(value)))
        self.value.setText(str(value))
        self.progress.setValue(value)


class Dashboard(QFrame):
    """实时遥测与悬浮窗控制面板。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("dashboardPanel")
        self._overlay_var = ValueProxy(False)
        self._overlay_size_var = ValueProxy("中")
        self._overlay_callback: Callable | None = None
        self._size_buttons: dict[str, QToolButton] = {}
        self._build()

    @property
    def overlay_var(self) -> ValueProxy:
        """返回悬浮窗开关值接口。"""
        return self._overlay_var

    def _build(self) -> None:
        """创建实时状态面板。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        eyebrow = QLabel("REAL-TIME TELEMETRY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("实时状态")
        title.setObjectName("sectionTitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)

        value_row = QHBoxLayout()
        self.value_label = QLabel("--.-")
        self.value_label.setObjectName("liveValue")
        self.unit_label = QLabel("G")
        self.unit_label.setObjectName("liveUnit")
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label, alignment=Qt.AlignBottom)
        value_row.addStretch()
        layout.addLayout(value_row)

        self.event_label = QLabel("")
        self.event_label.setObjectName("eventText")
        self.event_label.setWordWrap(True)
        layout.addWidget(self.event_label)

        self.channel_a = ChannelCard("A", "channelA")
        self.channel_b = ChannelCard("B", "channelB")
        layout.addWidget(self.channel_a)
        layout.addWidget(self.channel_b)
        layout.addStretch(1)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("statusSeparator")
        layout.addWidget(separator)

        overlay_title = QLabel("游戏内悬浮窗")
        overlay_title.setObjectName("sectionTitle")
        self.overlay_check = QCheckBox("显示实时数据")
        self.overlay_check.setObjectName("overlayEnabled")
        self.overlay_check.toggled.connect(self._on_overlay_toggled)
        layout.addWidget(overlay_title)
        layout.addWidget(self.overlay_check)

        size_row = QHBoxLayout()
        size_hint = QLabel("显示大小")
        size_hint.setObjectName("hintText")
        size_row.addWidget(size_hint)
        size_row.addStretch()
        size_group = QButtonGroup(self)
        for size in ("大", "中", "小"):
            button = QToolButton()
            button.setObjectName("sizeButton")
            button.setText(size)
            button.setCheckable(True)
            size_group.addButton(button)
            button.clicked.connect(lambda checked=False, value=size: self._set_size(value))
            self._size_buttons[size] = button
            size_row.addWidget(button)
        layout.addLayout(size_row)

        refresh_separator = QFrame()
        refresh_separator.setFrameShape(QFrame.HLine)
        refresh_separator.setObjectName("statusSeparator")
        layout.addWidget(refresh_separator)

        refresh_title = QLabel("数据刷新")
        refresh_title.setObjectName("sectionTitle")
        layout.addWidget(refresh_title)
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
        layout.addLayout(refresh_row)

    def _set_size(self, size: str) -> None:
        """更新悬浮窗大小选择。"""
        self._overlay_size_var.set(size)
        for value, button in self._size_buttons.items():
            button.blockSignals(True)
            button.setChecked(value == size)
            button.blockSignals(False)
        self._notify_overlay_change()

    def _on_overlay_toggled(self, enabled: bool) -> None:
        """同步悬浮窗开关，并立即通知主控制器。"""
        self._overlay_var.set(enabled)
        self._notify_overlay_change()

    def set_overlay_callback(self, callback: Callable | None) -> None:
        """设置悬浮窗开关和大小改变时的处理回调。"""
        self._overlay_callback = callback

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

    def set_overlay_size(self, size: str) -> None:
        """从配置同步悬浮窗大小。"""
        self._set_size(size if size in self._size_buttons else "中")

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

    def clear(self, mode: str = "aircraft") -> None:
        """清空无效游戏数据。"""
        self.value_label.setText("--" if mode == "tank" else "--.-")
        self.unit_label.setText("km/h" if mode == "tank" else "G")
        self._set_channels(0, 0)
        self.show_event("")


class SettingsPanel(QFrame):
    """所有既有参数的设置面板。"""

    def __init__(self, parent: QWidget, config_mgr: ConfigManager,
                 on_save: Callable | None = None,
                 on_mode_changed: Callable | None = None,
                 overlay_var: ValueProxy | None = None,
                 overlay_size_var: ValueProxy | None = None,
                 connection_widget=None,
                 dashboard_widget=None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self._config_mgr = config_mgr
        self._on_save_callback = on_save
        self._on_mode_changed_callback = on_mode_changed
        self._overlay_var = overlay_var
        self._overlay_size_var = overlay_size_var
        self._connection_widget = connection_widget
        self._dashboard_widget = dashboard_widget
        self._waveforms = ALL_WAVEFORMS + ["随机"]
        self._build()
        self._load_config()

    def _build(self) -> None:
        """构建模式切换、参数页和保存操作。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("参数设置")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        modes = QFrame()
        modes.setObjectName("sectionCard")
        mode_layout = QHBoxLayout(modes)
        mode_layout.setContentsMargins(6, 6, 6, 6)
        self.air_button = QToolButton()
        self.air_button.setObjectName("modeButton")
        self.air_button.setText("空战")
        self.air_button.setCheckable(True)
        self.tank_button = QToolButton()
        self.tank_button.setObjectName("modeButton")
        self.tank_button.setText("陆战")
        self.tank_button.setCheckable(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.air_button)
        self._mode_group.addButton(self.tank_button)
        self.air_button.clicked.connect(lambda: self._set_mode("aircraft"))
        self.tank_button.clicked.connect(lambda: self._set_mode("tank"))
        mode_layout.addWidget(self.air_button)
        mode_layout.addWidget(self.tank_button)
        mode_layout.addStretch()
        layout.addWidget(modes)

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        self.pages.addWidget(self._make_air_page())
        self.pages.addWidget(self._make_tank_page())
        layout.addWidget(self.pages, 1)

        actions = QHBoxLayout()
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
        layout.addLayout(actions)

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

    def _make_air_page(self) -> QScrollArea:
        """创建空战设置页。"""
        return self._make_scroll_page(self._build_air_content)

    def _build_air_content(self, layout: QVBoxLayout) -> None:
        """填充空战设置。"""
        card, form = self._make_section("空战触发", "过载与通道")
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
        self._add_row(form, "A 通道波形", self.ac_wf_a)
        self._add_row(form, "B 通道波形", self.ac_wf_b)
        self._add_row(form, "随机间隔", self.ac_wf_interval)
        layout.addWidget(card)

        event_card, event_layout = self._make_collapsible("事件设置", "空战击杀与坠毁反馈")
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
        card, form = self._make_section("陆战触发", "速度、波形与通道")
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
        self._add_row(form, "A 通道波形", self.tank_wf_a)
        self._add_row(form, "B 通道波形", self.tank_wf_b)
        self._add_row(form, "随机间隔", self.tank_wf_interval)
        layout.addWidget(card)

        cas_card, cas_form = self._make_section("CAS 设置", "陆战模式上飞机时使用")
        self.cas_gforce_min = self._double_box(0, 20, 0.5, " G")
        self.cas_gforce_max = self._double_box(0, 20, 0.5, " G")
        self.cas_ch_a = self._int_box(0, 200)
        self.cas_ch_b = self._int_box(0, 200)
        self.cas_wf_a = self._combo(self._waveforms)
        self.cas_wf_b = self._combo(self._waveforms)
        self.cas_wf_interval = self._int_box(5, 300, " 秒")
        self._add_row(cas_form, "过载下限", self.cas_gforce_min)
        self._add_row(cas_form, "过载上限", self.cas_gforce_max)
        self._add_row(cas_form, "A 通道最大强度", self.cas_ch_a)
        self._add_row(cas_form, "B 通道最大强度", self.cas_ch_b)
        self._add_row(cas_form, "A 通道波形", self.cas_wf_a)
        self._add_row(cas_form, "B 通道波形", self.cas_wf_b)
        self._add_row(cas_form, "随机间隔", self.cas_wf_interval)
        layout.addWidget(cas_card)

        event_card, event_layout = self._make_collapsible("事件设置", "陆战击杀、被击毁与维修反馈")
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
        card = QFrame()
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

    def _make_collapsible(self, title: str, subtitle: str) -> tuple[QFrame, QFormLayout]:
        """创建默认收起的事件设置区块。"""
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        toggle = QToolButton()
        toggle.setObjectName("textButton")
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)
        hint = QLabel(subtitle)
        hint.setObjectName("hintText")
        content = QWidget()
        content.setObjectName("collapsibleContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 8, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        content_layout.addLayout(form)
        content.setVisible(False)

        def set_expanded(expanded: bool) -> None:
            toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            content.setVisible(expanded)

        toggle.toggled.connect(set_expanded)
        layout.addWidget(toggle)
        layout.addWidget(hint)
        layout.addWidget(content)
        return card, form

    def _make_event_controls(self, form: QFormLayout, prefix: str, title: str) -> None:
        """创建击杀或死亡事件的完整控件组。"""
        enabled = QCheckBox(title)
        enabled.setObjectName(f"{prefix}Enabled")
        a_value = self._int_box(0, 200)
        b_value = self._int_box(0, 200)
        duration = self._double_box(0.1, 30, 0.5, " 秒")
        waveform_a = self._combo(ALL_WAVEFORMS)
        waveform_b = self._combo(ALL_WAVEFORMS)
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
        self._add_row(form, "  A 通道波形", waveform_a)
        self._add_row(form, "  B 通道波形", waveform_b)

    def _make_repair_controls(self, form: QFormLayout) -> dict:
        """创建维修事件控件组。"""
        controls = {
            "enabled": QCheckBox("维修惩罚"),
            "a": self._int_box(0, 200),
            "b": self._int_box(0, 200),
            "wf_a": self._combo(ALL_WAVEFORMS),
            "wf_b": self._combo(ALL_WAVEFORMS),
        }
        controls["enabled"].setObjectName("tankRepairEnabled")
        form.addRow(controls["enabled"])
        self._add_row(form, "  A 通道强度", controls["a"])
        self._add_row(form, "  B 通道强度", controls["b"])
        self._add_row(form, "  A 通道波形", controls["wf_a"])
        self._add_row(form, "  B 通道波形", controls["wf_b"])
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

    def _set_mode(self, mode: str, notify: bool = True) -> None:
        """切换空战或陆战设置页。"""
        is_air = mode == "aircraft"
        self.air_button.blockSignals(True)
        self.tank_button.blockSignals(True)
        self.air_button.setChecked(is_air)
        self.tank_button.setChecked(not is_air)
        self.air_button.blockSignals(False)
        self.tank_button.blockSignals(False)
        self.pages.setCurrentIndex(0 if is_air else 1)
        if notify and self._on_mode_changed_callback:
            self._on_mode_changed_callback()

    def get_mode(self) -> str:
        """返回当前选择的模式。"""
        return "aircraft" if self.air_button.isChecked() else "tank"

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        """设置下拉项，旧配置未知时回退到第一项。"""
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_config(self) -> None:
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
        self.ac_wf_interval.setValue(ac.random_interval)

        tank = cfg.tank
        self.tank_enabled.setChecked(tank.enabled)
        self.speed_min.setValue(tank.speed_min)
        self.speed_max.setValue(tank.speed_max)
        self.tank_ch_a.setValue(tank.channel_a_max)
        self.tank_ch_b.setValue(tank.channel_b_max)
        self._set_combo_value(self.tank_wf_a, tank.waveform_a)
        self._set_combo_value(self.tank_wf_b, tank.waveform_b)
        self.tank_wf_interval.setValue(tank.random_interval)

        cas = cfg.cas
        self.cas_gforce_min.setValue(cas.gforce_min)
        self.cas_gforce_max.setValue(cas.gforce_max)
        self.cas_ch_a.setValue(cas.channel_a_max)
        self.cas_ch_b.setValue(cas.channel_b_max)
        self._set_combo_value(self.cas_wf_a, cas.waveform_a)
        self._set_combo_value(self.cas_wf_b, cas.waveform_b)
        self.cas_wf_interval.setValue(cas.random_interval)

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
        self._set_mode(cfg.app.mode)

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
        setattr(config, f"{kind}_wf_a", getattr(self, f"{prefix}_wf_a").currentText())
        setattr(config, f"{kind}_wf_b", getattr(self, f"{prefix}_wf_b").currentText())

    def _on_save(self) -> None:
        """保存所有既有设置字段。"""
        protocol = self._connection_widget.get_protocol()
        relay_url = self._connection_widget.v4_relay_url.text().strip()
        if protocol == "v4":
            parsed_relay = urlsplit(relay_url)
            if parsed_relay.scheme not in {"ws", "wss"} or not parsed_relay.netloc:
                self._show_feedback("Relay 地址无效")
                self._connection_widget.v4_relay_url.setFocus()
                return

        cfg = self._config_mgr.config
        ac = cfg.aircraft
        ac.enabled = self.ac_enabled.isChecked()
        ac.gforce_min = self.gforce_min.value()
        ac.gforce_max = self.gforce_max.value()
        ac.channel_a_max = self.ac_ch_a.value()
        ac.channel_b_max = self.ac_ch_b.value()
        ac.waveform_a = self.ac_wf_a.currentText()
        ac.waveform_b = self.ac_wf_b.currentText()
        ac.random_interval = self.ac_wf_interval.value()

        tank = cfg.tank
        tank.enabled = self.tank_enabled.isChecked()
        tank.speed_min = self.speed_min.value()
        tank.speed_max = self.speed_max.value()
        tank.channel_a_max = self.tank_ch_a.value()
        tank.channel_b_max = self.tank_ch_b.value()
        tank.waveform_a = self.tank_wf_a.currentText()
        tank.waveform_b = self.tank_wf_b.currentText()
        tank.random_interval = self.tank_wf_interval.value()

        cas = cfg.cas
        cas.gforce_min = self.cas_gforce_min.value()
        cas.gforce_max = self.cas_gforce_max.value()
        cas.channel_a_max = self.cas_ch_a.value()
        cas.channel_b_max = self.cas_ch_b.value()
        cas.waveform_a = self.cas_wf_a.currentText()
        cas.waveform_b = self.cas_wf_b.currentText()
        cas.random_interval = self.cas_wf_interval.value()

        cfg.events.player_name = self.air_event_name.text().strip()
        self._save_event_controls("air_kill", cfg.events, "kill")
        self._save_event_controls("air_death", cfg.events, "death")
        cfg.tank_events.player_name = self.tank_event_name.text().strip()
        self._save_event_controls("tank_kill", cfg.tank_events, "kill")
        self._save_event_controls("tank_death", cfg.tank_events, "death")
        cfg.tank_events.repair_enabled = self.tank_repair_enabled.isChecked()
        cfg.tank_events.repair_ch_a = self.tank_repair_a.value()
        cfg.tank_events.repair_ch_b = self.tank_repair_b.value()
        cfg.tank_events.repair_wf_a = self.tank_repair_wf_a.currentText()
        cfg.tank_events.repair_wf_b = self.tank_repair_wf_b.currentText()

        cfg.app.ws_port = self._connection_widget.ws_port.value()
        cfg.app.dglab_protocol = protocol
        cfg.app.v4_relay_url = (
            relay_url or "wss://trex.dungeon-lab.cn/v4"
        )
        cfg.app.refresh_interval_ms = self._dashboard_widget.refresh_ms.value()
        cfg.app.mode = self.get_mode()
        if self._overlay_var:
            cfg.app.overlay_enabled = self._overlay_var.get()
        if self._overlay_size_var:
            cfg.app.overlay_size = self._overlay_size_var.get()
        self._config_mgr.save()
        self._show_feedback("已保存")
        if self._on_save_callback:
            self._on_save_callback()

    def _on_reset(self) -> None:
        """恢复默认配置并刷新控件。"""
        self._config_mgr.reset_defaults()
        self._load_config()
        self._config_mgr.save()
        self._show_feedback("已恢复默认")
        if self._on_save_callback:
            self._on_save_callback()

    def _show_feedback(self, text: str) -> None:
        """短暂显示保存反馈。"""
        self.save_feedback.setText(text)
        QTimer.singleShot(1800, lambda: self.save_feedback.setText(""))


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
        eyebrow = QLabel("DEVICE CONNECTION")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("连接郊狼")
        title.setObjectName("sectionTitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)

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
        layout.addWidget(self.status_text)
        layout.addWidget(self.url_text)

        connection_card = QFrame()
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
                 on_mode_changed: Callable | None = None):
        _set_windows_app_id()
        existing = QApplication.instance()
        self._app = existing or QApplication(sys.argv)
        setup_styles(self._app)
        super().__init__()
        self.root = self
        self.setObjectName("appWindow")
        self.setWindowTitle("郊狼雷霆 v1 beta")
        app_icon = QIcon(_resource_path("tubiao.ico"))
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
            self._app.setWindowIcon(app_icon)
        self.resize(1280, 780)
        self.setMinimumSize(1080, 660)
        self._config_mgr = config_manager
        self._on_mode_changed = on_mode_changed
        self._close_callback: Callable | None = None
        self._build()

    def _build(self) -> None:
        """组装主界面的三栏布局。"""
        surface = QWidget()
        surface.setObjectName("appSurface")
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
        self.dashboard.set_overlay_size(self._config_mgr.config.app.overlay_size)
        self.qr_widget = QRWidget(
            splitter,
            on_protocol_changed=self._apply_protocol_immediately,
        )
        self.settings_panel = SettingsPanel(
            splitter,
            self._config_mgr,
            on_save=self._on_settings_saved,
            on_mode_changed=self._on_mode_changed,
            overlay_var=self.dashboard.overlay_var,
            overlay_size_var=self.dashboard._overlay_size_var,
            connection_widget=self.qr_widget,
            dashboard_widget=self.dashboard,
        )
        splitter.addWidget(self.dashboard)
        splitter.addWidget(self.settings_panel)
        splitter.addWidget(self.qr_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([295, 620, 285])
        layout.addWidget(splitter, 1)

    def _on_settings_saved(self) -> None:
        """设置保存后通知业务控制器。"""
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
        """设置用户关闭主窗口时的清理回调。"""
        self._close_callback = callback

    def get_mode(self) -> str:
        """返回当前模式。"""
        return self.settings_panel.get_mode()

    @property
    def overlay_enabled(self) -> bool:
        """返回悬浮窗是否开启。"""
        return self.dashboard.overlay_var.get()

    @property
    def overlay_size(self) -> str:
        """返回悬浮窗大小设置。"""
        return self.dashboard._overlay_size_var.get()

    def get_config(self):
        """返回当前配置对象。"""
        return self._config_mgr.config

    def run(self) -> int:
        """显示窗口并进入 Qt 主事件循环。"""
        self.show()
        return self._app.exec()

    def after(self, ms: int, callback: Callable) -> None:
        """兼容旧控制器的延迟回调接口。"""
        QTimer.singleShot(ms, callback)

    def quit(self) -> None:
        """关闭窗口和 Qt 事件循环。"""
        self._close_callback = None
        self.hide()
        self._app.quit()

    def closeEvent(self, event) -> None:
        """将窗口关闭操作交给主控制器清理资源。"""
        if self._close_callback:
            callback = self._close_callback
            event.ignore()
            QTimer.singleShot(0, callback)
            return
        event.accept()
