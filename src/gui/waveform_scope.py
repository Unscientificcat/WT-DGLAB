"""输出电压波形曲线组件与单通道曲线窗口。

数据来自控制器的 OutputTelemetry 快照：每个批次记录了实际下发的
4 个 25ms 采样点（最终幅度 0-100），绘制时按批次真实间隔平铺采样点，
电压刻度与强度条一致（幅度 × 2 → 0-200）。
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..output_telemetry import (
    ChannelOutputSnapshot,
    display_waveform_name,
)
from .styles import COLORS

# 横轴时间窗与采样点时长
WINDOW_SECONDS = 6.0
POINT_SECONDS = 0.025
# 最新批次超过该时长仍无新数据，视为输出已停止（正常输出约 0.2s 一批）
STALE_SECONDS = 0.6
# 纵轴刻度与强度条一致
MAX_VOLTAGE = 200


def _empty_snapshot() -> ChannelOutputSnapshot:
    """返回无数据快照，供未连接时清空曲线。"""
    return ChannelOutputSnapshot("恒定", 0, False, ())


class WaveformScope(QWidget):
    """滚动显示单通道输出电压（0-200）的示波器画布。"""

    def __init__(self, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        self._fill = QColor(color)
        self._fill.setAlpha(38)
        self._batches: tuple = ()
        self._strength = 0
        self.setMinimumHeight(120)

    def set_data(self, snapshot: ChannelOutputSnapshot) -> None:
        """更新批次数据并重绘。"""
        self._batches = snapshot.batches
        self._strength = snapshot.strength
        self.update()

    def _build_points(self, now: float) -> list[tuple[float, float]]:
        """把批次采样点平铺为 (时刻, 电压) 折线点，旧→新。"""
        window_start = now - WINDOW_SECONDS
        recent = [item for item in self._batches if item.t >= window_start]
        if not recent or (now - recent[-1].t) > STALE_SECONDS:
            return []
        points: list[tuple[float, float]] = []
        for index, batch in enumerate(recent):
            start = max(batch.t, window_start)
            end = recent[index + 1].t if index + 1 < len(recent) else now
            moment = start
            while moment < end - 1e-9:
                for amplitude in batch.amplitudes:
                    if moment >= end:
                        break
                    points.append((moment, amplitude * 2))
                    moment += POINT_SECONDS
        return points

    def paintEvent(self, event) -> None:
        """绘制网格、电压曲线与当前强度参考线。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        margin = 10.0
        top = margin
        bottom = self.height() - margin
        left = margin + 16.0
        right = self.width() - margin
        span = max(1.0, right - left)
        height = max(1.0, bottom - top)

        def to_x(moment: float) -> float:
            return right - (now - moment) / WINDOW_SECONDS * span

        def to_y(voltage: float) -> float:
            return bottom - max(0.0, min(MAX_VOLTAGE, voltage)) / MAX_VOLTAGE * height

        now = time.monotonic()
        background = QColor(COLORS["bg_soft"])
        background.setAlpha(150)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 6, 6)

        # 横向网格与纵轴刻度
        grid_pen = QPen(QColor(COLORS["border"]), 1)
        painter.setPen(grid_pen)
        for voltage in (50, 100, 150):
            y = to_y(voltage)
            painter.drawLine(int(left), int(y), int(right), int(y))
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(2, int(to_y(MAX_VOLTAGE)) + 10, "200")
        painter.drawText(2, int(bottom) - 2, "0")

        # 底部零线
        zero_pen = QPen(QColor(COLORS["border"]), 1)
        painter.setPen(zero_pen)
        painter.drawLine(int(left), int(bottom), int(right), int(bottom))

        # 当前强度虚线参考线
        if self._strength > 0:
            dashed = QPen(QColor(COLORS["text_secondary"]), 1, Qt.DashLine)
            painter.setPen(dashed)
            y = to_y(self._strength)
            painter.drawLine(int(left), int(y), int(right), int(y))

        points = self._build_points(now)
        if len(points) >= 2:
            path = QPainterPath()
            path.moveTo(to_x(points[0][0]), to_y(points[0][1]))
            for moment, voltage in points[1:]:
                path.lineTo(to_x(moment), to_y(voltage))

            fill = QPainterPath(path)
            fill.lineTo(to_x(points[-1][0]), bottom)
            fill.lineTo(to_x(points[0][0]), bottom)
            fill.closeSubpath()
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._fill)
            painter.drawPath(fill)

            line_pen = QPen(self._color, 1.6)
            painter.setPen(line_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)


class ChannelScopeDialog(QDialog):
    """单通道输出电压曲线窗口（非模态，由 App 按通道单例管理）。"""

    def __init__(self, channel: str, telemetry_provider, bound_provider,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._channel = channel if channel in ("A", "B") else "A"
        self._telemetry_provider = telemetry_provider
        self._bound_provider = bound_provider

        self.setObjectName("channelScopeDialog")
        self.setModal(False)
        self.setWindowTitle(f"{self._channel} 通道输出电压曲线")
        self.setMinimumSize(420, 240)

        color = COLORS["primary"] if self._channel == "A" else COLORS["aqua"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        self.info_label = QLabel("未连接郊狼设备")
        self.info_label.setObjectName("scopeInfoLabel")
        layout.addWidget(self.info_label)

        self.scope = WaveformScope(color, self)
        layout.addWidget(self.scope, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

    def _refresh(self) -> None:
        """按 100ms 周期读取遥测快照并刷新曲线与信息行。"""
        telemetry = None
        if callable(self._telemetry_provider):
            telemetry = self._telemetry_provider()
        bound = bool(self._bound_provider())
        if telemetry is None or not bound:
            self.info_label.setText("未连接郊狼设备")
            self.scope.set_data(_empty_snapshot())
            return
        snapshot = telemetry.snapshot(self._channel)
        state = "" if snapshot.active else "（未输出）"
        self.info_label.setText(
            f"波形：{display_waveform_name(snapshot.name)}　·　"
            f"强度：{snapshot.strength}{state}"
        )
        self.scope.set_data(snapshot)

    def showEvent(self, event) -> None:
        """显示时启动刷新定时器。"""
        self._refresh()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        """隐藏时停止刷新定时器。"""
        self._timer.stop()
        super().hideEvent(event)
