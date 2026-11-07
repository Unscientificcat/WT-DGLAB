"""维修、死亡与部件损伤生命周期：直接验证生产触发引擎。"""

import pytest

from src.trigger_engine import TriggerEngine
from runtime_support import config, state, event, observe


@pytest.mark.parametrize("kind", ["kill", "death", "hit", "repair"])
@pytest.mark.parametrize("normal", [0, 5])
def test_event_expiry_or_repair_end_restores_latest_mapping(kind, normal):
    cfg, engine = config(), TriggerEngine()
    cfg.tank.channel_a_max = cfg.tank.channel_b_max = normal
    s = state(is_repairing=kind == "repair")
    result = observe(engine, cfg, events=[event(kind)], snapshot=s)
    assert result.kind == kind
    result = observe(engine, cfg, 106)
    assert result.kind == ""
    assert result.a == normal
    assert result.b == normal


@pytest.mark.parametrize("interrupt", ["kill", "death"])
@pytest.mark.parametrize("still_repairing", [True, False])
def test_repair_resume_depends_on_current_condition_and_death(interrupt, still_repairing):
    cfg, engine = config(), TriggerEngine()
    observe(engine, cfg, snapshot=state(is_repairing=True))
    observe(engine, cfg, 101, [event(interrupt, 101)], state(101, is_repairing=True))
    result = observe(engine, cfg, 106, snapshot=state(106, is_repairing=still_repairing))
    assert result.kind == ("repair" if still_repairing and interrupt == "kill" else "")


@pytest.mark.parametrize("exit_status", ["inactive", "unknown"])
def test_invalid_mission_immediately_stops_repair_output(exit_status):
    cfg, engine = config(), TriggerEngine()
    observe(engine, cfg, snapshot=state(is_repairing=True))
    result = observe(engine, cfg, 100.2, snapshot=state(100.2, mission=exit_status))
    assert result.intent.a.strength == 0


def test_disable_repair_during_playback_stops_before_output():
    cfg, engine = config(), TriggerEngine()
    observe(engine, cfg, snapshot=state(is_repairing=True))
    cfg.tank_events.repair_enabled = False
    result = engine.tick(cfg, ("controller", 1), True, 100.1)
    assert result.kind == ""
    assert result.intent.a.strength == 5


@pytest.mark.parametrize("higher", ["kill", "death", "repair"])
def test_part_damage_cannot_interrupt_higher_event(higher):
    cfg, engine = config(), TriggerEngine()
    observe(engine, cfg, events=[event(higher)])
    result = observe(engine, cfg, 100.2, [event("hit", 100.2)])
    assert result.kind == higher if higher != "repair" else result.kind == "hit"


def test_repaired_part_can_trigger_again_and_same_frame_parts_coalesce():
    cfg, engine = config(), TriggerEngine()
    observe(engine, cfg)
    first = state(101, damaged_parts=frozenset({"履带", "炮闩"}))
    assert observe(engine, cfg, 101, snapshot=first).kind == "hit"
    assert len([j for j in engine.journal if j[1] == "hit"]) == 1
    observe(engine, cfg, 102)
    observe(engine, cfg, 103)
    assert observe(engine, cfg, 104, snapshot=state(104, damaged_parts=frozenset({"履带"}))).kind == "hit"
