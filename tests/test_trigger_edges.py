"""新触发链路的真实样本、连续性与双协议满幅语义验证。"""

from dataclasses import replace
import json
from pathlib import Path
import threading
import time
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from main import App
from src.dglab_state import ConnectionSnapshot
from src.event_detector import EventDetector
from src.game_reader import GameReader
from src.game_runtime import GameRuntime
from src.gui.waveform_scope import WaveformScope
from src.trigger_engine import TriggerEngine
from src.waveforms import WaveformCatalog
from runtime_support import config, state, event, observe
from test_connection_refactor import connected
from test_output_stop_barrier import drain


_APP = QApplication.instance() or QApplication([])


def test_production_detector_replays_anonymous_real_id_reuse():
    cfg, detector = config(), EventDetector(None)
    fixture = Path(__file__).parent / "fixtures" / "hud_id_reuse.json"
    frames = json.loads(fixture.read_text(encoding="utf-8"))["frames"]
    counts = []
    for index, frame in enumerate(frames):
        s = state(100 + index)
        s.hud_records = tuple(frame["damage"])
        counts.append(len(detector.detect_records(s, "tank", cfg.events, cfg.tank_events)))
        assert not detector.detect_records(s, "tank", cfg.events, cfg.tank_events)
    assert counts == [0, 1, 1, 1, 1]


def test_production_detector_keeps_id_zero_and_every_same_batch_event():
    cfg, detector = config(), EventDetector(None)
    detector.detect_records(state(), "tank", cfg.events, cfg.tank_events)
    s = state(100.2)
    s.hud_records = (None, {}, {"id": "bad"},
                     {"id": 0, "msg": "玩家击毁了敌人"},
                     {"id": 1, "msg": "敌人击毁了玩家"})
    events = detector.detect_records(s, "tank", cfg.events, cfg.tank_events)
    assert [e.kind for e in events] == ["kill", "death"]
    assert len({e.event_id for e in events}) == 2


@pytest.mark.parametrize("message", [
    "大玩家击毁了敌人", "敌人击毁了玩家123", "敌人 (玩家) destroyed 对手",
    "对手 destroyed 敌人 (玩家)",
])
def test_vehicle_name_and_longer_nickname_are_not_player_identity(message):
    assert not EventDetector._classify_hud_message(message, "玩家")


@pytest.mark.parametrize("strength", [1, 2, 30, 100, 200])
@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.asyncio
async def test_constant_always_full_amplitude_at_channel_intensity(protocol, strength):
    controller, peer = connected(protocol)
    execute = getattr(controller, "_execute_command", None) or controller._exec_command
    await execute(("strength", "A", strength))
    batch = controller.telemetry.snapshot("A").batches[-1]
    assert peer.strength[0] == strength
    assert batch.amplitudes == (100,) * 4
    assert controller._pulse_at("A", time.monotonic()) == ((10,) * 4, (100,) * 4)
    scope = WaveformScope("#4488ff")
    scope.set_data(controller.telemetry.snapshot("A"))
    points = scope._build_points(batch.t + 0.09)
    assert points and max(value for _, value in points) == strength
    scope.deleteLater()


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("strength", [1, 30, 200])
@pytest.mark.asyncio
async def test_custom_curve_is_not_scaled_twice(tmp_path, protocol, strength):
    directory = tmp_path / "waveforms"
    directory.mkdir()
    (directory / "合成测试.pulse").write_text(
        "Dungeonlab+pulse:0,1,0=10,10,0,1,1/50-0,100-1", encoding="utf-8")
    catalog = WaveformCatalog(tmp_path)
    catalog.reload()
    controller, _ = connected(protocol)
    controller._player_a.set_catalog(catalog)
    controller._set_waveform("A", "合成测试.pulse")
    execute = getattr(controller, "_execute_command", None) or controller._exec_command
    await execute(("strength", "A", strength))
    batches = controller.telemetry.snapshot("A").batches
    assert batches[0].amplitudes == (50,) * 4
    assert [batch.amplitudes for batch in batches] == [
        ((50, 100, 0)[index % 3],) * 4 for index in range(len(batches))]


@pytest.mark.parametrize("idle_enabled", [False, True])
def test_death_rearm_needs_continuous_movement_independent_of_idle_switch(idle_enabled):
    engine, cfg = TriggerEngine(), config()
    cfg.tank.idle_enabled = idle_enabled
    observe(engine, cfg, events=[event("death")])
    observe(engine, cfg, 100.2)
    observe(engine, cfg, 102)
    assert engine._death_blocked
    observe(engine, cfg, 102.5)
    observe(engine, cfg, 103)
    assert not engine._death_blocked


@pytest.mark.parametrize("exemption", ["disabled", "repair", "dead", "invalid", "unknown", "moving"])
def test_idle_exemptions_restart_elapsed_timer(exemption):
    cfg, engine = config(), TriggerEngine()
    cfg.tank.idle_enabled = True
    for now in range(100, 110):
        s = state(now)
        s.tank.speed_kmh = 0
        observe(engine, cfg, now, snapshot=s)
    s = state(110)
    s.tank.speed_kmh = 0
    if exemption == "disabled":
        cfg.tank.idle_enabled = False
    elif exemption == "repair":
        s.tank.is_repairing = True
    elif exemption == "dead":
        s.tank.crew_alive = False
    elif exemption == "invalid":
        s.tank.valid = False
    elif exemption == "unknown":
        s.connected = False
        s.mission_status = "unknown"
    else:
        s.tank.speed_kmh = 10
    assert observe(engine, cfg, 110, snapshot=s).kind != "idle"
    cfg.tank.idle_enabled = True
    s = state(111)
    s.tank.speed_kmh = 0
    result = observe(engine, cfg, 111, snapshot=s)
    assert result.kind != "idle"


def test_idle_long_collection_gap_is_not_continuous_stationary_evidence():
    engine, cfg = TriggerEngine(), config()
    cfg.tank.idle_enabled = True
    first, late = state(), state(120)
    first.tank.speed_kmh = late.tank.speed_kmh = 0
    observe(engine, cfg, snapshot=first)
    assert observe(engine, cfg, 120, snapshot=late).kind == ""


@pytest.mark.parametrize("crew", [None, "bad", float("nan"), -1])
def test_malformed_or_missing_crew_is_unknown(crew):
    reader = GameReader()
    try:
        payload = {"valid": True, "crew_total": 4, "crew_current": crew}
        if crew is None:
            payload.pop("crew_current")
        assert reader._parse_tank({}, payload).crew_alive is None
    finally:
        reader.close()


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("normal", [0, 5])
@pytest.mark.parametrize("kind", ["kill", "death", "repair", "hit"])
@pytest.mark.asyncio
async def test_runtime_event_end_restores_both_protocol_channels(protocol, normal, kind):
    controller, peer = connected(protocol)
    controller._publish_snapshot()
    cfg = config()
    cfg.tank.channel_a_max = cfg.tank.channel_b_max = normal
    runtime = GameRuntime(None, controller, cfg)
    now = time.monotonic()
    s = state(now, is_repairing=kind == "repair")
    s.event_session = (id(controller), controller.snapshot().session)
    e = event(kind, now, session=s.event_session)
    runtime.engine.observe(s, [e], cfg, now)
    runtime.advance(now)
    await drain(controller)
    assert peer.strength[0] == getattr(cfg.tank_events, f"{kind}_ch_a")
    runtime.process(state(now + 6), cfg, now + 6)
    result = runtime.advance(now + 6)
    controller.submit_output(replace(result.intent, expires_at=time.monotonic() + 1))
    await drain(controller)
    assert peer.strength == [normal, normal]


def test_event_preview_wave_names_are_shared_with_dashboard():
    app = App.__new__(App)
    app.window = Mock()
    engine, cfg = TriggerEngine(), config()
    cfg.tank_events.kill_wf_a = "事件波形.pulse"
    app._view_snapshot = observe(engine, cfg, events=[event(bound=False)])
    app._update_channel_wave_names()
    app.window.dashboard.channel_a.set_wave_name.assert_called_once_with("事件波形.pulse")


def test_unknown_vehicle_uses_recent_cas_identity_without_bypassing_cas_switch():
    controller = Mock()
    controller.snapshot.return_value = ConnectionSnapshot(session=1, bound=True)
    cfg = config()
    cfg.cas.enabled = False
    runtime = GameRuntime(None, controller, cfg)
    runtime.process(state(vehicle="aircraft"), cfg, 100)
    runtime.process(state(100.05, vehicle="", mission="unknown"), cfg, 100.05)
    lost = state(100.1, vehicle="", mission="unknown")
    lost.hud_records = ({"id": 0, "msg": "玩家已坠毁"},)
    runtime.process(lost, cfg, 100.1)
    runtime.process(state(100.2, vehicle="aircraft"), cfg, 100.2)
    assert runtime.advance(100.2).kind == ""
    assert any("CAS" in decision for _, _, decision in runtime.engine.journal)


def test_disabled_hit_consumes_damage_baseline_and_cooldown_is_not_a_queue():
    cfg, engine = config(), TriggerEngine()
    cfg.tank_events.hit_enabled = False
    observe(engine, cfg)
    observe(engine, cfg, 100.2, snapshot=state(100.2, damaged_parts=frozenset({"履带"})))
    cfg.tank_events.hit_enabled = True
    assert observe(engine, cfg, 100.4, snapshot=state(100.4, damaged_parts=frozenset({"履带"}))).kind == ""
    # 冷却期内的新损伤被消费，冷却结束不会补播。
    observe(engine, cfg, 100.6, snapshot=state(100.6, damaged_parts=frozenset({"履带", "炮闩"})))
    for now in (101, 102, 103):
        result = observe(engine, cfg, now, snapshot=state(now, damaged_parts=frozenset({"履带", "炮闩"})))
    assert result.kind == ""


def test_missing_repair_fields_report_unavailable_without_inventing_event():
    cfg, engine = config(), TriggerEngine()
    s = state()
    s.tank.repair_supported = False
    result = observe(engine, cfg, snapshot=s)
    assert not result.kind
    assert "当前接口未提供" in result.diagnostic


def test_replacing_controller_revokes_previous_dispatcher_output():
    first, second = Mock(), Mock()
    first.snapshot.return_value = second.snapshot.return_value = ConnectionSnapshot(session=1, bound=True)
    cfg = config()
    runtime = GameRuntime(None, first, cfg)
    runtime.process(state(), cfg, 100)
    runtime.advance(100)
    first.stop_output.reset_mock()
    runtime.configure(cfg, second)
    runtime.advance(100.1)
    first.stop_output.assert_called_once()
    second.stop_output.assert_called_once()


def test_gui_repeated_render_does_not_count_as_new_failed_samples():
    app = App.__new__(App)
    app.window = Mock()
    app._sync_overlay = Mock()
    app._wt_fail_count = 0
    app._wt_connected = True
    engine, cfg = TriggerEngine(), config()
    s = state(mission="unknown")
    s.link_ok = False
    result = observe(engine, cfg, snapshot=s)
    for _ in range(20):
        app._render_trigger_snapshot(result)
    assert app._wt_connected and app._wt_fail_count == 1


def test_background_clock_expires_while_collection_and_gui_are_blocked():
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    class SlowReader:
        def collect(self):
            entered.set()
            release.wait(2)
            return state(time.monotonic())

        def close(self):
            pass

    controller = Mock()
    controller.snapshot.return_value = ConnectionSnapshot(session=1, bound=True)
    cfg = config()
    cfg.tank_events.kill_duration = 0.08
    runtime = GameRuntime(SlowReader(), controller, cfg)
    now = time.monotonic()
    s = state(now)
    s.event_session = (id(controller), 1)
    runtime.engine.observe(s, [event(now=now, session=s.event_session)], cfg, now)
    runtime.advance(now)
    thread = threading.Thread(target=runtime.run, args=(stop,))
    thread.start()
    try:
        assert entered.wait(1)
        limit = time.monotonic() + 1
        while time.monotonic() < limit and runtime.snapshot().kind:
            threading.Event().wait(0.01)
        assert runtime.snapshot().kind == ""
        assert not release.is_set()
        assert controller.submit_output.call_count >= 2
    finally:
        stop.set()
        release.set()
        thread.join(2)
    assert not thread.is_alive()
