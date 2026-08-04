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


class FakeWebSocket:
    """记录 V4 控制器发送内容的简易 WebSocket。"""

    def __init__(self):
        self.messages = []
        self.closed = False

    async def send(self, message):
        """记录一条出站消息。"""
        self.messages.append(json.loads(message))

    async def close(self):
        """记录关闭操作。"""
        self.closed = True


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
    replacement = Mock()
    app._create_coyote_controller = Mock(return_value=replacement)
    app.window = SimpleNamespace(
        qr_widget=SimpleNamespace(clear_qr_image=Mock()),
        after=Mock(),
    )

    app._switch_coyote_protocol_if_needed()

    old_controller.clear_all.assert_called_once_with()
    old_controller.stop.assert_called_once_with()
    assert app.coyote is replacement
    assert app._coyote_protocol == "v4"
    assert not app._coyote_started
    app.window.qr_widget.clear_qr_image.assert_called_once_with()
    app.window.after.assert_called_once_with(200, app._start_coyote)


@pytest.mark.asyncio
async def test_app_snapshot_selects_coyote_and_resets_both_channels():
    """App 上报郊狼后先归零 A/B，再标记设备可输出。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket()
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

    assert controller.status.client_connected
    assert controller.status.bound
    assert controller.status.address == "V4 · 郊狼 3.0"
    assert websocket.messages[0]["data"]["m"] == "devices.get"
    resets = [operation_from(frame) for frame in websocket.messages[1:]]
    assert resets == [
        {"s": "slot-1", "c": 0, "t": 7, "v": 0, "im": True},
        {"s": "slot-1", "c": 1, "t": 7, "v": 0, "im": True},
    ]


@pytest.mark.asyncio
async def test_strength_commands_use_delta_pulse_reset_and_clear():
    """V4 目标强度转换为增量，并在归零时清理通道任务。"""
    controller = CoyoteV4Controller()
    websocket = FakeWebSocket()
    controller._websocket = websocket
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
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
    assert operation_from(websocket.messages[0])["t"] == 7
    assert websocket.messages[1]["data"]["m"] == "device.op.clear"
    assert websocket.messages[1]["data"]["data"] == {
        "s": "slot-1",
        "c": 0,
    }


@pytest.mark.asyncio
async def test_selected_app_disconnect_clears_bound_state():
    """当前 V4 App 断开后立即撤销设备绑定状态。"""
    controller = CoyoteV4Controller()
    controller._client_id = "app-1"
    controller._slot_id = "slot-1"
    controller._status.client_connected = True
    controller._status.bound = True

    await controller._handle_frame({
        "type": "client_disconnected",
        "clientId": "app-1",
    })

    assert not controller.status.client_connected
    assert not controller.status.bound
    assert controller.status.address == "DG-LAB 4 App 已断开"
