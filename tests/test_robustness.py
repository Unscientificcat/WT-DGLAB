"""配置和遥测异常输入的回归测试。"""

import json
import os

from src.config_manager import ConfigManager
from src.game_reader import GameReader


def test_malformed_config_falls_back_to_defaults(tmp_path):
    """错误类型的配置字段不应阻止程序启动。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"app": {"ws_port": "bad"}}),
                    encoding="utf-8")

    config = ConfigManager(str(path)).load()

    assert config.app.ws_port == 8765


def test_non_finite_config_falls_back_to_defaults(tmp_path):
    """NaN 等非有限数值不应进入映射逻辑。"""
    path = tmp_path / "config.json"
    path.write_text('{"aircraft":{"gforce_min":NaN}}', encoding="utf-8")

    config = ConfigManager(str(path)).load()

    assert config.aircraft.gforce_min == 1.0


def test_malformed_tank_telemetry_uses_safe_defaults():
    """坦克接口字段异常时只回退异常字段，不丢弃整个状态。"""
    data = GameReader()._parse_tank({}, {
        "valid": True,
        "speed": "bad",
        "is_repairing": None,
        "repair_time": "nan",
    })

    assert data.valid
    assert data.speed_kmh == 0.0
    assert not data.is_repairing
    assert data.repair_time == 0.0


def test_invalid_field_keeps_other_fields_and_backs_up(tmp_path):
    """单字段非法只回退该字段，其余设置保留，并生成原文件备份。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "app": {"ws_port": "bad", "refresh_interval_ms": 300},
        "aircraft": {"gforce_min": 2.0, "gforce_max": 8.0,
                     "channel_a_max": 999, "channel_b_max": 40},
    }), encoding="utf-8")

    manager = ConfigManager(str(path))
    config = manager.load()

    assert config.app.ws_port == 8765
    assert config.app.refresh_interval_ms == 300
    assert config.aircraft.gforce_min == 2.0
    assert config.aircraft.gforce_max == 8.0
    assert config.aircraft.channel_a_max == 0
    assert config.aircraft.channel_b_max == 40
    assert len(manager.load_issues) == 2
    assert manager.invalid_backup_path.startswith(str(path) + ".invalid-")
    with open(manager.invalid_backup_path, encoding="utf-8") as file:
        assert json.load(file)["aircraft"]["channel_a_max"] == 999


def test_reversed_range_resets_both_fields(tmp_path):
    """最小值大于最大值时成对回退默认值。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "tank": {"speed_min": 80.0, "speed_max": 20.0},
    }), encoding="utf-8")

    config = ConfigManager(str(path)).load()

    assert config.tank.speed_min == 0.0
    assert config.tank.speed_max == 60.0


def test_unparseable_config_backs_up_and_resets(tmp_path):
    """JSON 无法解析时整体回退默认值，并备份原文件。"""
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")

    manager = ConfigManager(str(path))
    config = manager.load()

    assert config.app.ws_port == 8765
    assert manager.load_issues
    assert os.path.isfile(manager.invalid_backup_path)


def test_valid_config_has_no_issues_or_backup(tmp_path):
    """合法配置不产生修正说明，也不生成备份。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"app": {"ws_port": 9000}}),
                    encoding="utf-8")

    manager = ConfigManager(str(path))
    manager.load()

    assert manager.load_issues == []
    assert manager.invalid_backup_path == ""
    assert list(tmp_path.glob("config.json.invalid-*")) == []


def _strength_app(bound=True):
    """构造只含 _send_strength 所需属性的 App 实例。"""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from main import App

    app = App.__new__(App)
    app.coyote = SimpleNamespace(
        status=SimpleNamespace(bound=bound, server_running=True),
        set_strength_a=Mock(), set_strength_b=Mock(),
    )
    return app


def test_send_strength_deduplicates_within_keepalive(monkeypatch):
    """B3：强度不变时在保活间隔内不重复下发。"""
    import main

    clock = [100.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    app = _strength_app()
    for _ in range(5):
        app._send_strength(40, 20)
        clock[0] += 0.1
    assert app.coyote.set_strength_a.call_count == 1

    clock[0] = 100.6
    app._send_strength(40, 20)
    assert app.coyote.set_strength_a.call_count == 2


def test_send_strength_sends_immediately_on_change(monkeypatch):
    """B3：强度变化时立即下发。"""
    import main

    monkeypatch.setattr(main.time, "monotonic", lambda: 50.0)
    app = _strength_app()
    app._send_strength(40, 20)
    app._send_strength(41, 20)
    app.coyote.set_strength_a.assert_called_with(41)
    assert app.coyote.set_strength_b.call_count == 2


def test_send_strength_resends_after_rebind_or_new_controller(monkeypatch):
    """B3：绑定状态或控制器对象变化后第一帧必定下发。"""
    import main
    from types import SimpleNamespace
    from unittest.mock import Mock

    monkeypatch.setattr(main.time, "monotonic", lambda: 10.0)
    app = _strength_app()
    app._send_strength(30, 30)
    app.coyote.status.bound = False
    app._send_strength(30, 30)
    app.coyote.status.bound = True
    app._send_strength(30, 30)
    assert app.coyote.set_strength_a.call_count == 3

    old = app.coyote
    app.coyote = SimpleNamespace(
        status=old.status, set_strength_a=Mock(), set_strength_b=Mock())
    app._send_strength(30, 30)
    app.coyote.set_strength_a.assert_called_once_with(30)


def test_parse_part_value_uses_raw_field_for_state_suffix():
    """_state 后缀按原始字段名判断：非 0 即损毁，显示名单独传入（代码审查修复 D3）。"""
    reader = GameReader()
    part = reader._parse_part_value("engine_state", 1, "引擎")
    assert part.name == "引擎"
    assert part.is_destroyed and part.health == 0.0
    intact = reader._parse_part_value("engine_state", 0, "引擎")
    assert not intact.is_destroyed and intact.health == 100.0
    # 旧实现把 "engine state" 当显示名判断，_state 分支永远走不到，1 被当作比例 100%
    parts = reader._extract_damage_from_state({"engine_state_hp": 0.5, "track_hp_state": 2})
    by_field = {p.name: p for p in parts}
    assert by_field["track hp state"].is_destroyed
    assert by_field["engine state hp"].health == 50.0
