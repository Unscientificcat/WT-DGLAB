"""波形名显示、通道卡点击与输出电压曲线窗口回归测试。"""

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import CoyoteV4Controller
from src.gui.main_window import ChannelCard
from src.gui.waveform_scope import ChannelScopeDialog, WaveformScope
from src.output_telemetry import OutputTelemetry
from src.waveforms import WaveformCatalog

_APP = QApplication.instance() or QApplication([])


class FakeV4WebSocket:
    """记录 V4 控制器发送内容的简易 WebSocket。"""

    def __init__(self):
        self.messages = []

    async def send(self, message):
        """记录一条出站消息。"""
        self.messages.append(message)

    async def close(self):
        """记录关闭操作。"""
        pass


class FakeV3Client:
    """记录 V3 控制器下发的脉冲。"""

    def __init__(self):
        self.added = []

    async def set_strength(self, channel, operation_type, value):
        """记录强度设置。"""
        pass

    async def clear_pulses(self, channel):
        """记录清空操作。"""
        pass

    async def add_pulses(self, channel, *pulses):
        """记录一次波形下发。"""
        self.added.append(pulses)


def _write_waveform_file(tmp_path, name="测试波形.pulse"):
    """在临时 waveforms 目录写入一条最小可解析的 .pulse 波形。"""
    text = "Dungeonlab+pulse:0,1,0=10,10,0,1,1/50-0,100-1"
    directory = tmp_path / "waveforms"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")
    catalog = WaveformCatalog(tmp_path)
    catalog.reload()
    return catalog


@pytest.mark.asyncio
async def test_v4_constant_strength_records_output_batch():
    """V4 恒定模式按强度下发批次，遥测记录最终幅度与波形名。"""
    controller = CoyoteV4Controller()
    controller._websocket = FakeV4WebSocket()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._status.bound = True

    await controller._execute_command(("strength", "A", 100))

    snapshot = controller.telemetry.snapshot("A")
    assert snapshot.name == "恒定"
    assert snapshot.strength == 100
    assert snapshot.active
    # 恒定波形幅度按强度/200 缩放：100/200 × 100 = 50，电压显示 100
    assert snapshot.batches[-1].amplitudes == (50, 50, 50, 50)


@pytest.mark.asyncio
async def test_v4_zero_strength_records_silence():
    """V4 强度归零后遥测记录静默。"""
    controller = CoyoteV4Controller()
    controller._websocket = FakeV4WebSocket()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._status.bound = True

    await controller._execute_command(("strength", "B", 60))
    await controller._execute_command(("strength", "B", 0))

    snapshot = controller.telemetry.snapshot("B")
    assert not snapshot.active
    assert snapshot.strength == 0
    assert snapshot.batches[-1].amplitudes == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_v4_preset_waveform_records_name_and_scaled_amplitudes(tmp_path):
    """V4 切换预设波形后遥测跟随更新，幅度按强度缩放。"""
    catalog = _write_waveform_file(tmp_path)
    controller = CoyoteV4Controller(catalog=catalog)

    controller._set_waveform("A", "测试波形.pulse")
    assert controller.telemetry.snapshot("A").name == "测试波形.pulse"

    controller._websocket = FakeV4WebSocket()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._status.bound = True
    await controller._execute_command(("strength", "A", 100))

    snapshot = controller.telemetry.snapshot("A")
    # 预设首帧为曲线点 50 的 4 个采样，按强度 100/200=0.5 缩放为 25
    assert snapshot.batches[-1].amplitudes == (25, 25, 25, 25)


@pytest.mark.asyncio
async def test_v4_unknown_waveform_falls_back_to_constant():
    """未知波形名回退恒定并同步到遥测。"""
    controller = CoyoteV4Controller()

    controller._set_waveform("A", "不存在.pulse")

    assert controller.telemetry.snapshot("A").name == "恒定"


@pytest.mark.asyncio
async def test_v4_reset_channel_records_silence():
    """V4 归零通道（重置）同样在遥测中记录静默。"""
    controller = CoyoteV4Controller()
    controller._websocket = FakeV4WebSocket()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._status.bound = True

    await controller._reset_channel("A")

    snapshot = controller.telemetry.snapshot("A")
    assert not snapshot.active
    assert snapshot.batches[-1].amplitudes == (0, 0, 0, 0)


@pytest.mark.asyncio
async def test_v3_strength_records_constant_batch_and_silence():
    """V3 恒定模式记录批次，归零时记录静默。"""
    controller = CoyoteController(port=8999)
    controller._client = FakeV3Client()
    controller._status.bound = True

    await controller._exec_command(("strength", "A", 100))
    snapshot = controller.telemetry.snapshot("A")
    assert snapshot.name == "恒定"
    assert snapshot.strength == 100
    # V3 恒定幅度 = 强度 // 2 = 50，电压显示 100
    assert snapshot.batches[-1].amplitudes == (50, 50, 50, 50)

    await controller._exec_command(("strength", "A", 0))
    assert not controller.telemetry.snapshot("A").active


@pytest.mark.asyncio
async def test_v3_waveform_command_records_player_name(tmp_path):
    """V3 波形命令切换后遥测记录播放器当前波形名。"""
    catalog = _write_waveform_file(tmp_path)
    controller = CoyoteController(port=8999, catalog=catalog)
    controller._client = FakeV3Client()

    await controller._exec_command(("waveform", "A", "测试波形.pulse"))

    assert controller.telemetry.snapshot("A").name == "测试波形.pulse"
    assert controller.telemetry.snapshot("B").name == "恒定"


def test_channel_card_shows_wave_name_and_emits_click():
    """通道卡显示去后缀波形名，左键点击发出通道信号。"""
    card = ChannelCard("A", "channelA")
    seen = []
    card.clicked.connect(seen.append)

    card.set_wave_name("挥鞭.pulse")
    assert card.wave_label.text() == "波形：挥鞭"

    card.set_wave_name("挥鞭.pulse")
    card.set_wave_name("恒定")
    assert card.wave_label.text() == "波形：恒定"

    QTest.mouseClick(card, Qt.LeftButton)
    assert seen == ["A"]
    card.deleteLater()


def test_dashboard_forwards_channel_click():
    """仪表盘把通道卡点击转发给注册的回调。"""
    from src.gui.main_window import Dashboard

    callback = Mock()
    window = QWidget()
    dashboard = Dashboard(window)
    dashboard.set_scope_callback(callback)

    dashboard.channel_a.clicked.emit("A")

    callback.assert_called_once_with("A")
    dashboard.deleteLater()
    window.deleteLater()


def test_scope_paints_recorded_batches():
    """示波器画布能按批次数据离屏渲染出非空白图像。"""
    telemetry = OutputTelemetry()
    now = time.monotonic()
    for index in range(6):
        telemetry.record_pulse("A", (index * 20, 0, 0, 0), 100)
    # 手工把批次时间铺开到最近几秒，避免测试中瞬时记录全部聚在同一时刻
    from src.output_telemetry import PulseBatch

    with telemetry._lock:
        original = list(telemetry._batches["A"])
    spread = tuple(
        PulseBatch(now - 5 + index * 0.2, batch.amplitudes, batch.strength)
        for index, batch in enumerate(original)
    )
    with telemetry._lock:
        telemetry._batches["A"].clear()
        telemetry._batches["A"].extend(spread)

    scope = WaveformScope("#4B89D8")
    scope.resize(300, 120)
    snapshot = telemetry.snapshot("A")
    scope.set_data(snapshot)
    image = scope.grab().toImage()

    assert not image.isNull()
    # 曲线和背景不可能单色：采样多个像素至少出现两种颜色
    colors = {image.pixel(x, y) for x in range(0, 300, 20) for y in range(0, 120, 10)}
    assert len(colors) > 1
    scope.deleteLater()


def test_scope_dialog_shows_connection_state():
    """未连接郊狼时信息行显示未连接，连接后显示波形与强度。"""
    telemetry = OutputTelemetry()
    telemetry.record_waveform("A", "挥鞭.pulse")
    telemetry.record_pulse("A", (60, 60, 60, 60), 120)
    dialog = ChannelScopeDialog(
        "A",
        telemetry_provider=lambda: telemetry,
        bound_provider=lambda: False,
    )
    dialog._refresh()
    assert dialog.info_label.text() == "未连接郊狼设备"

    dialog._bound_provider = lambda: True
    dialog._refresh()
    assert "波形：挥鞭" in dialog.info_label.text()
    assert "强度：120" in dialog.info_label.text()
    dialog.deleteLater()


def test_scope_dialog_timer_runs_only_when_visible():
    """显示窗口启动刷新定时器，隐藏后停止。"""
    dialog = ChannelScopeDialog(
        "B",
        telemetry_provider=lambda: None,
        bound_provider=lambda: False,
    )

    dialog.show()
    assert dialog._timer.isActive()
    dialog.hide()
    assert not dialog._timer.isActive()
    dialog.deleteLater()


def test_app_opens_single_scope_dialog_per_channel():
    """App 按通道维护曲线窗口单例，重复打开复用并置顶。"""
    from main import App

    app = App.__new__(App)
    app.coyote = SimpleNamespace(
        telemetry=OutputTelemetry(),
        status=SimpleNamespace(bound=False),
    )
    app._scope_dialogs = {}
    container = QWidget()
    app.window = container

    app._open_channel_scope("A")
    first = app._scope_dialogs["A"]
    assert isinstance(first, ChannelScopeDialog)
    assert first.isVisible()

    app._open_channel_scope("A")
    assert app._scope_dialogs["A"] is first
    assert "B" not in app._scope_dialogs

    first.close()
    container.deleteLater()


def test_app_syncs_wave_names_to_dashboard_cards():
    """App 每 tick 把控制器遥测中的波形名同步到通道卡。"""
    from main import App

    app = App.__new__(App)
    telemetry = OutputTelemetry()
    telemetry.record_waveform("A", "挥鞭.pulse")
    app.coyote = SimpleNamespace(telemetry=telemetry)
    card_a = ChannelCard("A", "channelA")
    card_b = ChannelCard("B", "channelB")
    app.window = SimpleNamespace(dashboard=SimpleNamespace(
        channel_a=card_a, channel_b=card_b))

    app._update_channel_wave_names()

    assert card_a.wave_label.text() == "波形：挥鞭"
    assert card_b.wave_label.text() == "波形：恒定"
    card_a.deleteLater()
    card_b.deleteLater()
