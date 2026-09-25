"""维修、死亡及重新出击交叉场景的输出回归测试。"""

import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from main import App
from src.config_manager import Config
from src.game_reader import AircraftData, GameState, TankData


def tank_state(repairing=True, valid=True):
    """创建有效战局中的坦克遥测。"""
    return GameState(
        connected=True, link_ok=True, vehicle_type="tank",
        tank=TankData(valid=valid, is_repairing=repairing, speed_kmh=30),
    )


def event(kind):
    """构造可区分强度和波形的陆战事件。"""
    return dict(kind=kind, mode="tank", ch_a=81, ch_b=42,
                duration=60 if kind == "repair" else 5,
                wf_a="事件A", wf_b="事件B")


@pytest.fixture
def app():
    """保留真实事件、波形和映射逻辑，仅替换界面及设备边界。"""
    instance = App.__new__(App)
    cfg = Config()
    cfg.tank.enabled = False
    cfg.cas.enabled = False
    cfg.tank_events.repair_enabled = True
    cfg.tank_events.repair_ch_a = 25
    cfg.tank_events.repair_ch_b = 26
    instance.config_mgr = SimpleNamespace(config=cfg)
    instance._last_state = tank_state()
    instance._event_kind = ""
    instance._event_mode = ""
    instance._event_remaining = 0
    instance._repair_blocked_until_idle = False
    instance._repair_death_state = None
    instance._wt_connected = True
    instance._wt_fail_count = 0
    instance._overlay_tick = 0
    instance._running = False
    instance._event_queue = queue.Queue()
    instance._data_queue = queue.Queue()
    instance.window = Mock()
    instance.window.get_mode.return_value = "tank"
    instance.coyote = Mock()
    instance.coyote.status.bound = True
    instance._send_strength = Mock()
    instance._sync_overlay = Mock()
    instance._process_coyote_start_result = Mock()
    instance._update_coyote_status = Mock()
    instance._update_channel_wave_names = Mock()
    return instance


def tick(app, state=None, events=()):
    """执行完整 UI 刷新，并确保未在异常捕获中提前退出。"""
    if state is not None:
        app._data_queue.put(state)
    for item in events:
        app._event_queue.put(item)
    app._update_channel_wave_names.reset_mock()
    app._ui_tick()
    app._update_channel_wave_names.assert_called_once()


def test_death_expiry_never_resumes_stale_repair(app):
    """选车界面保留维修字段时，死亡到期当轮归零且不再恢复维修。"""
    tick(app, tank_state(), [event("repair")])
    app._send_strength.assert_called_with(81, 42)
    tick(app, tank_state(), [event("death"), event("repair")])
    assert app._event_kind == "death"
    app._event_remaining = 0.05
    tick(app)
    assert app._event_kind == ""
    app._send_strength.assert_called_with(0, 0)
    app.window.dashboard.show_event.assert_called_with("")
    assert app._sync_overlay.call_args.args[1:] == (0, 0)
    assert app.coyote.set_waveform_a.call_args.args[0] == "恒定"
    tick(app, tank_state(), [event("repair")])
    assert app._event_kind == ""
    app._send_strength.assert_called_with(0, 0)


@pytest.mark.parametrize("state", [
    GameState(),
    GameState(connected=True, link_ok=True),
    tank_state(repairing=False, valid=False),
    tank_state(),
    GameState(connected=True, vehicle_type="aircraft",
              aircraft=AircraftData(valid=True)),
])
def test_missing_menu_and_stale_states_do_not_rearm_repair(app, state):
    """机库、缺失数据、飞机及残留维修都不能解除旧维修限制。"""
    tick(app, tank_state(), [event("death")])
    tick(app, state)
    assert app._repair_blocked_until_idle
    tick(app, tank_state(), [event("repair")])
    assert app._event_kind != "repair"


def test_repair_rearms_only_after_later_valid_idle_frame(app):
    """死亡同轮非维修帧不能解锁；后续退出维修才允许新维修。"""
    tick(app, tank_state(False), [event("death")])
    tick(app)
    assert app._repair_blocked_until_idle
    tick(app, tank_state(False))
    assert not app._repair_blocked_until_idle
    # 死亡仍在倒计时，排队维修仍不得覆盖它。
    tick(app, tank_state(), [event("repair")])
    assert app._event_kind == "death"
    app._event_remaining = 0.05
    tick(app)
    assert app._event_kind == ""
    tick(app, tank_state(False))
    tick(app, tank_state(), [event("repair")])
    assert app._event_kind == "repair"
    app._send_strength.assert_called_with(81, 42)


@pytest.mark.parametrize(
    "repairing,expected", [(True, (25, 26)), (False, (0, 0))],
)
def test_kill_expiry_applies_repair_or_normal_output_immediately(
        app, repairing, expected):
    """击杀结束当轮恢复有效维修，否则立即回到正常强度。"""
    tick(app, tank_state(), [event("repair"), event("kill")])
    app._event_remaining = 0.05
    tick(app, tank_state(repairing))
    assert app._event_kind == ("repair" if repairing else "")
    app._send_strength.assert_called_with(*expected)


@pytest.mark.parametrize("state", [
    GameState(),
    GameState(connected=True, link_ok=True),
    tank_state(False),
    tank_state(valid=False),
    GameState(connected=True, vehicle_type="aircraft",
              aircraft=AircraftData(valid=True)),
])
def test_repair_invalidated_before_any_strength_is_sent(app, state):
    """失效当轮不再下发维修强度，并同步清除维修提示。"""
    tick(app, tank_state(), [event("repair")])
    app._send_strength.reset_mock()
    tick(app, state)
    assert app._event_kind == ""
    app._send_strength.assert_called_once_with(0, 0)
    app.window.dashboard.show_event.assert_called_with("")


def test_disabling_repair_cancels_output_before_send(app):
    """关闭维修功能后，即使接口仍报告维修也必须结束输出。"""
    tick(app, tank_state(), [event("repair")])
    app._cfg.tank_events.repair_enabled = False
    app._send_strength.reset_mock()
    tick(app, tank_state())
    assert app._event_kind == ""
    app._send_strength.assert_called_once_with(0, 0)


def test_death_expiry_restores_enabled_normal_mapping(app):
    """结束惩罚后按当前有效数据恢复常规映射，而非无条件归零。"""
    app._cfg.tank.enabled = True
    app._cfg.tank.channel_a_max = 100
    app._cfg.tank.channel_b_max = 80
    tick(app, tank_state(), [event("death")])
    app._event_remaining = 0.05
    tick(app)
    assert app._event_kind == ""
    app._send_strength.assert_called_with(50, 40)
