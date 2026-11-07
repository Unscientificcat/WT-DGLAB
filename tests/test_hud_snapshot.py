"""HUD 完整快照及跨局 ID 复用回归。"""

import json
import logging
from pathlib import Path

import pytest

from src.event_detector import EventDetector
from src.game_reader import GameState
from test_event_detector import QueuedReader, active_state, make_configs


def recorded_frames():
    """读取保留时间、ID 和零宽字符的匿名现场样本。"""
    path = Path(__file__).parent / "fixtures" / "hud_id_reuse.json"
    return json.loads(path.read_text(encoding="utf-8"))["frames"]


def hud(record_id=19, event_time=4, message="玩家击毁了 IT-1"):
    """生成可覆盖的 HUD 记录。"""
    return {"id": record_id, "time": event_time, "msg": message}


def test_real_recording_detects_four_events_once(caplog):
    """旧 ID 19 更新时间后仍识别，持续返回完整历史不会重复触发。"""
    frames = recorded_frames()
    responses = []
    for frame in frames:
        responses.extend([(True, frame["damage"])] * 3)
    reader = QueuedReader(responses)
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    with caplog.at_level(logging.INFO, logger="EventDetector"):
        results = [detector.poll(active_state(), "tank", aircraft, tank)
                   for _ in responses]
    assert [i for i, result in enumerate(results) if result] == [3, 6, 9, 12]
    assert all(result["kind"] == "kill" for result in results if result)
    assert detector.last_dmg_id == 21
    assert reader.last_dmg_ids == [0] * len(responses)
    assert "同 ID 更新：ID=19；time=4 → 2" in caplog.text
    assert "HUD 匹配结果：ID=19；time=2" in caplog.text
    assert caplog.text.count("HUD 历史基线已建立") == 1
    assert caplog.text.count("HUD 记录") == 4


@pytest.mark.parametrize("mode,vehicle", [
    ("tank", "tank"), ("aircraft", "aircraft"), ("tank", "aircraft"),
])
@pytest.mark.parametrize("changed,kind", [
    (hud(event_time=2), "kill"),
    (hud(message="玩家击毁了 T-62"), "kill"),
    (hud(message="敌人击毁了玩家"), "death"),
    (hud(record_id=3), "kill"),
])
def test_changed_record_uses_existing_mode_and_classifier(mode, vehicle, changed, kind):
    """空战、陆战和 CAS 均接受低 ID、新时间或新文本。"""
    reader = QueuedReader([(True, [hud()]), (True, [changed]), (True, [changed])])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    state = active_state(vehicle)
    assert detector.poll(state, mode, aircraft, tank) == {}
    result = detector.poll(state, mode, aircraft, tank)
    assert result["kind"] == kind
    cfg = tank if mode == "tank" else aircraft
    assert result["ch_a"] == getattr(cfg, f"{kind}_ch_a")
    assert detector.poll(state, mode, aircraft, tank) == {}


@pytest.mark.parametrize("gap", [(False, []), (True, []), (True, [hud(21)])])
def test_gaps_do_not_forget_known_records(gap):
    """超时、空快照或记录消失之后，原记录恢复不能重放。"""
    reader = QueuedReader([
        (True, [hud(), hud(21)]), gap,
        (True, [hud(21), hud()]),
        (True, [hud(21), hud(event_time=2)]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    state = active_state()
    assert detector.poll(state, "tank", aircraft, tank) == {}
    assert detector.poll(state, "tank", aircraft, tank) == {}
    assert detector.poll(state, "tank", aircraft, tank) == {}
    assert detector.poll(state, "tank", aircraft, tank)["kind"] == "kill"


def test_menu_consumes_updates_but_first_live_change_survives(caplog):
    """菜单消费变化；新局不重建基线吞掉首杀，也不补发菜单事件。"""
    reader = QueuedReader([
        (True, [hud()]), (True, [hud(event_time=3)]),
        (True, [hud(event_time=3)]), (True, [hud(event_time=2)]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    with caplog.at_level(logging.INFO, logger="EventDetector"):
        assert detector.poll(GameState(), "tank", aircraft, tank) == {}
        assert detector.poll(GameState(), "tank", aircraft, tank) == {}
        assert detector.poll(active_state(), "tank", aircraft, tank) == {}
        assert detector.poll(active_state(), "tank", aircraft, tank)["kind"] == "kill"
    assert "无有效对局；ID/time=[(19, 3)]" in caplog.text
    assert caplog.text.count("HUD 历史基线已建立") == 1


@pytest.mark.parametrize("gate", ["cas", "kill", "nickname"])
def test_enabling_gate_does_not_replay_consumed_change(gate):
    """恢复 CAS、击杀开关或昵称不会重放已消费记录。"""
    reader = QueuedReader([(True, [hud()]), (True, [hud(event_time=2)]),
                           (True, [hud(event_time=2)]), (True, [hud(event_time=1)])])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    state = active_state("aircraft")
    detector.poll(state, "tank", aircraft, tank)
    tank.kill_enabled = gate != "kill"
    tank.player_name = "" if gate == "nickname" else "玩家"
    assert detector.poll(state, "tank", aircraft, tank, gate != "cas") == {}
    tank.kill_enabled, tank.player_name = True, "玩家"
    assert detector.poll(state, "tank", aircraft, tank) == {}
    assert detector.poll(state, "tank", aircraft, tank)["kind"] == "kill"


def test_cosmetic_changes_and_unrelated_fields_are_not_new_events():
    """零宽字符、Unicode、空白和辅助字段变化不能重复触发。"""
    original = hud(message="玩家 (M1A1) 击毁了 IT-1")
    cosmetic = hud(message="玩\u200b家 （Ｍ１Ａ１）  击\u200b毁了 IT-1")
    cosmetic.update(sender="变化", enemy=True)
    detector = EventDetector(QueuedReader([(True, [original]), (True, [cosmetic])]))
    aircraft, tank = make_configs()
    detector.poll(active_state(), "tank", aircraft, tank)
    assert detector.poll(active_state(), "tank", aircraft, tank) == {}


def test_batch_order_and_latest_fingerprint_are_preserved():
    """保持原有按 ID 处理顺序；指纹回到更早值仍是一条可观察变化。"""
    reader = QueuedReader([
        (True, [hud()]),
        (True, [hud(21, message="敌人击毁了玩家"), hud(event_time=2)]),
        (True, [hud(), hud(21, message="敌人击毁了玩家")]),
        (True, [hud(21, message="敌人击毁了玩家"), hud()]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    state = active_state()
    detector.poll(state, "tank", aircraft, tank)
    assert detector.poll(state, "tank", aircraft, tank)["kind"] == "death"
    assert detector.poll(state, "tank", aircraft, tank)["kind"] == "kill"
    assert detector.poll(state, "tank", aircraft, tank) == {}
