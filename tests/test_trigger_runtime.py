"""完整采集批次到业务快照、输出计划和协议适配器的回归。"""

from dataclasses import replace
from unittest.mock import Mock
import threading
import time

import pytest

from main import App
from src.dglab_state import ConnectionSnapshot
from src.game_reader import GameReader
from src.game_runtime import GameRuntime
from src.trigger_engine import TriggerEngine
from test_connection_refactor import connected
from test_output_stop_barrier import drain


from runtime_support import config, state, event, observe


@pytest.mark.parametrize("vehicle,scene,mode", [
    ("tank", "tank", "tank"), ("aircraft", "aircraft", "aircraft"),
    ("aircraft", "tank", "tank"),
])
@pytest.mark.parametrize("kind", ["kill", "death"])
@pytest.mark.parametrize("bound", [False, True])
def test_event_preview_uses_scene_and_independent_output_qualification(vehicle, scene, mode, kind, bound):
    cfg = config()
    cfg.app.mode = mode
    engine = TriggerEngine()
    result = observe(engine, cfg, events=[event(kind, mode=vehicle, scene=scene, bound=bound)],
                     snapshot=state(vehicle=vehicle))
    assert result.kind == kind
    expected = getattr(cfg.tank_events if scene == "tank" else cfg.events, f"{kind}_ch_a")
    assert result.a == expected
    assert result.intent.a.strength == (expected if bound else 0)


@pytest.mark.parametrize("first,second,winner", [
    ("kill", "death", "death"), ("death", "kill", "death"),
    ("kill", "hit", "kill"), ("repair", "kill", "kill"),
    ("hit", "repair", "repair"), ("repair", "death", "death"),
])
def test_event_priority_is_independent_of_batch_order(first, second, winner):
    engine, cfg = TriggerEngine(), config()
    result = observe(engine, cfg, events=[event(first), event(second)])
    assert result.kind == winner
    assert len(engine.journal) == 2


def test_same_kind_restarts_clock_without_stacking():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, events=[event()])
    result = observe(engine, cfg, 102, [event(now=102)])
    assert result.remaining == 5
    assert result.a == 30
    result = observe(engine, cfg, 107)
    assert result.kind == ""
    assert result.a == 5


def test_gui_absence_does_not_prevent_event_expiry_and_latest_normal_restore():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, events=[event()])
    observe(engine, cfg, 104.9)
    result = engine.tick(cfg, ("controller", 1), True, 105.01)
    assert result.kind == ""
    assert result.intent.a.strength == 5


@pytest.mark.parametrize("kind", ["kill", "death", "hit", "repair"])
def test_old_session_and_initially_unbound_events_cannot_gain_output(kind):
    engine, cfg = TriggerEngine(), config()
    s = state(is_repairing=kind == "repair")
    s.event_output_bound = False
    result = observe(engine, cfg, events=[event(kind, bound=False)], snapshot=s)
    assert result.kind == kind
    result = engine.tick(cfg, ("controller", 1), True, 100.1)
    assert result.intent.a.strength == 0
    engine.tick(cfg, ("controller", 2), False, 100.2)
    result = engine.tick(cfg, ("controller", 1), True, 100.3)
    assert result.intent.a.strength == 0


def test_repair_first_observation_survives_kill_without_gaining_new_session():
    engine, cfg = TriggerEngine(), config()
    s = state(is_repairing=True)
    s.event_output_bound = False
    observe(engine, cfg, events=[event()], snapshot=s)
    assert engine.repair is not None
    s = state(105, is_repairing=True)
    result = observe(engine, cfg, 105, snapshot=s)
    assert result.kind == "repair"
    assert result.intent.a.strength == 0


def test_repair_ends_immediately_and_does_not_resume_after_death():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, snapshot=state(is_repairing=True))
    assert engine.active.event.kind == "repair"
    result = observe(engine, cfg, 101)
    assert result.kind == ""
    observe(engine, cfg, 102, [event("death", 102)], state(102, is_repairing=True))
    result = observe(engine, cfg, 107, snapshot=state(107, is_repairing=True))
    assert result.kind == ""
    observe(engine, cfg, 108)
    result = observe(engine, cfg, 109, snapshot=state(109, is_repairing=True))
    assert result.kind == "repair"


def test_disabled_death_output_still_clears_old_repair():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, snapshot=state(is_repairing=True))
    cfg.tank_events.death_enabled = False
    result = observe(engine, cfg, 101, [event("death", 101)], state(101, is_repairing=True))
    assert result.kind == ""
    assert engine.repair is None


def test_crew_alive_to_dead_is_single_confirmed_death():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, snapshot=state(crew_alive=True))
    result = observe(engine, cfg, 101, snapshot=state(101, crew_alive=False))
    assert result.kind == "death"
    result = observe(engine, cfg, 102, snapshot=state(102, crew_alive=False))
    assert result.remaining == 4


def test_unknown_crew_and_invalid_data_are_not_death():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg)
    result = observe(engine, cfg, 101, snapshot=state(101, mission="unknown"))
    assert result.kind == ""
    assert result.intent.a.strength == 0


@pytest.mark.parametrize("recover_after,expected", [(0.4, "kill"), (1.1, "")])
def test_hud_during_transient_mission_failure_is_bounded(recover_after, expected):
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, 99.8)
    result = observe(engine, cfg, 100, [event()], state(mission="unknown"))
    assert result.intent.a.strength == 0
    result = observe(engine, cfg, 100 + recover_after)
    assert result.kind == expected
    if expected:
        assert result.remaining == pytest.approx(5 - recover_after)


def test_explicit_menu_never_replays_pending_hud():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg)
    observe(engine, cfg, 100.1, [event(now=100.1)], state(100.1, mission="unknown"))
    observe(engine, cfg, 100.2, snapshot=state(100.2, mission="inactive"))
    assert observe(engine, cfg, 100.3).kind == ""


def test_part_damage_baseline_cooldown_and_repair_retrigger():
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, snapshot=state(damaged_parts=frozenset({"履带"})))
    assert engine.active is None
    result = observe(engine, cfg, 101, snapshot=state(101, damaged_parts=frozenset({"履带", "炮闩"})))
    assert result.kind == "hit"
    observe(engine, cfg, 102, snapshot=state(102, damaged_parts=frozenset()))
    observe(engine, cfg, 103)
    assert observe(engine, cfg, 104, snapshot=state(104, damaged_parts=frozenset({"履带"}))).kind == "hit"


def test_idle_uses_elapsed_time_and_death_residue_cannot_unlock():
    engine, cfg = TriggerEngine(), config()
    cfg.tank.idle_enabled = True
    def stationary(now):
        s = state(now)
        s.tank.speed_kmh = 0
        return s
    observe(engine, cfg, snapshot=stationary(100))
    for now in range(101, 110):
        observe(engine, cfg, now, snapshot=stationary(now))
    assert observe(engine, cfg, 110, snapshot=stationary(110)).kind == "idle"
    observe(engine, cfg, 111, [event("death", 111)])
    observe(engine, cfg, 111.2)
    assert observe(engine, cfg, 130, snapshot=stationary(130)).kind == ""
    observe(engine, cfg, 131)
    observe(engine, cfg, 131.5)
    observe(engine, cfg, 132)
    assert not engine._death_blocked
    observe(engine, cfg, 133, snapshot=stationary(133))
    for now in range(134, 143):
        observe(engine, cfg, now, snapshot=stationary(now))
    assert observe(engine, cfg, 143, snapshot=stationary(143)).kind == "idle"


def test_cas_keeps_land_event_configuration_and_can_be_disabled():
    cfg, engine = config(), TriggerEngine()
    result = observe(engine, cfg, events=[event(mode="aircraft")], snapshot=state(vehicle="aircraft"))
    assert result.a == 30
    cfg.cas.enabled = False
    assert engine.tick(cfg, ("controller", 1), True, 100.1).intent.a.strength == 0


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.asyncio
async def test_full_batch_runtime_to_real_adapter_and_expiry(protocol):
    controller, peer = connected(protocol)
    controller._publish_snapshot()
    cfg = config()
    runtime = GameRuntime(None, controller, cfg)
    for now, records in [(100, ()), (100.2, (
        {"id": 0, "msg": "玩家击毁了敌人"},
        {"id": 1, "msg": "敌人击毁了玩家"},
    ))]:
        s = state(now)
        s.hud_records = records
        s.event_session = (id(controller), controller.snapshot().session)
        runtime.process(s, cfg, now)
        result = runtime.advance(now)
        # 使用真实单调时钟使适配器的看门狗期限有效。
        controller.submit_output(replace(result.intent, expires_at=time.monotonic() + 1))
        await drain(controller)
    assert result.kind == "death"
    assert peer.strength == [40, 12]
    assert len([j for j in runtime.engine.journal if j[0].startswith("hud:")]) == 2
    s = state(105.3)
    runtime.process(s, cfg, 105.3)
    result = runtime.advance(105.3)
    controller.submit_output(replace(result.intent, expires_at=time.monotonic() + 1))
    await drain(controller)
    assert result.kind == ""
    assert peer.strength == [5, 3]


def test_gui_render_never_sends_output_and_shares_snapshot_label():
    app = App.__new__(App)
    app.window = Mock()
    app.coyote = Mock()
    app._sync_overlay = Mock()
    app._wt_fail_count = 0
    app._wt_connected = True
    engine, cfg = TriggerEngine(), config()
    result = observe(engine, cfg, events=[event()])
    app._render_trigger_snapshot(result)
    app.window.dashboard.show_event.assert_called_with(result.label)
    app._sync_overlay.assert_called_with("tank", 30, 12)
    app.coyote.submit_output.assert_not_called()


def test_configure_copies_config_and_does_not_reset_event():
    controller = Mock()
    controller.snapshot.return_value = ConnectionSnapshot(session=1, bound=True)
    cfg = config()
    runtime = GameRuntime(None, controller, cfg)
    cfg.tank.channel_a_max = 100
    assert runtime._config.tank.channel_a_max == 5
    runtime.configure(cfg)
    assert runtime._config.tank.channel_a_max == 100


def test_concurrent_collect_is_bounded_and_distinguishes_unknown_from_menu(monkeypatch):
    reader = GameReader()
    barrier = threading.Barrier(4)
    payloads = {
        reader.STATE_URL: {"valid": False},
        reader.INDICATORS_URL: {"valid": True, "army": "tank", "speed": 10},
        reader.MAP_INFO_URL: None,
        reader.HUDMSG_URL: {"damage": [{"id": 0, "msg": "玩家击毁了敌人"}]},
    }
    def fetch(_session, url, **_kwargs):
        barrier.wait(timeout=2)
        return payloads[url]
    monkeypatch.setattr(reader, "_fetch_json", fetch)
    try:
        result = reader.collect()
        assert result.mission_status == "unknown"
        assert not result.connected
        assert result.hud_success and result.hud_records[0]["id"] == 0
        payloads[reader.MAP_INFO_URL] = {"valid": False}
        assert reader.collect().mission_status == "inactive"
        payloads[reader.MAP_INFO_URL] = {"valid": True}
        assert reader.collect().connected
    finally:
        reader.close()
