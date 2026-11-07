"""V4 事件延迟：真实邮箱、协调执行器与独立网络响应时间线。"""

import asyncio
import logging
import time

import pytest

from src.command_mailbox import CommandMailbox
from src.dglab_state import ChannelTarget, OutputIntent
from test_output_stop_barrier import bound_controller, drain


def event_intent(a=30, b=12, source="event:1:kill", **kwargs):
    """创建带原始识别时刻的事件目标。"""
    return OutputIntent(ChannelTarget(a), ChannelTarget(b), source=source,
                        identified_at=time.monotonic(), **kwargs)


def requests(peer, method=None, kind=None, channel=None, stage="send"):
    """从模拟端取出指定协议操作的时间线。"""
    return [(at, req) for phase, at, req in peer.timeline
            if phase == stage
            and (method is None or req.get("m") == method)
            and (kind is None or req.get("data", {}).get("t") == kind)
            and (channel is None or req.get("data", {}).get("c") == channel)]


def test_mailbox_atomic_batch_keeps_latest_output_and_v3_order():
    """批次原子取出，后续目标保留；V3 默认仍逐通道取出。"""
    box = CommandMailbox(batch_stops=True)
    box.put(("strength", "A", 99))
    box.put_stops(("A", "B"))
    box.put(("output", None, "最新目标"))
    assert box.has_stop("A") and box.has_stop("B")
    assert box.get_nowait() == ("stop_batch", None, ("A", "B"))
    assert box.get_nowait() == ("output", None, "最新目标")
    assert box.empty()
    v3 = CommandMailbox()
    v3.put_stops(("A", "B"))
    assert v3.get_nowait() == ("stop", "A")
    assert v3.get_nowait() == ("stop", "B")


@pytest.mark.asyncio
@pytest.mark.parametrize("b", [0, 12])
async def test_200ms_roundtrip_parallel_stops_and_coordinated_start(b):
    """200ms 往返下，两轮停止加一轮强度，而非四轮停止逐个等待。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.2
    controller.stop_output()
    controller.submit_output(event_intent(b=b))
    await drain(controller)
    await peer.wait_idle()
    clears = requests(peer, "device.op.clear")
    clear_responses = requests(peer, "device.op.clear", stage="response")
    resets = requests(peer, kind=7, stage="response")
    increments = requests(peer, kind=3)
    increment_responses = requests(peer, kind=3, stage="response")
    waves = requests(peer, kind=0)
    assert len(clears) == 2  # B=0 不再重复清理
    assert max(at for at, _ in clears) < min(at for at, _ in clear_responses)
    assert min(at for at, _ in increments) >= max(at for at, _ in resets)
    assert max(at for at, _ in increments) < min(at for at, _ in increment_responses)
    assert min(at for at, _ in waves) >= max(at for at, _ in increment_responses)
    elapsed = waves[0][0] - clears[0][0]
    print(f"\nV4 RTT=200ms A=30 B={b} 首批波形发送={elapsed:.3f}s")
    assert elapsed < 0.95
    assert peer.strength == [30, b]
    assert peer.playing == [True, bool(b)]


@pytest.mark.asyncio
async def test_asymmetric_response_waits_for_both_channels():
    """较快通道不能越过较慢通道的停止或强度完成确认。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = lambda req: 0.01 if req["data"]["c"] == 0 else 0.09
    controller.stop_output()
    controller.submit_output(event_intent())
    await drain(controller)
    await peer.wait_idle()
    assert min(at for at, _ in requests(peer, kind=3)) >= max(
        at for at, _ in requests(peer, kind=7, stage="response"))
    assert min(at for at, _ in requests(peer, kind=0)) >= max(
        at for at, _ in requests(peer, kind=3, stage="response"))


@pytest.mark.asyncio
async def test_stop_proof_reuse_is_limited_to_same_epoch():
    """同代次零目标复用；下一次事件必须重新确认停止。"""
    controller, peer = bound_controller("v4")
    for index in range(2):
        controller.stop_output()
        controller.submit_output(event_intent(b=0, source=f"event:{index}:kill"))
        await drain(controller)
        assert len(requests(peer, "device.op.clear", channel=1)) == index + 1
        assert controller._stop_confirmed["B"] == controller._stop_key("B")
        assert controller._stop_confirmed["A"] is None


@pytest.mark.asyncio
async def test_inconsistent_report_invalidates_zero_proof():
    """即使冷却中的上报也不能保留与零强度不符的停止证明。"""
    controller, peer = bound_controller("v4")
    controller.stop_output()
    await drain(controller)
    controller._merge_reported_strength({"intensityB": 17})
    assert controller._stop_confirmed["B"] is None
    controller.submit_output(event_intent(b=0))
    await drain(controller)
    assert len(requests(peer, "device.op.clear", channel=1)) == 2


@pytest.mark.asyncio
async def test_batch_failure_blocks_both_and_recovery_is_bounded():
    """B 停止丢响应时 A 不能提前恢复，三次失败后停止重试。"""
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    peer.drop_response = lambda req: req["data"].get("t") == 7 and req["data"]["c"] == 1
    controller.stop_output()
    controller.submit_output(event_intent())
    worker = asyncio.create_task(controller._command_loop())
    try:
        async with asyncio.timeout(2):
            while not controller._faulted["B"]:
                await asyncio.sleep(0.01)
        await asyncio.sleep(0.15)
        assert controller._batch_blocked
        assert not requests(peer, kind=3)
        assert not requests(peer, kind=0)
        assert len(requests(peer, kind=7, channel=1)) == 3
    finally:
        controller._running = False
        await worker


@pytest.mark.asyncio
async def test_lost_increment_ack_stops_both_before_retry_without_double_add():
    """增量已经执行但确认丢失，双方归零后重建，不直接再加一次。"""
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.015
    dropped = []

    def drop_once(req):
        if req["data"].get("t") == 3 and req["data"]["c"] == 1 and not dropped:
            dropped.append(req)
            return True
        return False

    peer.drop_response = drop_once
    controller.stop_output()
    controller.submit_output(event_intent())
    await drain(controller)
    assert peer.strength == [30, 12]
    assert peer.playing == [True, True]
    assert len(requests(peer, kind=7)) == 4
    assert min(at for at, _ in requests(peer, kind=0)) > max(
        at for at, _ in requests(peer, kind=7, stage="response"))


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["stop", "strength"])
async def test_expiry_during_wait_never_starts_waveform(phase):
    """等待停止或强度确认期间到期，原期限不延长且不补发事件。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.04
    controller.stop_output()
    deadline = time.monotonic() + (0.02 if phase == "stop" else 0.10)
    controller.submit_output(event_intent(expires_at=deadline))
    await drain(controller)
    await peer.wait_idle()
    assert not requests(peer, kind=0)
    assert peer.strength == [0, 0]
    assert controller._intent.expires_at == deadline


@pytest.mark.asyncio
async def test_new_stop_during_increment_prevents_old_waveform():
    """增量在途时新停止立即撤销旧资格，随后归零。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.01
    stopped = []

    async def stop_once(req):
        if req["data"].get("t") == 3 and not stopped:
            stopped.append(True)
            controller.stop_output()

    peer.before_response = stop_once
    controller.submit_output(event_intent())
    await drain(controller)
    await peer.wait_idle()
    assert not requests(peer, kind=0)
    assert peer.strength == [0, 0]


@pytest.mark.asyncio
async def test_latest_target_replaces_inflight_target_without_old_waveform():
    """同来源新目标在确认期间到达时，从已确认基准更新，波形只发最新值。"""
    controller, peer = bound_controller("v4")
    changed = []

    async def replace_once(req):
        if req["data"].get("t") == 3 and not changed:
            changed.append(True)
            controller.submit_output(event_intent(5, 7))

    peer.before_response = replace_once
    controller.submit_output(event_intent())
    await drain(controller)
    assert peer.strength == [5, 7]
    assert len(requests(peer, kind=0)) == 2


@pytest.mark.asyncio
async def test_disconnect_during_clear_never_resets_replacement_device():
    """旧清理完成后连接代次已变，不得继续向新设备发送归零或输出。"""
    controller, peer = bound_controller("v4")
    changed = []

    async def disconnect_once(req):
        if req["m"] == "device.op.clear" and not changed:
            changed.append(True)
            controller._detach_device("模拟设备断开", keep_client=True)
            controller._slot_id = "replacement"

    peer.before_response = disconnect_once
    controller.stop_output()
    with pytest.raises((RuntimeError, ConnectionError)):
        await drain(controller)
    assert not requests(peer, kind=7)
    assert not requests(peer, kind=3)
    assert not controller._batch_blocked
    assert controller._stop_confirmed == {"A": None, "B": None}


@pytest.mark.asyncio
async def test_trace_stages_once_and_reports_are_not_execution_ack(caplog):
    """记录各事件阶段；目标匹配上报显式标注非执行回执且不重复。"""
    controller, peer = bound_controller("v4")
    caplog.set_level(logging.INFO)
    output = event_intent()
    controller.stop_output()
    controller.submit_output(output)
    controller.submit_output(output)
    await drain(controller)
    for _ in range(2):
        controller._merge_reported_strength({"intensityA": 30, "intensityB": 12})
    records = [r.message for r in caplog.records if "V4 事件计时" in r.message]
    for stage in ("提交", "取出执行", "双通道停止完成", "强度确认", "首批波形发送"):
        assert sum(f"stage={stage} " in record for record in records) == 1
    assert sum("A目标匹配上报（非执行回执）" in record for record in records) == 1
    assert "识别后=未知" not in " ".join(records)


@pytest.mark.asyncio
async def test_waveform_feeder_cannot_cross_coordinated_strength_wait():
    """补给协程已等待输出锁时，也不能提前发送较快通道的波形。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = lambda req: 0.01 if req["data"]["c"] == 0 else 0.08
    controller.submit_output(event_intent())
    feeder = asyncio.create_task(controller._waveform_loop())
    try:
        await drain(controller)
        await peer.wait_idle()
        waves = requests(peer, kind=0)
        assert waves
        assert waves[0][0] >= max(at for at, _ in requests(peer, kind=3, stage="response"))
    finally:
        controller._running = False
        await feeder
        await peer.wait_idle()


@pytest.mark.asyncio
async def test_new_event_during_stop_uses_new_epoch_and_latest_source():
    """旧停止在途时连续击杀，旧事件不输出，新事件重新确认后输出。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.01
    replaced = []

    async def replace_once(req):
        if req["data"].get("t") == 7 and not replaced:
            replaced.append(True)
            controller.stop_output()
            controller.submit_output(event_intent(5, 7, source="event:2:kill"))

    peer.before_response = replace_once
    controller.stop_output()
    controller.submit_output(event_intent())
    await drain(controller)
    await peer.wait_idle()
    assert peer.strength == [5, 7]
    assert len(requests(peer, kind=3)) == 2
    assert not controller._batch_blocked


@pytest.mark.asyncio
async def test_single_channel_stop_superseding_batch_does_not_stick_barrier():
    """双通道停止期间仅 A 增加新代次，完成新停止后屏障可以释放。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.01
    changed = []

    async def stop_a(req):
        if req["data"].get("t") == 7 and not changed:
            changed.append(True)
            controller.stop_output("A")

    peer.before_response = stop_a
    controller.stop_output()
    await drain(controller)
    assert not controller._batch_blocked
    controller.submit_output(event_intent())
    await drain(controller)
    await peer.wait_idle()
    assert peer.strength == [30, 12]


@pytest.mark.asyncio
async def test_repeated_strength_failures_fault_without_unbounded_retries():
    """恢复归零成功不能清除整组输出连续失败计数。"""
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    peer.drop_response = lambda req: req["data"].get("t") == 3 and req["data"]["c"] == 1
    controller.submit_output(event_intent())
    await asyncio.wait_for(drain(controller), 1)
    assert controller._faulted == {"A": True, "B": True}
    assert len(requests(peer, kind=3, channel=1)) == 3
    assert peer.strength == [0, 0]
    assert not requests(peer, kind=0)


@pytest.mark.asyncio
async def test_cancelled_batch_keeps_channels_blocked_until_explicit_stop():
    """取消未完成的批次不能留下可复用的停止证明。"""
    controller, peer = bound_controller("v4")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold(req):
        if req["m"] == "device.op.clear":
            entered.set()
            await release.wait()

    peer.before_response = hold
    controller.stop_output()
    task = asyncio.create_task(drain(controller))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert controller._batch_blocked
    assert controller._stop_confirmed == {"A": None, "B": None}
    peer.before_response = None
    controller.stop_output()
    await drain(controller)
    assert not controller._batch_blocked


@pytest.mark.asyncio
async def test_superseded_strength_cannot_be_sent_by_waiting_feeder():
    """同来源目标被替换后，补给必须等待最新目标应用，不能重发旧强度。"""
    controller, peer = bound_controller("v4")
    changed = []

    async def replace_once(req):
        if req["data"].get("t") == 3 and not changed:
            changed.append(True)
            controller.submit_output(event_intent(5, 7))

    peer.before_response = replace_once
    controller.submit_output(event_intent())
    await controller._execute_command(controller._cmd_queue.get_nowait())
    # 模拟最新意图取出前，补给协程先获得锁。
    async with controller._output_lock:
        await controller._send_waveform("A", controller._last_strength["A"])
    assert not requests(peer, kind=0)
    await drain(controller)
    assert peer.strength == [5, 7]
    assert peer.playing == [True, True]


@pytest.mark.asyncio
async def test_report_without_current_trace_is_not_event_latency(caplog):
    """非事件上报或旧事件结束后的报告不关联到事件响应。"""
    controller, peer = bound_controller("v4")
    caplog.set_level(logging.INFO)
    controller._merge_reported_strength({"intensityA": 30})
    controller.submit_output(event_intent())
    await drain(controller)
    controller.stop_output()
    controller._merge_reported_strength({"intensityA": 30})
    assert not any("目标匹配上报" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_new_session_discards_proofs_and_old_trace():
    """停止确认及事件计时不能跨连接会话复用。"""
    controller, peer = bound_controller("v4")
    controller.stop_output()
    controller.submit_output(event_intent(0, 0))
    await drain(controller)
    assert all(controller._stop_confirmed.values())
    controller._new_session()
    assert controller._stop_confirmed == {"A": None, "B": None}
    assert controller._latency_trace is None
    controller.submit_output(event_intent(0, 0))
    await drain(controller)
    assert len(requests(peer, "device.op.clear")) == 4


@pytest.mark.asyncio
async def test_continuous_normal_updates_do_not_starve_waveforms():
    """常规遥测变化快于网络确认时仍持续输出，每轮使用最新目标。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.04
    worker = asyncio.create_task(controller._command_loop())
    try:
        for index in range(20):
            controller.submit_output(event_intent(10 + index, 10, source="normal"))
            await asyncio.sleep(0.01)
            if index == 10:
                assert requests(peer, kind=0), "不能等常规目标停止变化才开始播放"
        await asyncio.sleep(0.15)
        assert peer.strength == [29, 10]
        assert peer.playing == [True, True]
    finally:
        controller._running = False
        await worker
        await peer.wait_idle()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["A", "B"])
async def test_single_stop_during_increment_preserves_other_channel(channel):
    """一个通道在增量等待期间被撤销，另一个仍沿用原资格完成输出。"""
    controller, peer = bound_controller("v4")
    peer.response_delay = 0.01
    stopped = []

    async def stop_a(req):
        if req["data"].get("t") == 3 and not stopped:
            stopped.append(True)
            controller.stop_output(channel)

    peer.before_response = stop_a
    controller.submit_output(event_intent())
    await drain(controller)
    await peer.wait_idle()
    assert peer.strength == ([0, 12] if channel == "A" else [30, 0])
    assert peer.playing == ([False, True] if channel == "A" else [True, False])


@pytest.mark.asyncio
async def test_failure_recovery_does_not_overwrite_new_event_with_old_epoch():
    """旧增量失败与新事件同时到达，恢复命令必须携带新代次。"""
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    replaced = []

    def replace_and_drop(req):
        if req["data"].get("t") == 3 and req["data"]["c"] == 1 and not replaced:
            replaced.append(True)
            controller.stop_output()
            controller.submit_output(event_intent(5, 7, source="event:2:kill"))
            return True
        return False

    peer.drop_response = replace_and_drop
    controller.submit_output(event_intent())
    await drain(controller)
    assert peer.strength == [5, 7]
    assert peer.playing == [True, True]
