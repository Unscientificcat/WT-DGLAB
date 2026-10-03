"""事件切换、实际强度与停止屏障的端到端模拟回归。"""

import asyncio
import json
import queue

import pytest

from main import App
from src.command_mailbox import CommandMailbox
from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import CoyoteV4Controller
from test_repair_lifecycle import app, event, tank_state, tick
from v4_peer import V4Peer


class V3Peer:
    """模拟 V3 绝对强度、波形缓存和传输失败。"""

    def __init__(self):
        self.strength = [0, 0]
        self.playing = [False, False]
        self.calls = []
        self.fail_zero = False
        self.fail_clear = False

    async def set_strength(self, channel, operation_type, value):
        """执行绝对设置；可使一次归零失败。"""
        assert operation_type.name == "SET_TO"
        self.calls.append(("strength", channel.name, value))
        if self.fail_zero and value == 0:
            self.fail_zero = False
            raise OSError("模拟归零发送失败")
        self.strength[channel.value - 1] = value

    async def clear_pulses(self, channel):
        """清空指定通道的波形。"""
        self.calls.append(("clear", channel.name))
        if self.fail_clear:
            self.fail_clear = False
            raise OSError("模拟清理失败")
        self.playing[channel.value - 1] = False

    async def add_pulses(self, channel, *pulses):
        """记录实际播放。"""
        self.calls.append(("waveform", channel.name))
        self.playing[channel.value - 1] = True


def bound_controller(protocol):
    """创建仅连接内存模拟 App 的控制器。"""
    if protocol == "v4":
        controller = CoyoteV4Controller()
        peer = V4Peer(controller)
        controller._websocket = peer
        controller._client_id = "app-1"
        controller._slot_id = "slot-1"
    else:
        controller = CoyoteController()
        peer = V3Peer()
        controller._client = peer
    controller._running = True
    controller.status.bound = True
    controller.status.server_running = True
    return controller, peer


async def drain(controller):
    """让生产邮箱中的全部命令走真实控制器处理。"""
    execute = (controller._execute_command if isinstance(controller, CoyoteV4Controller)
               else controller._exec_command)
    while not controller._cmd_queue.empty():
        await execute(controller._cmd_queue.get_nowait())


def test_mailbox_barrier_discards_old_but_keeps_new_intent():
    box = CommandMailbox()
    box.put(("waveform", "A", "旧事件"))
    box.put(("strength", "A", 30))
    box.put(("strength", "B", 12))
    box.put_stop("A")
    box.put(("waveform", "A", "恢复波形"))
    box.put(("strength", "A", 5))
    assert box.get_nowait() == ("stop", "A")
    assert box.get_nowait() == ("waveform", "A", "恢复波形")
    assert {box.get_nowait(), box.get_nowait()} == {
        ("strength", "A", 5), ("strength", "B", 12)}
    with pytest.raises(queue.Empty):
        box.get_nowait()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("channel", ["A", "B"])
async def test_thirty_zero_five_never_becomes_thirty_five(protocol, channel):
    controller, peer = bound_controller(protocol)
    setter = controller.set_strength_a if channel == "A" else controller.set_strength_b
    index = 0 if channel == "A" else 1
    setter(30)
    await drain(controller)
    assert peer.strength[index] == 30
    setter(0)
    await drain(controller)
    assert peer.strength[index] == 0
    assert not peer.playing[index]
    setter(5)
    await drain(controller)
    assert peer.strength[index] == 5
    # 0 与 5 同时排队时仍必须先停止，且恢复命令不能被屏障删掉。
    setter(0)
    setter(5)
    await drain(controller)
    assert peer.strength[index] == 5
    assert peer.playing[index]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_single_channel_stop_preserves_other_channel(protocol):
    controller, peer = bound_controller(protocol)
    controller.set_strength_a(30)
    controller.set_strength_b(40)
    await drain(controller)
    controller.stop_output("A")
    await drain(controller)
    assert peer.strength == [0, 40]
    assert peer.playing == [False, True]
    controller.clear_all()
    await drain(controller)
    assert peer.strength == [0, 0]
    assert peer.playing == [False, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("kind", ["kill", "repair", "hit", "death"])
@pytest.mark.parametrize("normal_strength", [0, 5])
async def test_event_expiry_restores_actual_peer_output(app, protocol, kind, normal_strength):
    controller, peer = bound_controller(protocol)
    app.coyote = controller
    app._send_strength = App._send_strength.__get__(app)
    cfg = app.config_mgr.config
    cfg.tank.enabled = bool(normal_strength)
    cfg.tank.speed_min = 0
    cfg.tank.speed_max = 30
    cfg.tank.channel_a_max = normal_strength
    cfg.tank.channel_b_max = normal_strength
    tick(app, tank_state(repairing=kind == "repair"), [event(kind)])
    await drain(controller)
    assert peer.strength == [81, 42]
    app._event_remaining = 0.05
    tick(app)
    await drain(controller)
    assert peer.strength == [normal_strength, normal_strength]
    assert peer.playing == [bool(normal_strength)] * 2
    assert app._event_kind == ""


@pytest.mark.asyncio
async def test_v4_waits_for_reset_response_before_restoring():
    controller, peer = bound_controller("v4")
    controller.set_strength_a(30)
    await drain(controller)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause_reset(request):
        if request["data"].get("t") == 7:
            entered.set()
            await release.wait()

    peer.before_response = pause_reset
    controller.stop_output("A")
    controller.set_strength_a(5)
    task = asyncio.create_task(drain(controller))
    await asyncio.wait_for(entered.wait(), 1)
    assert peer.strength[0] == 0
    assert not peer.playing[0]
    assert controller._needs_stop["A"]
    release.set()
    await task
    assert peer.strength[0] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["cleared", "replaced", "cancelled", "disconnected", None])
async def test_v4_cancelled_task_is_not_treated_as_success(reason):
    controller, peer = bound_controller("v4")
    peer.reason = reason
    with pytest.raises(RuntimeError, match="未完成"):
        await controller._execute_command(("strength", "A", 30))
    assert controller._last_strength["A"] == 0
    assert controller._needs_stop["A"]
    assert not peer.playing[0]


@pytest.mark.asyncio
async def test_v4_lost_reset_requires_retry_before_resume():
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    controller.set_strength_a(30)
    await drain(controller)
    peer.drop = lambda req: req.get("data", {}).get("t") == 7
    with pytest.raises(RuntimeError, match="停止未确认"):
        await controller._execute_command(("stop", "A"))
    assert controller._app_strength["A"] is None
    assert controller._needs_stop["A"]
    with pytest.raises(RuntimeError, match="停止未确认"):
        await controller._execute_command(("strength", "A", 5))
    assert not peer.playing[0]
    peer.drop = None
    await controller._execute_command(("strength", "A", 5))
    assert peer.strength[0] == 5
    assert not controller._pending_rpc


@pytest.mark.asyncio
async def test_v4_repeated_zero_cleans_residual_waveform_even_at_local_zero():
    controller, peer = bound_controller("v4")
    peer.strength[0] = 30
    peer.playing[0] = True
    for _ in range(2):
        await controller._execute_command(("strength", "A", 0))
        assert peer.strength[0] == 0
        assert not peer.playing[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["fail_zero", "fail_clear"])
async def test_v3_stop_failure_blocks_feeder_and_recovers(failure):
    controller, peer = bound_controller("v3")
    controller.set_strength_a(30)
    await drain(controller)
    setattr(peer, failure, True)
    with pytest.raises(OSError):
        await controller._exec_command(("stop", "A"))
    assert controller._channel_strength["A"] == 0
    assert not controller._is_feeding("A")
    assert controller._needs_stop["A"]
    await controller._exec_command(("strength", "A", 5))
    assert peer.strength[0] == 5
    assert not controller._needs_stop["A"]


@pytest.mark.asyncio
async def test_v4_lost_ack_never_replays_increment():
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    peer.drop_response = lambda req: req.get("data", {}).get("t") == 3
    with pytest.raises(TimeoutError):
        await controller._execute_command(("strength", "A", 30))
    assert peer.strength[0] == 30  # 已执行但响应丢失，本地不能重放同一增量。
    assert controller._needs_stop["A"]
    peer.drop_response = None
    await controller._execute_command(("strength", "A", 5))
    assert peer.strength[0] == 5
    assert not controller._pending_rpc


@pytest.mark.asyncio
async def test_v4_clear_failure_still_attempts_absolute_zero():
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    await controller._execute_command(("strength", "A", 30))
    peer.drop = lambda req: req.get("m") == "device.op.clear"
    with pytest.raises(RuntimeError, match="停止未确认"):
        await controller._execute_command(("stop", "A"))
    assert peer.strength[0] == 0
    assert controller._needs_stop["A"]
    peer.drop = None
    await controller._execute_command(("strength", "A", 5))
    assert peer.strength[0] == 5


@pytest.mark.asyncio
async def test_v4_pending_stop_blocks_waveform_after_inflight_increment():
    controller, peer = bound_controller("v4")

    async def submit_stop(request):
        if request["data"].get("t") == 3:
            controller.stop_output("A")

    peer.before_response = submit_stop
    await controller._execute_command(("strength", "A", 30))
    assert not peer.playing[0]
    peer.before_response = None
    await drain(controller)
    assert peer.strength[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_cancel_event_stops_actual_output(app, protocol):
    controller, peer = bound_controller(protocol)
    app.coyote = controller
    app._send_strength = App._send_strength.__get__(app)
    tick(app, tank_state(), [event("repair")])
    await drain(controller)
    app._cancel_active_event()
    await drain(controller)
    assert peer.strength == [0, 0]
    assert peer.playing == [False, False]


class ListeningV4Peer(V4Peer):
    """通过真实控制器消息循环传递响应，不直接调用响应处理器。"""

    def __init__(self, controller):
        super().__init__(controller)
        self.incoming = asyncio.Queue()
        self.response_sink = self.incoming.put

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self.incoming.get()
        if frame is None:
            raise StopAsyncIteration
        return json.dumps(frame)

    async def close(self):
        """关闭后结束接收流。"""
        await super().close()
        await self.incoming.put(None)


@pytest.mark.asyncio
async def test_v4_binding_and_shutdown_keep_listener_alive(monkeypatch):
    import src.coyote_v4_controller as v4

    controller = CoyoteV4Controller()
    controller._running = True
    controller._loop = asyncio.get_running_loop()
    peer = ListeningV4Peer(controller)
    peer.strength = [30, 40]
    peer.playing = [True, True]

    class Connect:
        async def __aenter__(self):
            return peer

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(v4.websockets, "connect", lambda *a, **kw: Connect())
    await peer.incoming.put({"type": "hello", "clientId": "target-1"})
    await peer.incoming.put({"type": "client_attached", "clientId": "app-1"})
    await peer.incoming.put({"type": "message", "clientId": "app-1", "data": {
        "t": "ev", "ev": "devices.snapshot",
        "devices": [{"type": "COYOTE_030", "slotId": "slot-1"}],
    }})
    main_task = asyncio.create_task(controller._async_main())
    try:
        async with asyncio.timeout(1):
            while not controller.status.bound:
                await asyncio.sleep(0.001)
        assert peer.strength == [0, 0]
        assert peer.playing == [False, False]
        await controller._execute_command(("strength", "A", 30))
        await controller._execute_command(("strength", "B", 40))
        controller.stop(wait=False)
        await asyncio.wait_for(main_task, 1)
        assert peer.closed
        assert peer.strength == [0, 0]
        assert peer.playing == [False, False]
        assert not controller.status.bound
        assert not controller._pending_rpc
    finally:
        controller._running = False
        if not main_task.done():
            main_task.cancel()
        await asyncio.gather(main_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_v4_shutdown_attempts_b_when_a_fails():
    controller, peer = bound_controller("v4")
    controller.RPC_TIMEOUT_S = 0.01
    await controller._execute_command(("strength", "A", 30))
    await controller._execute_command(("strength", "B", 40))
    peer.drop = lambda req: req.get("data", {}).get("c") == 0
    await controller._close_websocket()
    assert peer.strength[1] == 0
    assert not peer.playing[1]
    assert peer.closed
    assert not controller._running


class QueuedV4Peer(V4Peer):
    """模拟先入队、后执行的 App 任务，以及 clear 取消待执行任务。"""

    def __init__(self, controller):
        super().__init__(controller)
        self.tasks = []

    async def send(self, message):
        """归零及增量延迟执行，使历史 clear 竞态可确定地复现。"""
        frame = json.loads(message)
        request = frame.get("data", {})
        channel = request.get("data", {}).get("c")
        if request.get("m") == "device.op":
            async def execute_later():
                await asyncio.sleep(0.005)
                await super(QueuedV4Peer, self).send(message)

            task = asyncio.create_task(execute_later())
            self.tasks.append((channel, task, request))
            return
        if request.get("m") == "device.op.clear":
            for queued_channel, task, queued_request in self.tasks:
                if queued_channel == channel and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await self.response_sink({
                        "type": "message", "clientId": frame["clientId"],
                        "data": {"t": "resp", "reqId": queued_request["reqId"],
                                 "result": {"reason": "cleared"}},
                    })
        await super().send(message)


@pytest.mark.asyncio
async def test_v4_old_reset_then_clear_loses_reset_but_barrier_does_not():
    controller, _ = bound_controller("v4")
    peer = QueuedV4Peer(controller)
    controller._websocket = peer
    peer.strength[0] = 30
    peer.playing[0] = True
    try:
        # 复现旧实现：发送归零后不等完成就清队列，归零任务被取消。
        await controller._send_request("app-1", "device.op", {
            "s": "slot-1", "c": 0, "t": 7, "v": 0, "im": True,
        })
        await controller._clear_channel("A")
        assert peer.strength[0] == 30
        assert not peer.playing[0]
        # 新实现即使本地记录错误地为 0，也会确认绝对归零再恢复。
        await controller._execute_command(("stop", "A"))
        assert peer.strength[0] == 0
        await controller._execute_command(("strength", "A", 5))
        assert peer.strength[0] == 5
    finally:
        await asyncio.gather(*(item[1] for item in peer.tasks), return_exceptions=True)
