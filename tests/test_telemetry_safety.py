"""8111 遥测失效时的安全归零回归测试。"""

import queue
from types import SimpleNamespace
from unittest.mock import Mock

from main import App
from src.game_reader import GameReader, GameState


class FakeResponse:
    """提供固定 JSON 响应的简易 HTTP 响应对象。"""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        """返回预设 JSON 数据。"""
        return self.payload


class FakeSession:
    """按 URL 返回预设响应，记录读取顺序。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, timeout):
        """模拟 requests.Session.get。"""
        self.calls.append(url)
        return self.responses[url]


def make_reader(responses):
    """创建使用伪 HTTP 会话的游戏读取器。"""
    reader = GameReader()
    reader._session = FakeSession(responses)
    return reader


def test_menu_stale_indicators_do_not_create_tank_data():
    """游戏菜单的残留速度不可被当成有效坦克遥测。"""
    reader = make_reader({
        GameReader.STATE_URL: FakeResponse({"valid": False}),
        GameReader.MAP_INFO_URL: FakeResponse({"valid": False}),
        GameReader.INDICATORS_URL: FakeResponse({
            "valid": True,
            "army": "tank",
            "speed": 68.0,
        }),
    })

    state = reader.fetch()

    assert not state.connected
    assert state.vehicle_type == ""
    assert state.tank is None
    assert reader._session.calls == [
        GameReader.STATE_URL,
        GameReader.MAP_INFO_URL,
    ]


def test_active_tank_uses_complete_map_metadata_when_valid_flag_is_omitted():
    """兼容有效地图响应未提供 valid 字段的 8111 版本。"""
    reader = make_reader({
        GameReader.STATE_URL: FakeResponse({"valid": False}),
        GameReader.MAP_INFO_URL: FakeResponse({
            "grid_steps": ["3250.0", "3250.0"],
            "grid_zero": ["-32768.0", "32768.0"],
            "map_generation": "1",
            "map_max": ["32768.0", "32768.0"],
            "map_min": ["-32768.0", "-32768.0"],
        }),
        GameReader.INDICATORS_URL: FakeResponse({
            "valid": True,
            "army": "tank",
            "type": "tankModels/us_m1a1_hc_usmc_sm",
            "speed": 68.0,
        }),
    })

    state = reader.fetch()

    assert state.connected
    assert state.vehicle_type == "tank"
    assert state.tank is not None
    assert state.tank.valid
    assert state.tank.speed_kmh == 68.0


def test_inactive_state_cancels_event_and_forces_zero_output():
    """离开有效对局时，事件覆盖也必须停止并发送 A/B 归零。"""
    app = App.__new__(App)
    app.config_mgr = SimpleNamespace(config=SimpleNamespace())
    app._last_state = GameState()
    app._wt_fail_count = 0
    app._wt_connected = True
    app._event_kind = "kill"
    app._event_mode = "tank"
    app._event_ch_a = 100
    app._event_ch_b = 120
    app._event_remaining = 5.0
    app._overlay_last_value = "68"
    app._overlay_last_unit = "km/h"
    app._send_strength = Mock()
    app._sync_overlay = Mock()
    app._apply_waveform = Mock()
    app.coyote = SimpleNamespace(status=SimpleNamespace(bound=True))
    app.window = SimpleNamespace(
        get_mode=Mock(return_value="tank"),
        status_bar=SimpleNamespace(set_wt_status=Mock()),
        dashboard=SimpleNamespace(clear=Mock(), show_event=Mock()),
    )

    app._apply_game_state(GameState())

    app._send_strength.assert_called_once_with(0, 0)
    app._apply_waveform.assert_called_once()
    app.window.dashboard.clear.assert_called_once_with("tank")
    app._sync_overlay.assert_called_once_with("tank", 0, 0)
    assert app._event_remaining == 0.0
    assert app._event_kind == ""
    assert app._event_ch_a == 0
    assert app._event_ch_b == 0
    assert app._overlay_last_value == ""
    assert app._overlay_last_unit == ""


def test_overlay_never_reuses_a_value_after_telemetry_becomes_invalid():
    """悬浮窗在对局失效后显示占位符，而非退出前的速度。"""
    app = App.__new__(App)
    app._apply_overlay_settings = Mock()
    app._last_state = GameState()
    app._overlay_last_value = "68"
    app._overlay_last_unit = "km/h"
    app.overlay = SimpleNamespace(visible=True, update=Mock())

    app._sync_overlay("tank", 80, 100)

    app.overlay.update.assert_called_once_with("tank", "--", "km/h", 0, 0, "")
    assert app._overlay_last_value == ""
    assert app._overlay_last_unit == ""


def test_event_tick_reuses_last_state_when_no_new_telemetry_is_queued():
    """事件先到达时，不得用空状态误取消该事件。"""
    app = App.__new__(App)
    app._event_queue = queue.Queue()
    app._event_queue.put({"kind": "kill"})
    app._data_queue = queue.Queue()
    app._last_state = GameState(connected=True)
    app._event_remaining = 0.0
    app._event_kind = "kill"
    app._event_mode = "tank"
    app._running = False
    app._apply_game_state = Mock()
    app._update_coyote_status = Mock()
    app.window = SimpleNamespace(dashboard=SimpleNamespace(show_event=Mock()))

    def apply_event(_event):
        app._event_remaining = 5.0

    app._apply_event = Mock(side_effect=apply_event)

    app._ui_tick()

    app._apply_event.assert_called_once()
    app._apply_game_state.assert_called_once_with(app._last_state)


def test_app_queues_events_returned_by_event_detector():
    """主控制器将本轮状态交给独立检测器并把结果放入 UI 队列。"""
    aircraft_events = object()
    tank_events = object()
    app = App.__new__(App)
    app.config_mgr = SimpleNamespace(config=SimpleNamespace(
        events=aircraft_events,
        tank_events=tank_events,
    ))
    app._current_mode = "tank"
    app._event_queue = queue.Queue()
    app.event_detector = SimpleNamespace(poll=Mock(return_value={
        "kind": "kill",
        "mode": "tank",
    }))
    state = GameState(connected=True, vehicle_type="tank")

    app._poll_events(state)

    app.event_detector.poll.assert_called_once_with(
        state,
        "tank",
        aircraft_events,
        tank_events,
    )
    assert app._event_queue.get_nowait() == {
        "kind": "kill",
        "mode": "tank",
    }
