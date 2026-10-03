"""连接重构：生产调度器、协议替身和真实异步时间线验证。"""

import asyncio
from dataclasses import FrozenInstanceError
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.connection_service import ConnectionService
from src.dglab_devices import DeviceRegistry
from src.dglab_state import ChannelTarget, OutputIntent, WaveformConfig
from src.waveforms import WaveformPlayer
from test_output_stop_barrier import bound_controller, drain
from test_repair_lifecycle import app, event, tank_state, tick
from main import App


def connected(protocol="v4"):
    """创建具有真实设备注册状态的内存会话。"""
    controller, peer = bound_controller(protocol)
    if protocol == "v4":
        controller._registry.replace([device("slot-1")])
    return controller, peer


def device(slot, **extra):
    """官方设备描述符。"""
    return {"slotId": slot, "type": "COYOTE_030", "name": slot,
            "slotState": {"hasDevice": True}, **extra}


def intent(a=30, b=12, **kwargs):
    """生成双通道输出采样。"""
    return OutputIntent(ChannelTarget(a), ChannelTarget(b), **kwargs)


async def slots(controller, props=None, state=None):
    """将 App 增量送入真实接收分派器。"""
    await controller._handle_app_data("app-1", {
        "t": "ev", "ev": "slots.patch", "slots": [{
            "slotId": "slot-1", "props": props or {}, "slotState": state or {},
        }],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_atomic_intent_coalesces_and_renews_without_io(protocol):
    controller, peer = connected(protocol)
    for number in range(1000):
        controller.submit_output(intent(number % 100, 9))
    assert len(controller._cmd_queue) == 1
    await drain(controller)
    assert peer.strength == [99, 9]
    old_lease = controller._lease_until
    controller.submit_output(intent(99, 9))
    assert controller._cmd_queue.empty()
    assert controller._lease_until >= old_lease


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_stop_invalidates_taken_intent_but_preserves_other_channel(protocol):
    controller, peer = connected(protocol)
    controller.submit_output(intent())
    command = controller._cmd_queue.get_nowait()
    controller.stop_output("A")
    execute = getattr(controller, "_execute_command", None) or controller._exec_command
    await execute(command)
    await drain(controller)
    assert peer.strength == [0, 12]
    controller.submit_output(intent(5, 12))
    await drain(controller)
    assert peer.strength == [5, 12]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_old_session_cannot_replay_taken_output(protocol):
    controller, peer = connected(protocol)
    controller.submit_output(intent())
    command = controller._cmd_queue.get_nowait()
    controller._new_session()
    execute = getattr(controller, "_execute_command", None) or controller._exec_command
    await execute(command)
    assert peer.strength == [0, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_event_deadline_stops_without_gui_and_within_100ms(protocol):
    controller, peer = connected(protocol)
    deadline = time.monotonic() + 0.12
    controller.submit_output(intent(expires_at=deadline, source="event:1:kill"))
    await drain(controller)
    first_stop = []
    original = controller._stop_channel

    async def record_stop(channel):
        first_stop.append(time.monotonic())
        await original(channel)

    controller._stop_channel = record_stop
    stop = asyncio.Event()
    processor = (controller._command_loop() if protocol == "v4"
                 else controller._cmd_processor(stop))
    tasks = [asyncio.create_task(processor), asyncio.create_task(controller._runtime_watchdog())]
    try:
        await asyncio.sleep(0.30)
        assert peer.strength == [0, 0]
        assert peer.playing == [False, False]
        assert deadline <= first_stop[0] <= deadline + 0.1
    finally:
        controller._running = False
        stop.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_expired_lease_requires_new_valid_intent(protocol):
    controller, peer = connected(protocol)
    controller.submit_output(intent())
    await drain(controller)
    controller._lease_until = time.monotonic() - 1
    task = asyncio.create_task(controller._runtime_watchdog())
    await asyncio.sleep(0.035)
    controller._running = False
    await task
    await drain(controller)
    assert peer.strength == [0, 0]
    controller._running = True
    controller.submit_output(intent(expires_at=time.monotonic() - 1))
    await drain(controller)
    assert peer.strength == [0, 0]
    controller.submit_output(intent(5, 0))
    await drain(controller)
    assert peer.strength == [5, 0]


@pytest.mark.asyncio
async def test_persistent_report_mismatch_resets_before_restoring():
    controller, peer = connected()
    controller.submit_output(intent(30, 0))
    await drain(controller)
    peer.strength[0] = 70
    controller._calib_block_until["A"] = 0
    await slots(controller, {"intensityA": 70})
    assert controller._cmd_queue.empty()
    await slots(controller, {"intensityA": 70})
    peer.messages.clear()
    await drain(controller)
    operations = [m["data"] for m in peer.messages]
    assert operations[0]["m"] == "device.op.clear"
    assert operations[1]["data"]["t"] == 7
    assert operations[2]["data"] == {"s": "slot-1", "c": 0, "t": 3, "v": 30, "im": True}
    assert peer.strength[0] == 30
    assert controller._app_strength["A"] == 70


@pytest.mark.asyncio
async def test_repeated_unrecoverable_mismatch_stops_channel():
    controller, peer = connected()
    controller.submit_output(intent(30, 12))
    await drain(controller)
    for _ in range(3):
        peer.strength[0] = 80
        controller._calib_block_until["A"] = 0
        await slots(controller, {"intensityA": 80})
        await slots(controller, {"intensityA": 80})
        await drain(controller)
    assert controller._faulted["A"]
    assert peer.strength == [0, 12]
    controller.submit_output(intent(40, 12))
    await drain(controller)
    assert peer.strength == [0, 12]


@pytest.mark.asyncio
async def test_lost_increment_response_rebases_without_double_add():
    controller, peer = connected()
    controller.RPC_TIMEOUT_S = 0.02
    lost = [False]

    def drop_once(request):
        if request.get("data", {}).get("t") == 3 and not lost[0]:
            lost[0] = True
            return True
        return False

    peer.drop_response = drop_once
    controller.submit_output(intent(30, 0))
    await drain(controller)
    assert peer.strength == [30, 0]
    assert not controller._needs_stop["A"]
    kinds = [m["data"].get("data", {}).get("t") for m in peer.messages]
    assert kinds.index(7) < len(kinds) - 1


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [True, False])
async def test_app_limit_mute_and_restore(nested):
    controller, peer = connected()
    controller.submit_output(intent(60, 12))
    await drain(controller)
    props = {"channelA": {"intensityMax": 20}} if nested else {"channelA.intensityMax": 20}
    await slots(controller, props)
    await drain(controller)
    assert peer.strength == [20, 12]
    props = {"channelA": {"isMuted": True}} if nested else {"channelA.isMuted": True}
    await slots(controller, props)
    await drain(controller)
    assert peer.strength == [0, 12]
    assert not peer.playing[0]
    props = {"channelA": {"isMuted": False}} if nested else {"channelA.isMuted": False}
    await slots(controller, props)
    await drain(controller)
    assert peer.strength == [20, 12]


@pytest.mark.asyncio
async def test_multiple_devices_require_selection_and_offline_does_not_switch():
    controller, peer = connected()
    controller._slot_id = ""
    controller._status.bound = False
    controller._registry.replace([device("slot-1"), device("slot-2")])
    await controller._refresh_devices()
    assert controller._runtime_state == "waiting_selection"
    assert not controller._slot_id
    controller.select_device("slot-1")
    await drain(controller)
    await controller._binding_task
    assert controller.status.bound
    await slots(controller, state={"hasDevice": False})
    assert not controller.status.bound
    assert not controller._slot_id
    await controller._refresh_devices()
    assert not controller._slot_id
    await slots(controller, state={"hasDevice": True})
    await controller._binding_task
    assert controller._slot_id == "slot-1"


@pytest.mark.asyncio
async def test_stale_response_cannot_complete_new_session_request():
    controller, peer = connected()
    peer.drop_response = lambda request: True
    task = asyncio.create_task(controller._send_request("app-1", "device.op.clear", {}, True))
    await asyncio.sleep(0)
    old = peer.messages[-1]["data"]["reqId"]
    controller._detach_device("断开", keep_client=True)
    with pytest.raises(ConnectionError):
        await task
    task = asyncio.create_task(controller._send_request("app-1", "device.op.clear", {}, True))
    await asyncio.sleep(0)
    new = peer.messages[-1]["data"]["reqId"]
    controller._rpc.resolve("app-1", {"reqId": old, "result": {}})
    assert not task.done()
    controller._rpc.resolve("app-1", {"reqId": new, "result": {}})
    assert await task == {}


@pytest.mark.asyncio
async def test_waveform_error_is_not_silently_ignored():
    controller, peer = connected()
    peer.error = "invalid_wave"
    await controller._send_waveform("A", 30)
    errors = controller._rpc.collect_errors()
    assert errors and errors[0][1] == "invalid_wave"


def test_waveform_clock_preserves_continuous_frames_and_wraps():
    player = WaveformPlayer()
    frames = tuple(((i,) * 4, (100,) * 4) for i in range(20))
    player.set_waveform("测试", pulses=frames)
    assert [player.pulse_at(10 + i * 0.1) for i in range(10)] == list(frames[:10])
    assert player.pulse_at(10.5) == frames[5]
    assert player.pulse_at(12.1) == frames[1]
    player.set_waveform("新波形", pulses=frames)
    assert player.pulse_at(99) == frames[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_sent_waveform_contains_distinct_sequential_frames(protocol):
    controller, peer = connected(protocol)
    frames = tuple(((i + 10,) * 4, (100,) * 4) for i in range(20))
    controller._player_a.set_waveform("测试", pulses=frames)
    if protocol == "v4":
        await controller._execute_command(("strength", "A", 100))
        wave = next(m["data"]["data"]["v"] for m in peer.messages
                    if m["data"].get("data", {}).get("t") == 0)
        assert [int(frame[:2], 16) for frame in wave] == list(range(10, 20))
    else:
        received = []

        async def capture(channel, *pulses):
            received.extend(pulses)

        peer.add_pulses = capture
        await controller._exec_command(("strength", "A", 100))
        assert [pulse[0][0] for pulse in received] == list(range(10, 30))


@pytest.mark.asyncio
async def test_waveform_feeder_runs_without_repeated_strength_commands():
    controller, peer = connected()
    controller.submit_output(intent())
    await drain(controller)
    peer.messages.clear()
    controller._next_wave = {"A": 0, "B": 0}
    task = asyncio.create_task(controller._waveform_loop())
    await asyncio.sleep(0.08)
    controller._running = False
    await task
    waves = [m["data"]["data"] for m in peer.messages if m["data"].get("data", {}).get("t") == 0]
    assert {wave["c"] for wave in waves} == {0, 1}


def test_snapshots_are_immutable_and_reports_are_not_predicted():
    controller, _ = connected()
    controller._last_strength["A"] = 30
    controller._publish_snapshot()
    snap = controller.snapshot()
    assert snap.a.sent == 30
    assert snap.a.reported is None
    with pytest.raises(FrozenInstanceError):
        snap.a.sent = 99
    controller._last_strength["A"] = 99
    assert snap.a.sent == 30


def test_registry_retains_partial_properties_and_marks_offline():
    registry = DeviceRegistry()
    registry.replace([device("one", props={"channelA": {"intensityMax": 15, "isMuted": True}})])
    registry.patch_slots([{"slotId": "one", "props": {"channelA": {"isMuted": False}}}])
    assert registry.channel("one", "A") == (15, False)
    registry.patch_slots([{"slotId": "one", "props": {"connectState": "disconnected"}}])
    assert not registry.snapshots()[0].available


class ManagedAdapter:
    """仅模拟连接生命周期，不建立真实网络连接。"""

    def __init__(self, name, events):
        self.name, self.events = name, events
        self._running = False
        self._thread = None
        self.status = SimpleNamespace(error="")

    def start(self):
        self.events.append((self.name, "start", threading.get_ident()))
        self._running = True

    def stop(self, wait=True):
        self.events.append((self.name, "stop", threading.get_ident()))
        self._running = False

    def _publish_snapshot(self):
        pass


def test_service_replaces_in_background_and_stops_before_start():
    events = []
    a, b = ManagedAdapter("a", events), ManagedAdapter("b", events)
    service = ConnectionService(a)
    service.start()
    deadline = time.monotonic() + 1
    while not a._running and time.monotonic() < deadline:
        time.sleep(0.005)
    service.replace(b)
    while not b._running and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.stop()
    names = [(name, event) for name, event, _ in events]
    assert names.index(("a", "stop")) < names.index(("b", "start"))
    assert all(thread != threading.get_ident() for _, event, thread in events if event == "start")
    assert not a._running and not b._running


def test_service_retries_and_stop_cancels_retry():
    events = []
    adapter = ManagedAdapter("a", events)
    service = ConnectionService(adapter)
    service.RETRY_SECONDS = 0.02
    service.start()
    deadline = time.monotonic() + 1
    while not adapter._running and time.monotonic() < deadline:
        time.sleep(0.005)
    adapter._running = False
    while sum(event == "start" for _, event, _ in events) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.stop()
    count = len(events)
    service.start()
    time.sleep(0.03)
    assert len(events) == count
    assert sum(event == "start" for _, event, _ in events) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("kind", ["kill", "repair", "hit", "death"])
@pytest.mark.parametrize("normal", [0, 5])
async def test_real_game_event_to_atomic_output_restores_normal(app, protocol, kind, normal):
    """真实主程序事件逻辑通过新意图接口走生产协议路径。"""
    controller, peer = connected(protocol)
    app.coyote = controller
    app._desired_waveforms = {"A": WaveformConfig(), "B": WaveformConfig()}
    app._send_strength = App._send_strength.__get__(app)
    app._output_revision = 0
    cfg = app.config_mgr.config
    cfg.tank.enabled = bool(normal)
    cfg.tank.speed_min = 0
    cfg.tank.speed_max = 30
    cfg.tank.channel_a_max = normal
    cfg.tank.channel_b_max = normal
    trigger = event(kind)
    trigger.update(ch_a=30, ch_b=12, duration=5)
    tick(app, tank_state(repairing=False), [trigger])
    await drain(controller)
    # 维修事件需要实际维修状态保持有效。
    if kind == "repair":
        tick(app, tank_state(repairing=True), [trigger])
        await drain(controller)
    assert peer.strength == [30, 12]
    app._event_remaining = 0.01
    tick(app, tank_state(repairing=False))
    await drain(controller)
    assert peer.strength == [normal, normal]
    if normal == 0:
        assert peer.playing == [False, False]


@pytest.mark.asyncio
async def test_fresh_lease_deadline_does_not_restart_waveform():
    controller, peer = connected()
    controller.submit_output(intent(expires_at=time.monotonic() + 1))
    await drain(controller)
    peer.messages.clear()
    for _ in range(5):
        controller.submit_output(intent(expires_at=time.monotonic() + 1))
    await drain(controller)
    assert not peer.messages


@pytest.mark.asyncio
async def test_v3_strength_report_updates_limit_and_display():
    from pydglab_ws import StrengthData
    controller, peer = connected("v3")
    controller.submit_output(intent(60, 12))
    await drain(controller)

    async def reports():
        yield StrengthData(a=20, b=12, a_limit=20, b_limit=200)

    peer.data_generator = reports
    await controller._event_listener(asyncio.Event())
    await drain(controller)
    controller._publish_snapshot()
    assert peer.strength == [20, 12]
    assert controller.snapshot().a.reported == 20
    assert controller.snapshot().a.limit == 20


@pytest.mark.asyncio
async def test_only_alternative_device_requires_visible_manual_selection():
    controller, _ = connected()
    controller._registry.replace([device("slot-2")])
    await controller._refresh_devices()
    await controller._refresh_devices()
    assert not controller._slot_id
    assert controller._runtime_state == "waiting_selection"


def test_gui_distinguishes_report_unknown_limit_and_selection():
    from PySide6.QtWidgets import QApplication, QWidget
    from src.gui.main_window import QRWidget
    from src.dglab_state import ChannelSnapshot, ConnectionSnapshot, DeviceSnapshot
    qt = QApplication.instance() or QApplication([])
    parent = QWidget()
    panel = QRWidget(parent)
    panel.set_protocol("v4")
    panel.set_connection_snapshot(ConnectionSnapshot(
        state="waiting_selection", devices=(DeviceSnapshot("other", "另一台", True),),
        a=ChannelSnapshot(target=30, limit=20, muted=True),
    ))
    assert not panel.device_selector.isHidden()
    assert "App 未知" in panel.output_status.text()
    assert "App 上限 20" in panel.output_status.text()
    assert "App 静音" in panel.output_status.text()
    selected = []
    panel.on_device_selected = selected.append
    panel._choose_device(1)
    assert selected == ["other"]
    parent.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_queued_recovery_uses_latest_target_instead_of_old_strength(protocol):
    controller, peer = connected(protocol)
    controller.submit_output(intent(60, 0))
    await drain(controller)
    controller._queue_latest_target("A")
    controller.submit_output(intent(5, 0))
    await drain(controller)
    assert peer.strength[0] == 5
    controller._queue_latest_target("A")
    command = controller._cmd_queue.get_nowait()
    controller.stop_output("A")
    execute = getattr(controller, "_execute_command", None) or controller._exec_command
    await execute(command)
    await drain(controller)
    assert peer.strength[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["v3", "v4"])
async def test_old_telemetry_in_gui_queue_does_not_renew_output(app, protocol):
    controller, peer = connected(protocol)
    app.coyote = controller
    app._desired_waveforms = {"A": WaveformConfig(), "B": WaveformConfig()}
    app._send_strength = App._send_strength.__get__(app)
    app._output_revision = 0
    cfg = app.config_mgr.config.tank
    cfg.enabled = True
    cfg.channel_a_max = cfg.channel_b_max = 30
    state = tank_state(repairing=False)
    state.sampled_at = time.monotonic() - 5
    tick(app, state)
    await drain(controller)
    assert peer.strength == [0, 0]
