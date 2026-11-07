"""陆战部件损伤短脉冲回归测试：损伤边沿检测、冷却、优先级与配置校验。

说明：原"被命中"基于 hudmsg `*` 前缀判定，实机验证 8111 无普通命中
记录后（阶段11-2），信号源改为 /indicators 部件/乘员损伤边沿。
"""

import json
import os
import logging
from types import SimpleNamespace

import pytest

from src.config_manager import ConfigManager, TankEventSettings
from src.event_detector import EventDetector
from src.game_reader import GameState, GameReader, TankData

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tank_state(damaged=()):
    """创建有效战局中的坦克遥测，damaged 为已损毁部件名集合。"""
    return GameState(
        connected=True, link_ok=True, vehicle_type="tank",
        tank=TankData(valid=True, speed_kmh=30,
                      damaged_parts=frozenset(damaged)),
    )


# ============================================================
# 数据解析
# ============================================================

def test_parse_tank_extracts_damaged_parts():
    """_parse_tank 从 /indicators 提取损毁部件与阵亡乘员集合。"""
    reader = GameReader()
    indicators = {
        "valid": True, "type": "t-34", "speed": 12.0,
        "tracks_state": 1, "engine_state": 2, "gun_state": 0,
        "gunner_state": 1, "driver_state": 0,
        "crew_total": 4, "crew_current": 4,
    }
    data = reader._parse_tank({}, indicators)
    assert data.damaged_parts == frozenset({"履带", "引擎", "炮手"})
    assert data.crew_alive is True
    assert data.valid is True


def test_parse_tank_without_damage_fields():
    """字段缺失时部件集合为空，不影响其他解析。"""
    reader = GameReader()
    data = reader._parse_tank({}, {"valid": True, "speed": 5.0})
    assert data.damaged_parts == frozenset()
    assert data.speed_kmh == pytest.approx(5.0)


# ============================================================
# HUD 诊断日志（原 hudmsg 命中分支已移除）
# ============================================================

class _ReaderStub:
    def __init__(self, responses):
        self.responses = list(responses)

    def fetch_hudmsg_with_status(self, last_dmg_id):
        return self.responses.pop(0)


def test_unclassified_hud_message_logged_but_not_fired(caplog):
    """含玩家名但未分类的损伤消息只记诊断日志，不触发任何事件。"""
    detector = EventDetector(_ReaderStub([
        (True, [{"id": 101, "msg": "enemy1 has hit *玩家 (T-34)"}]),
        (True, []),
    ]))
    config = TankEventSettings(player_name="玩家", kill_enabled=True)
    detector._cursor_ready = True
    with caplog.at_level(logging.INFO, logger="EventDetector"):
        event = detector.poll(tank_state(), "tank", SimpleNamespace(),
                              config, cas_enabled=True)
    assert event == {}
    assert any("HUD 未分类损伤消息" in record.message
               for record in caplog.records)


def test_classified_kill_still_detected():
    """移除命中分支后击杀/被击毁词条检测不受影响。"""
    detector = EventDetector(_ReaderStub([
        (True, [{"id": 101, "msg": "玩家 (T-34) destroyed enemy1"}]),
        (True, []),
    ]))
    config = TankEventSettings(player_name="玩家", kill_enabled=True,
                               kill_ch_a=21)
    detector._cursor_ready = True
    event = detector.poll(tank_state(), "tank", SimpleNamespace(),
                          config, cas_enabled=True)
    assert event["kind"] == "kill"
    assert event["ch_a"] == 21


# ============================================================
# 配置读写与校验
# ============================================================

def write_config(tmp_path, data):
    """写入临时配置文件并返回 ConfigManager。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ConfigManager(str(path))


def test_hit_config_defaults():
    """部件损伤短脉冲默认关闭、时长 0.5 秒、冷却 2 秒。"""
    config = TankEventSettings()
    assert config.hit_enabled is False
    assert config.hit_duration == pytest.approx(0.5)
    assert config.hit_cooldown == pytest.approx(2.0)
    assert config.hit_ch_a == 0
    assert config.hit_wf_a == "恒定"


def test_hit_config_round_trip(tmp_path):
    """部件损伤配置从文件加载后字段保留。"""
    manager = write_config(tmp_path, {
        "tank_events": {"hit_enabled": True, "hit_ch_a": 40,
                        "hit_duration": 1.5, "hit_cooldown": 5.0},
    })
    config = manager.load().tank_events
    assert config.hit_enabled is True
    assert config.hit_ch_a == 40
    assert config.hit_duration == pytest.approx(1.5)
    assert config.hit_cooldown == pytest.approx(5.0)


def test_hit_config_invalid_duration_resets_field(tmp_path):
    """时长越界时只回退该字段，其余字段保留并备份原文件。"""
    manager = write_config(tmp_path, {
        "tank_events": {"hit_enabled": True, "hit_duration": 0.0},
    })
    config = manager.load().tank_events
    assert config.hit_enabled is True
    assert config.hit_duration == pytest.approx(0.5)
    assert manager.invalid_backup_path
    assert os.path.isfile(manager.invalid_backup_path)


def test_hit_config_invalid_cooldown_resets_field(tmp_path):
    """冷却越界（含负值）时只回退该字段。"""
    manager = write_config(tmp_path, {
        "tank_events": {"hit_cooldown": -1.0},
    })
    config = manager.load().tank_events
    assert config.hit_cooldown == pytest.approx(2.0)


def test_default_template_contains_hit_keys():
    """config.default.json 的 tank_events 段必须包含部件损伤配置键。"""
    with open(os.path.join(ROOT, "config.default.json"),
              encoding="utf-8") as file:
        data = json.load(file)
    hit_keys = {
        "hit_enabled": False, "hit_ch_a": 0, "hit_ch_b": 0,
        "hit_duration": 0.5, "hit_wf_a": "恒定", "hit_wf_b": "恒定",
        "hit_cooldown": 2.0, "hit_random_a": False, "hit_random_b": False,
    }
    for key, value in hit_keys.items():
        assert data["tank_events"][key] == value


