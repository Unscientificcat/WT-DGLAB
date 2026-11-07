"""离线预览、跨会话撤销、CAS 配置与真实协议集成。"""

from dataclasses import replace
import time

import pytest

from src.game_runtime import GameRuntime
from src.trigger_engine import TriggerEngine
from runtime_support import config, state, event, observe
from test_connection_refactor import connected
from test_output_stop_barrier import drain


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("vehicle,scene", [("tank", "tank"), ("aircraft", "tank"), ("aircraft", "aircraft")])
@pytest.mark.parametrize("kind", ["kill", "death"])
@pytest.mark.asyncio
async def test_preview_target_and_production_protocol_have_independent_gates(protocol, bound, vehicle, scene, kind):
    controller, peer = connected(protocol)
    controller.status.bound = bound
    controller._publish_snapshot()
    cfg = config()
    cfg.app.mode = scene
    runtime = GameRuntime(None, controller, cfg)
    now = time.monotonic()
    s = state(now, vehicle)
    s.event_session = (id(controller), controller.snapshot().session)
    s.event_output_bound = bound
    e = event(kind, now, vehicle, scene, bound, s.event_session)
    runtime.engine.observe(s, [e], cfg, now)
    result = runtime.advance(now)
    await drain(controller)
    expected = getattr(cfg.tank_events if scene == "tank" else cfg.events, f"{kind}_ch_a")
    assert result.a == expected
    assert peer.strength == ([expected, 12] if bound else [0, 0])
    assert result.label


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("kind", ["kill", "death", "repair", "hit"])
@pytest.mark.asyncio
async def test_connect_mid_preview_never_replays_old_event(protocol, kind):
    controller, peer = connected(protocol)
    controller.status.bound = False
    controller._publish_snapshot()
    cfg = config()
    runtime = GameRuntime(None, controller, cfg)
    now = time.monotonic()
    s = state(now, is_repairing=kind == "repair")
    s.event_session = (id(controller), controller.snapshot().session)
    s.event_output_bound = False
    runtime.engine.observe(s, [event(kind, now, bound=False, session=s.event_session)], cfg, now)
    runtime.advance(now)
    controller.status.bound = True
    controller._publish_snapshot()
    result = runtime.advance(now + 0.1)
    await drain(controller)
    assert result.kind == kind
    assert peer.strength == [0, 0]
    s = state(now + 6)
    s.event_session = (id(controller), controller.snapshot().session)
    runtime.engine.observe(s, [], cfg, now + 6)
    runtime.advance(now + 6)
    await drain(controller)
    assert peer.strength == [5, 3]


@pytest.mark.parametrize("kind", ["kill", "death", "repair", "hit"])
def test_disconnect_reconnect_preserves_preview_but_revokes_qualification(kind):
    engine, cfg = TriggerEngine(), config()
    s = state(is_repairing=kind == "repair")
    result = observe(engine, cfg, events=[event(kind)], snapshot=s)
    assert result.output_allowed
    engine.tick(cfg, ("controller", 1), False, 100.1)
    result = engine.tick(cfg, ("controller", 1), True, 100.2)
    assert result.kind == kind
    assert not result.output_allowed


@pytest.mark.parametrize("kind", ["kill", "death", "repair", "hit"])
def test_protocol_or_device_switch_does_not_authorize_old_event(kind):
    engine, cfg = TriggerEngine(), config()
    observe(engine, cfg, events=[event(kind)], snapshot=state(is_repairing=kind == "repair"))
    result = engine.tick(cfg, ("replacement", 1), True, 100.2)
    assert result.kind == kind
    assert result.intent.a.strength == 0


def test_queue_wait_cannot_extend_identification_deadline():
    cfg, engine = config(), TriggerEngine()
    e = event(now=100)
    result = observe(engine, cfg, 104.8, [e])
    assert result.remaining == pytest.approx(0.2)
    assert observe(engine, cfg, 105).kind == ""


def test_expired_before_consumption_is_never_replayed():
    cfg, engine = config(), TriggerEngine()
    result = observe(engine, cfg, 106, [event(now=100)])
    assert result.kind == ""
    assert any("过期" in item[2] for item in engine.journal)
