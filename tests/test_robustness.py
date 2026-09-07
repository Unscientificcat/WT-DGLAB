"""配置和遥测异常输入的回归测试。"""

import json

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
