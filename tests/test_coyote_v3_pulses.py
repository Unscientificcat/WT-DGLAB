"""V3 波形按时补给的回归测试（代码审查修复 B2）。"""

import asyncio
import time

import pytest

from src.coyote_controller import CoyoteController
from src.waveforms import WaveformCatalog


class RecordingClient:
    """按顺序记录 clear / add 调用的 V3 客户端替身。"""

    def __init__(self):
        self.calls = []

    async def set_strength(self, channel, operation_type, value):
        """记录强度设置。"""
        self.calls.append(("strength", channel.name, value))

    async def clear_pulses(self, channel):
        """记录清空 App 队列。"""
        self.calls.append(("clear", channel.name))

    async def add_pulses(self, channel, *pulses):
        """记录追加的波形条数。"""
        self.calls.append(("add", channel.name, len(pulses)))

    def adds(self, channel="A"):
        """返回指定通道每次追加的条数列表。"""
        return [c[2] for c in self.calls if c[0] == "add" and c[1] == channel]

    def clears(self, channel="A"):
        """返回指定通道的清空次数。"""
        return sum(1 for c in self.calls if c[0] == "clear" and c[1] == channel)


def _bound_controller(catalog=None) -> tuple[CoyoteController, RecordingClient]:
    """创建已绑定、使用替身客户端的控制器。"""
    controller = CoyoteController(port=8999, catalog=catalog)
    client = RecordingClient()
    controller._client = client
    controller._status.bound = True
    return controller, client


def _catalog(tmp_path, *names):
    """在临时目录写入最小可解析的 .pulse 波形。"""
    directory = tmp_path / "waveforms"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(
            "Dungeonlab+pulse:0,1,0=10,10,0,1,1/50-0,100-1", encoding="utf-8")
    catalog = WaveformCatalog(tmp_path)
    catalog.reload()
    return catalog


async def _run_feeder(controller, seconds=0.25):
    """运行补给协程一小段时间后停止。"""
    stop = asyncio.Event()
    task = asyncio.create_task(controller._pulse_feeder(stop))
    await asyncio.sleep(seconds)
    stop.set()
    await task


@pytest.mark.asyncio
async def test_strength_change_clears_and_primes_two_seconds():
    """强度变化：先清空队列，再预充 2 秒（20 条）。"""
    controller, client = _bound_controller()
    await controller._exec_command(("strength", "A", 100))
    assert client.clears() == 1
    assert client.adds() == [20]
    # 清空发生在追加之前
    kinds = [c[0] for c in client.calls if c[0] != "strength"]
    assert kinds == ["clear", "add"]


@pytest.mark.asyncio
async def test_repeated_same_strength_does_not_append():
    """主线程保活重复下发相同强度时不再追加波形（不积压）。"""
    controller, client = _bound_controller()
    for _ in range(20):
        await controller._exec_command(("strength", "A", 80))
    assert client.adds() == [20]
    assert client.clears() == 1


@pytest.mark.asyncio
async def test_feeder_tops_up_one_second_when_due():
    """补给节拍到期时追加 1 秒（10 条），并按截止时间累加。"""
    controller, client = _bound_controller()
    await controller._exec_command(("strength", "A", 60))
    due = time.monotonic() - 0.05
    controller._next_feed["A"] = due
    await _run_feeder(controller)
    assert client.adds() == [20, 10]
    assert controller._next_feed["A"] == pytest.approx(
        due + CoyoteController.FEED_INTERVAL_S)


@pytest.mark.asyncio
async def test_feeder_waits_until_due():
    """未到补给时间不追加。"""
    controller, client = _bound_controller()
    await controller._exec_command(("strength", "A", 60))
    await _run_feeder(controller)
    assert client.adds() == [20]


@pytest.mark.asyncio
async def test_feeder_reprimes_after_stall():
    """事件循环卡顿超过一个节拍后重新预充 2 秒。"""
    controller, client = _bound_controller()
    await controller._exec_command(("strength", "A", 60))
    controller._next_feed["A"] = time.monotonic() - 5
    await _run_feeder(controller)
    assert client.adds() == [20, 20]


@pytest.mark.asyncio
async def test_feeder_skips_silent_channel():
    """强度为 0 的通道不补给。"""
    controller, client = _bound_controller()
    controller._next_feed["B"] = time.monotonic() - 0.05
    await _run_feeder(controller)
    assert client.adds("B") == []


@pytest.mark.asyncio
async def test_waveform_switch_while_feeding_replaces_queue(tmp_path):
    """输出中切换波形：清空旧队列并立即预充新波形。"""
    controller, client = _bound_controller(_catalog(tmp_path, "新波形.pulse"))
    await controller._exec_command(("strength", "A", 100))
    client.calls.clear()
    await controller._exec_command(("waveform", "A", "新波形.pulse"))
    assert [c[0] for c in client.calls] == ["clear", "add"]
    assert controller.telemetry.snapshot("A").name == "新波形.pulse"


@pytest.mark.asyncio
async def test_waveform_switch_while_silent_does_not_send(tmp_path):
    """强度为 0 时切换波形只记录，不下发。"""
    controller, client = _bound_controller(_catalog(tmp_path, "新波形.pulse"))
    await controller._exec_command(("waveform", "A", "新波形.pulse"))
    assert client.calls == []


@pytest.mark.asyncio
async def test_strength_zero_clears_and_records_silence():
    """强度归零：清空队列，遥测记录静默，补给停止。"""
    controller, client = _bound_controller()
    await controller._exec_command(("strength", "A", 100))
    await controller._exec_command(("strength", "A", 0))
    assert client.clears() == 2
    assert not controller.telemetry.snapshot("A").active
    controller._next_feed["A"] = time.monotonic() - 0.05
    await _run_feeder(controller)
    assert client.adds() == [20]


def test_reset_pulse_state_zeroes_channels():
    """绑定 / 断线时复位补给状态，重连后第一帧强度必然触发预充。"""
    controller = CoyoteController(port=8999)
    controller._channel_strength = {"A": 50, "B": 70}
    controller._reset_pulse_state()
    assert controller._channel_strength == {"A": 0, "B": 0}
