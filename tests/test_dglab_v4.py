"""DG-LAB V3/V4 双协议配置、界面和 V4 帧回归测试。"""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.config_manager import ConfigManager
from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import (
    DEFAULT_RELAY_URL,
    PAIRING_URL_PREFIX,
    CoyoteV4Controller,
)
from src.gui.main_window import MainWindow
from main import App


from v4_peer import V4Peer as FakeWebSocket


def operation_from(frame):
    """从 V4 Relay 外层帧取出 device.op 数据。"""
    request = frame["data"]
    assert frame["type"] == "message"
    assert request["t"] == "req"
    assert request["m"] == "device.op"
    return request["data"]


def test_old_config_defaults_to_v3_and_new_fields_round_trip(tmp_path):
    """旧配置默认 V3，新协议字段可以保存并重新加载。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"app": {"ws_port": 9000}}, ensure_ascii=False),
        encoding="utf-8",
    )
    manager = ConfigManager(str(config_path))

    manager.load()

    assert manager.config.app.dglab_protocol == "v3"
    assert manager.config.app.v4_relay_url == DEFAULT_RELAY_URL

    manager.config.app.dglab_protocol = "v4"
    manager.config.app.v4_relay_url = "ws://192.168.1.10:9998/v4"
    manager.save()
    reloaded = ConfigManager(str(config_path)).load()

    assert reloaded.app.dglab_protocol == "v4"
    assert reloaded.app.v4_relay_url == "ws://192.168.1.10:9998/v4"


def test_invalid_saved_relay_url_falls_back_to_official_default(tmp_path):
    """手工损坏的 Relay 配置不会阻止程序启动。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "app": {
            "dglab_protocol": "v4",
            "v4_relay_url": "https://不是-websocket.example",
        },
    }), encoding="utf-8")

    config = ConfigManager(str(config_path)).load()

    assert config.app.dglab_protocol == "v4"
    assert config.app.v4_relay_url == DEFAULT_RELAY_URL


def test_connection_panel_switches_v3_and_v4_fields(tmp_path):
    """协议按钮切换表单后立即保存并通知业务控制器。"""
    config_path = tmp_path / "config.json"
    manager = ConfigManager(str(config_path))
    manager.config.app.dglab_protocol = "v4"
    callback = Mock()
    window = MainWindow(manager, on_mode_changed=callback)
    panel = window.qr_widget
    callback.reset_mock()

    assert panel.get_protocol() == "v4"
    assert panel.v4_relay_url.isVisibleTo(panel)
    assert not panel.ws_port.isVisibleTo(panel)

    panel.v3_button.click()

    assert panel.get_protocol() == "v3"
    assert panel.ws_port.isVisibleTo(panel)
    assert not panel.v4_relay_url.isVisibleTo(panel)
    assert manager.config.app.dglab_protocol == "v3"
    assert ConfigManager(str(config_path)).load().app.dglab_protocol == "v3"
    callback.assert_called_once_with()
    window.close()


def test_invalid_relay_prevents_immediate_v4_switch(tmp_path):
    """Relay 地址无效时恢复 V3 选择且不触发控制器切换。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    callback = Mock()
    window = MainWindow(manager, on_mode_changed=callback)
    panel = window.qr_widget
    callback.reset_mock()
    panel.v4_relay_url.setText("https://invalid.example")

    panel.v4_button.click()

    assert panel.get_protocol() == "v3"
    assert manager.config.app.dglab_protocol == "v3"
    assert panel.status_text.text() == "⚠ Relay 地址无效"
    callback.assert_not_called()
    window.close()


def test_pairing_url_uses_official_v4_tid_format():
    """V4 二维码包含 Relay 地址和官方要求的 tid 参数。"""
    app_url, pairing_url = CoyoteV4Controller.build_pairing_urls(
        "wss://trex.dungeon-lab.cn/v4", "controller-123"
    )

    assert app_url == (
        "wss://trex.dungeon-lab.cn/v4?tid=controller-123"
    )
    assert pairing_url.startswith(PAIRING_URL_PREFIX)
    assert "%3Ftid%3Dcontroller-123" in pairing_url


@pytest.mark.parametrize("url", ["http://example.com", "127.0.0.1:9998", ""])
def test_invalid_relay_url_is_rejected(url):
    """V4 控制器只接受完整 ws/wss Relay 地址。"""
    if not url:
        assert CoyoteV4Controller.normalize_relay_url(url) == DEFAULT_RELAY_URL
        return
    with pytest.raises(ValueError):
        CoyoteV4Controller.normalize_relay_url(url)


def test_pulse_is_encoded_as_official_eight_byte_hex_frame():
    """四组频率和强度按官方顺序编码为八字节十六进制。"""
    frame = CoyoteV4Controller.pulse_to_hex(
        ((10, 20, 30, 40), (100, 80, 60, 40)),
        100,
    )

    assert frame == "0A141E2832281E14"


def test_app_switches_controller_after_protocol_setting_is_saved():
    """保存 V4 选择后停止 V3，并安排启动新的 V4 控制器。"""
    app = App.__new__(App)
    app.config_mgr = SimpleNamespace(config=SimpleNamespace(
        app=SimpleNamespace(
            dglab_protocol="v4",
            ws_port=8765,
            v4_relay_url=DEFAULT_RELAY_URL,
        ),
    ))
    app._coyote_protocol = "v3"
    app._coyote_started = True
    app._coyote_starting = False
    old_controller = CoyoteController(port=8765)
    old_controller.clear_all = Mock()
    old_controller.stop = Mock()
    app.coyote = old_controller
    app._controllers = [old_controller]
    replacement = Mock()
    app._create_coyote_controller = Mock(return_value=replacement)
    app.window = SimpleNamespace(
        qr_widget=SimpleNamespace(clear_qr_image=Mock()),
        after=Mock(),
    )

    app._retiring_controllers = []

    app._switch_coyote_protocol_if_needed()

    old_controller.clear_all.assert_called_once_with()
    # stop 不在 GUI 线程执行，交给下一次启动线程（B6）
    old_controller.stop.assert_not_called()
    assert app._retiring_controllers == [old_controller]
    assert app.coyote is replacement
    assert app._coyote_protocol == "v4"
    assert not app._coyote_started
    app.window.qr_widget.clear_qr_image.assert_called_once_with()
    app.window.after.assert_called_once_with(200, app._start_coyote)


@pytest.mark.asyncio
async def test_app_snapshot_selects_coyote_and_resets_both_channels():
    """App 上报郊狼后先归零 A/B，再标记设备可输出。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket

    await controller._handle_frame({
        "type": "client_attached",
        "clientId": "app-1",
    })
    await controller._handle_frame({
        "type": "message",
        "clientId": "app-1",
        "data": {
            "t": "ev",
            "ev": "devices.snapshot",
            "devices": [{
                "slotId": "slot-1",
                "name": "郊狼 3.0",
                "type": "COYOTE_030",
            }],
        },
    })

    await controller._binding_task
    assert controller.status.client_connected
    assert controller.status.bound
    assert controller.status.address == "V4 · 郊狼 3.0"
    assert websocket.messages[0]["data"]["m"] == "devices.get"
    resets = [operation_from(frame) for frame in websocket.messages[1:] if frame["data"]["m"] == "device.op"]
    assert resets == [
        {"s": "slot-1", "c": 0, "t": 7, "v": 0, "im": True},
        {"s": "slot-1", "c": 1, "t": 7, "v": 0, "im": True},
    ]


@pytest.mark.asyncio
async def test_strength_commands_use_delta_pulse_reset_and_clear():
    """V4 目标强度转换为增量，并在归零时清理通道任务。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.bound = True

    await controller._execute_command(("strength", "A", 40))
    assert operation_from(websocket.messages[0])["v"] == 40
    pulse = operation_from(websocket.messages[1])
    assert pulse["t"] == 0
    assert pulse["d"] == 1000
    assert pulse["v"] == ["0A0A0A0A14141414"] * 10

    websocket.messages.clear()
    await controller._execute_command(("strength", "A", 20))
    assert operation_from(websocket.messages[0])["v"] == -20

    websocket.messages.clear()
    await controller._execute_command(("strength", "A", 0))
    assert len(websocket.messages) == 2
    assert operation_from(websocket.messages[1])["t"] == 7
    assert operation_from(websocket.messages[1])["v"] == 0
    assert websocket.messages[0]["data"]["m"] == "device.op.clear"
    assert websocket.messages[0]["data"]["data"] == {
        "s": "slot-1",
        "c": 0,
    }


@pytest.mark.asyncio
async def test_single_report_does_not_replace_confirmed_delta_base():
    """单条延迟上报仅作显示，不改变已确认基准。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.bound = True
    controller._app_strength = {"A": 60, "B": None}  # App 实际 60（如手动调过）
    controller._last_strength = {"A": 0, "B": 0}

    await controller._execute_command(("strength", "A", 30))

    # 延迟上报不参与增量计算；持续偏差由独立归零恢复流程处理。
    assert operation_from(websocket.messages[0])["v"] == 30
    assert controller._last_strength["A"] == 30
    assert controller._app_strength["A"] == 60


@pytest.mark.asyncio
async def test_pending_report_does_not_double_count_delta():
    """App 上报滞后期间连续调强度，以已确认命令值为基准不重复累计。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.bound = True

    await controller._execute_command(("strength", "A", 30))
    websocket.messages.clear()
    await controller._execute_command(("strength", "A", 40))
    # 上报尚未到达，基准应为预写的 30 → 增量 10 而非 40
    assert operation_from(websocket.messages[0])["v"] == 10


@pytest.mark.asyncio
async def test_unverified_report_does_not_repeat_confirmed_increment():
    """已确认的增量不能因单条低值报告而再次累加。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.bound = True
    # 目标 40 曾下发（本地记录 40），但指令丢失，App 上报回落为 0
    controller._last_strength = {"A": 40, "B": 0}
    controller._app_strength = {"A": 0, "B": None}

    await controller._execute_command(("strength", "A", 40))

    assert not websocket.messages
    assert controller._last_strength["A"] == 40


@pytest.mark.asyncio
async def test_slots_patch_updates_strength_base():
    """slots.patch 上报的通道强度写入闭环基准。"""
    controller = CoyoteV4Controller()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])

    await controller._handle_app_data("app-1", {
        "t": "ev", "ev": "slots.patch",
        "slots": [{"slotId": "slot-1", "props": {"intensityA": 55}}],
    })

    assert controller._app_strength["A"] == 55


@pytest.mark.asyncio
async def test_other_slot_report_ignored():
    """其他 slot 的上报不影响当前设备基准。"""
    controller = CoyoteV4Controller()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])

    await controller._handle_app_data("app-1", {
        "t": "ev", "ev": "slots.patch",
        "slots": [{"slotId": "slot-other", "props": {"intensityA": 99}}],
    })

    assert controller._app_strength["A"] is None


@pytest.mark.asyncio
async def test_bind_resets_strength_base_to_zero():
    """绑定设备归零后闭环基准为 0。"""
    controller = CoyoteV4Controller()
    controller._websocket = FakeWebSocket(controller)
    controller._client_id = "app-1"

    await controller._handle_app_data("app-1", {
        "t": "ev", "ev": "devices.snapshot",
        "devices": [{"slotId": "slot-1", "type": "COYOTE_030",
                     "name": "Coyote", "props": {"intensityA": 90}}],
    })

    await controller._binding_task
    assert controller._status.bound
    assert controller._last_strength == {"A": 0, "B": 0}
    assert controller._app_strength == {"A": None, "B": None}


@pytest.mark.asyncio
async def test_selected_app_disconnect_clears_bound_state():
    """当前 V4 App 断开后立即撤销设备绑定状态。"""
    controller = CoyoteV4Controller()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.client_connected = True
    controller._status.bound = True

    await controller._handle_frame({
        "type": "client_disconnected",
        "clientId": "app-1",
    })

    assert not controller.status.client_connected
    assert not controller.status.bound
    assert controller.status.address == "DG-LAB 4 App 已断开"


def _bound_v4(catalog=None):
    """创建已绑定、使用假 WebSocket 的 V4 控制器。"""
    controller = CoyoteV4Controller(catalog=catalog)
    websocket = FakeWebSocket(controller)
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._registry.replace([{ "slotId": "slot-1", "type": "COYOTE_030" }])
    controller._status.bound = True
    return controller, websocket


def _slot_report(value):
    """构造 slots.patch 强度上报。"""
    return {"t": "ev", "ev": "slots.patch",
            "slots": [{"slotId": "slot-1", "props": {"intensityA": value}}]}


@pytest.mark.asyncio
async def test_stale_report_during_cooldown_does_not_overshoot():
    """冷却期内到达的发送前旧值不作基准，不产生二次增量（B5）。"""
    controller, websocket = _bound_v4()
    await controller._execute_command(("strength", "A", 100))
    # 发送 +100 后 App 仍上报发送前的 0
    await controller._handle_app_data("app-1", _slot_report(0))
    websocket.messages.clear()
    await controller._execute_command(("strength", "A", 110))
    # 以已确认的 100 为基准 → +10，而不是以旧值 0 算出 +110 超调
    assert operation_from(websocket.messages[0])["v"] == 10


@pytest.mark.asyncio
async def test_pending_report_is_discarded_after_cooldown():
    """冷却期旧报告过期后仍是旧报告，不能再次参与增量计算。"""
    controller, websocket = _bound_v4()
    await controller._execute_command(("strength", "A", 50))
    await controller._handle_app_data("app-1", _slot_report(0))
    await controller._handle_app_data("app-1", _slot_report(70))
    assert controller._app_strength["A"] == 70
    assert controller._last_strength["A"] == 50
    controller._calib_block_until["A"] = 0.0  # 模拟冷却结束
    websocket.messages.clear()
    await controller._execute_command(("strength", "A", 50))
    # 冷却期旧报告不会在过期后成为新基准，仅补给波形。
    assert all(operation_from(frame)["t"] == 0 for frame in websocket.messages)


@pytest.mark.asyncio
async def test_report_outside_cooldown_updates_base_immediately():
    """非冷却期的上报直接写入基准。"""
    controller, _ = _bound_v4()
    await controller._execute_command(("strength", "A", 40))
    controller._calib_block_until["A"] = 0.0
    await controller._handle_app_data("app-1", _slot_report(45))
    assert controller._app_strength["A"] == 45


@pytest.mark.asyncio
async def test_reset_starts_cooldown_and_detach_clears_it():
    """归零同样进入冷却；解绑清除冷却状态。"""
    controller, _ = _bound_v4()
    await controller._execute_command(("strength", "A", 40))
    await controller._execute_command(("strength", "A", 0))
    await controller._handle_app_data("app-1", _slot_report(40))
    assert controller._app_strength["A"] == 40
    assert controller._last_strength["A"] == 0
    controller._detach_device("测试解绑", keep_client=True)
    assert controller._calib_block_until == {"A": 0.0, "B": 0.0}
    assert controller._pending_report == {"A": None, "B": None}


def _v4_catalog(tmp_path, *names):
    """在临时目录写入最小可解析的 .pulse 波形。"""
    from src.waveforms import WaveformCatalog
    directory = tmp_path / "waveforms"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text(
            "Dungeonlab+pulse:0,1,0=10,10,0,1,1/50-0,100-1", encoding="utf-8")
    catalog = WaveformCatalog(tmp_path)
    catalog.reload()
    return catalog


@pytest.mark.asyncio
async def test_waveform_switch_while_active_sends_immediately(tmp_path):
    """输出中切换波形立即下发新波形，不依赖强度变化（B4）。"""
    controller, websocket = _bound_v4(_v4_catalog(tmp_path, "新波形.pulse"))
    await controller._execute_command(("strength", "A", 60))
    websocket.messages.clear()
    await controller._execute_command(("waveform", "A", "新波形.pulse"))
    assert len(websocket.messages) == 1
    operation = operation_from(websocket.messages[0])
    assert operation["t"] == 0 and operation["im"] is True
    # 相同配置重复提交不再下发
    await controller._execute_command(("waveform", "A", "新波形.pulse"))
    assert len(websocket.messages) == 1


@pytest.mark.asyncio
async def test_waveform_switch_while_silent_does_not_send(tmp_path):
    """强度为 0 时切换波形只记录，不下发。"""
    controller, websocket = _bound_v4(_v4_catalog(tmp_path, "新波形.pulse"))
    await controller._execute_command(("waveform", "A", "新波形.pulse"))
    assert websocket.messages == []
    assert controller.telemetry.snapshot("A").name == "新波形.pulse"


@pytest.mark.asyncio
async def test_stop_during_hello_wait_does_not_start_tasks(monkeypatch):
    """等待 hello 期间 stop()：不启动命令 / 心跳任务，启动结果为失败（B7）。"""
    import asyncio
    import src.coyote_v4_controller as v4

    controller = CoyoteV4Controller()
    started = []

    class FakeConnect:
        async def __aenter__(self):
            return FakeWebSocket(controller)

        async def __aexit__(self, *args):
            return False

    async def fake_message_loop():
        controller._running = False  # 模拟 hello 到达前用户已 stop()
        controller._ready_event.set()
        await asyncio.sleep(10)

    async def fake_command_loop():
        started.append("processor")

    monkeypatch.setattr(v4.websockets, "connect", lambda *a, **k: FakeConnect())
    monkeypatch.setattr(controller, "_message_loop", fake_message_loop)
    monkeypatch.setattr(controller, "_command_loop", fake_command_loop)
    controller._running = True

    await controller._async_main()
    # 让可能被错误创建的任务有机会运行
    await asyncio.sleep(0)

    assert started == []
    assert controller._result_queue.get_nowait() is False
    assert not controller.status.server_running


def test_start_worker_stops_retiring_controller_before_starting_new():
    """启动线程先停止旧控制器再启动新控制器，结果仍经队列回主线程（B6）。"""
    import queue as queue_module
    order = []
    app = App.__new__(App)
    app._coyote_start_queue = queue_module.Queue(maxsize=2)
    old_controller = Mock()
    old_controller.stop.side_effect = lambda: order.append("stop-old")
    new_controller = Mock()
    new_controller.start.side_effect = lambda: order.append("start-new") or True
    new_controller.get_qrcode_url.return_value = "url"
    new_controller.status = SimpleNamespace(error="")

    app._start_coyote_worker(new_controller, "V4 Relay", [old_controller])

    assert order == ["stop-old", "start-new"]
    assert app._coyote_start_queue.get_nowait()[0] is new_controller


def test_stale_start_result_stops_controller_off_gui_thread():
    """过期控制器的启动结果在后台线程停止，不阻塞主线程（B6）。"""
    import queue as queue_module
    import threading
    app = App.__new__(App)
    app._coyote_start_queue = queue_module.Queue(maxsize=2)
    app._start_workers = []
    app.coyote = Mock()
    stale = Mock()
    stopped_on = []
    stale.stop.side_effect = lambda: stopped_on.append(threading.current_thread())
    app._coyote_start_queue.put((stale, "V3 服务端", True, "", ""))

    app._process_coyote_start_result()
    for worker in app._start_workers:
        worker.join(timeout=2)

    assert stopped_on and stopped_on[0] is not threading.current_thread()


@pytest.mark.parametrize("protocol", ["v3", "v4"])
def test_unexpected_service_exit_schedules_restart(protocol):
    """V3 / V4 服务运行中意外退出时 5 秒后自动重启（B8）。"""
    app = App.__new__(App)
    app._running = True
    app._coyote_protocol = protocol
    app._coyote_started = True
    app._coyote_starting = False
    app.coyote = SimpleNamespace(status=SimpleNamespace(
        server_running=False, bound=False, client_connected=False,
        address="", error="端口被占用"))
    app.window = SimpleNamespace(
        after=Mock(),
        status_bar=SimpleNamespace(set_coyote_status=Mock()),
        qr_widget=SimpleNamespace(set_status=Mock()),
    )

    app._update_coyote_status()

    app.window.after.assert_called_once_with(5000, app._start_coyote)
    assert not app._coyote_started


def test_no_restart_while_shutting_down():
    """退出过程中服务停止不触发重启。"""
    app = App.__new__(App)
    app._running = False
    app._coyote_protocol = "v3"
    app._coyote_started = True
    app._coyote_starting = False
    app.coyote = SimpleNamespace(status=SimpleNamespace(
        server_running=False, bound=False, client_connected=False,
        address="", error=""))
    app.window = SimpleNamespace(
        after=Mock(),
        status_bar=SimpleNamespace(set_coyote_status=Mock()),
        qr_widget=SimpleNamespace(set_status=Mock()),
    )

    app._update_coyote_status()

    app.window.after.assert_not_called()
