"""陆战部件损伤短脉冲回归测试：损伤边沿检测、冷却、优先级与配置校验。

说明：原"被命中"基于 hudmsg `*` 前缀判定，实机验证 8111 无普通命中
记录后（阶段11-2），信号源改为 /indicators 部件/乘员损伤边沿。
"""

import json
import os
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as main_module
from main import App
from src.config_manager import Config, ConfigManager, TankEventSettings
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


@pytest.fixture
def app():
    """保留真实边沿检测、事件守卫与映射逻辑，仅替换界面及设备边界。"""
    instance = App.__new__(App)
    cfg = Config()
    cfg.tank.enabled = False
    cfg.cas.enabled = False
    cfg.tank_events.hit_enabled = True
    cfg.tank_events.hit_ch_a = 31
    cfg.tank_events.hit_ch_b = 32
    cfg.tank_events.hit_duration = 0.5
    cfg.tank_events.hit_wf_a = "命中A"
    cfg.tank_events.hit_wf_b = "命中B"
    cfg.tank_events.hit_cooldown = 2.0
    instance.config_mgr = SimpleNamespace(config=cfg)
    instance._last_state = tank_state()
    instance._event_kind = ""
    instance._event_mode = ""
    instance._event_ch_a = 0
    instance._event_ch_b = 0
    instance._event_remaining = 0
    instance._repair_blocked_until_idle = False
    instance._repair_death_state = None
    instance._idle_active = False
    instance._idle_start_time = None
    instance._idle_label_shown = False
    instance._idle_death_blocked = False
    instance._last_damaged_parts = frozenset()
    instance._last_hit_time = 0.0
    instance._wt_connected = True
    instance._wt_fail_count = 0
    instance._overlay_tick = 0
    instance._running = False
    instance._event_queue = __import__("queue").Queue()
    instance._data_queue = __import__("queue").Queue()
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


@pytest.fixture
def clock(monkeypatch):
    """可控单调时钟。"""
    now = [1000.0]
    monkeypatch.setattr(main_module.time, "monotonic", lambda: now[0])
    return now


def tick(app, state=None, events=()):
    """执行完整 UI 刷新，并确保未在异常捕获中提前退出。"""
    if state is not None:
        app._data_queue.put(state)
    for item in events:
        app._event_queue.put(item)
    app._update_channel_wave_names.reset_mock()
    app._ui_tick()
    app._update_channel_wave_names.assert_called_once()


def hit_event():
    """构造部件损伤事件字典。"""
    return dict(kind="hit", mode="tank", ch_a=31, ch_b=32, duration=0.5,
                wf_a="命中A", wf_b="命中B")


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
# 边沿检测与触发
# ============================================================

def test_new_part_damage_triggers_hit(app, clock):
    """新部件被打坏触发部件损伤短脉冲，字段来自 hit_* 配置。"""
    tick(app, tank_state({"履带"}))
    assert app._event_kind == "hit"
    assert app._event_ch_a == 31
    # 应用当轮即开始倒计时（_ui_tick 固有行为），剩余 0.4s
    assert app._event_remaining == pytest.approx(0.4)
    app.coyote.set_waveform_a.assert_called_with("命中A", False, 30, 50)
    app.window.dashboard.show_event.assert_called_with("🎯 被命中! (0.4s)")
    app._send_strength.assert_called_with(31, 32)


def test_no_new_damage_does_not_trigger(app, clock):
    """损毁集合无变化（含初始基线一致）时不触发。"""
    app._last_damaged_parts = frozenset({"履带"})
    tick(app, tank_state({"履带"}))
    assert app._event_kind == ""


def test_multi_part_same_frame_triggers_once(app, clock):
    """一发炮弹同时打坏多个部件只触发一次短脉冲。"""
    tick(app, tank_state({"履带", "炮管"}))
    assert app._event_kind == "hit"
    assert app._last_damaged_parts == frozenset({"履带", "炮管"})


def test_cooldown_suppresses_rapid_damage(app, clock):
    """冷却期内的新部件损伤被抑制，冷却结束后恢复触发。"""
    tick(app, tank_state({"履带"}))                     # t=1000 触发
    app._event_kind = ""
    app._event_remaining = 0
    clock[0] += 1.0
    tick(app, tank_state({"履带", "引擎"}))             # 冷却内 → 抑制
    assert app._event_kind == ""
    assert app._last_damaged_parts == frozenset({"履带", "引擎"})
    clock[0] += 2.0
    tick(app, tank_state({"履带", "引擎", "炮管"}))     # 冷却结束 → 触发
    assert app._event_kind == "hit"


def test_hit_disabled_no_trigger(app, clock):
    """功能关闭时不触发。"""
    app.config_mgr.config.tank_events.hit_enabled = False
    tick(app, tank_state({"履带"}))
    assert app._event_kind == ""


def test_repaired_part_can_retrigger(app, clock):
    """部件修复后再次被打坏会再次触发（边沿语义）。"""
    tick(app, tank_state({"履带"}))
    app._event_remaining = 0.05            # 让首次短脉冲到期
    clock[0] += 5
    tick(app, tank_state())                # 维修修复，基线清空不触发
    assert app._event_kind == ""
    clock[0] += 1
    tick(app, tank_state({"履带"}))        # 再次被打坏 → 再次触发
    assert app._event_kind == "hit"


def test_cas_frames_do_not_trigger(app, clock):
    """上飞机（CAS）期间不检测坦克部件损伤。"""
    from src.game_reader import AircraftData
    app._last_damaged_parts = frozenset({"履带"})
    cas_state = GameState(connected=True, link_ok=True,
                          vehicle_type="aircraft",
                          aircraft=AircraftData(valid=True))
    tick(app, cas_state)
    assert app._event_kind == ""


# ============================================================
# 主控制器优先级
# ============================================================

def test_hit_skipped_during_kill_event(app):
    """击杀事件进行中部件损伤不得抢占输出。"""
    app._apply_event(dict(kind="kill", mode="tank", ch_a=81, ch_b=42,
                          duration=5, wf_a="击杀A", wf_b="击杀B"))
    app._apply_event(hit_event())
    assert app._event_kind == "kill"
    assert app._event_ch_a == 81


def test_hit_skipped_during_repair_and_after_death(app):
    """维修事件进行中及死亡等待重生期间，部件损伤被忽略。"""
    app._apply_event(dict(kind="repair", mode="tank", ch_a=25, ch_b=26,
                          duration=60, wf_a="维修A", wf_b="维修B"))
    app._apply_event(hit_event())
    assert app._event_kind == "repair"

    app._event_kind = ""
    app._event_remaining = 0
    app._repair_blocked_until_idle = True
    app._apply_event(hit_event())
    assert app._event_kind == ""


def test_hit_can_follow_finished_kill(app):
    """击杀事件结束后部件损伤可正常触发。"""
    app._apply_event(dict(kind="kill", mode="tank", ch_a=81, ch_b=42,
                          duration=5, wf_a="击杀A", wf_b="击杀B"))
    app._event_remaining = 0
    app._event_kind = ""
    app._apply_event(hit_event())
    assert app._event_kind == "hit"


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


def test_event_countdown_uses_real_elapsed_time(app, clock):
    """GUI 卡顿 2 秒后，事件倒计时按实际耗时扣减，不按固定 0.1 秒（D2）。"""
    tick(app, tank_state({"履带"}))
    assert app._event_kind == "hit"
    clock[0] += 2.0
    tick(app, tank_state({"履带"}))
    assert app._event_kind == ""
    assert app._event_remaining == 0.0


def test_damage_baseline_resets_after_leaving_ground(app, clock):
    """离开陆战地面（CAS）后回来，已损坏部件只建立基线不误触发（代码审查修复 D4）。"""
    from src.game_reader import AircraftData
    app._last_damaged_parts = frozenset()
    cas_state = GameState(connected=True, link_ok=True,
                          vehicle_type="aircraft",
                          aircraft=AircraftData(valid=True))
    tick(app, cas_state)
    assert app._last_damaged_parts is None
    tick(app, tank_state({"履带"}))        # 回到坦克时履带仍坏 → 仅建立基线
    assert app._event_kind == ""
    assert app._last_damaged_parts == frozenset({"履带"})
    tick(app, tank_state({"履带", "引擎"}))  # 之后的新损伤正常触发
    assert app._event_kind == "hit"


def test_damage_baseline_resets_on_disconnect(app, clock):
    """断线后旧对局的基线作废，新对局首帧不触发、后续边沿不漏判。"""
    app._last_damaged_parts = frozenset({"履带"})
    tick(app, GameState(connected=False))
    assert app._last_damaged_parts is None
    tick(app, tank_state())                # 新对局完好 → 建立空基线
    tick(app, tank_state({"履带"}))        # 旧基线含履带时会漏判，现在触发
    assert app._event_kind == "hit"
