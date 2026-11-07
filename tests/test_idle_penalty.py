"""陆战静止惩罚回归测试：状态机、豁免、优先级与配置校验。"""

import os
import json

import pytest

from src.config_manager import ConfigManager, TankSettings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 配置读写与校验
# ============================================================

def write_config(tmp_path, data):
    """写入临时配置文件并返回 ConfigManager。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ConfigManager(str(path))


def test_idle_config_defaults():
    """静止惩罚默认关闭、超时 10 秒、阈值 2 km/h。"""
    config = TankSettings()
    assert config.idle_enabled is False
    assert config.idle_timeout_s == pytest.approx(10.0)
    assert config.idle_speed_max == pytest.approx(2.0)
    assert config.idle_ch_a == 0
    assert config.idle_wf_a == "恒定"


def test_idle_config_round_trip(tmp_path):
    """静止惩罚配置从文件加载后字段保留。"""
    manager = write_config(tmp_path, {
        "tank": {"idle_enabled": True, "idle_timeout_s": 20.0,
                 "idle_speed_max": 5.0, "idle_ch_a": 88,
                 "idle_wf_b": "惩罚B.pulse"},
    })
    tank = manager.load().tank
    assert tank.idle_enabled is True
    assert tank.idle_timeout_s == pytest.approx(20.0)
    assert tank.idle_speed_max == pytest.approx(5.0)
    assert tank.idle_ch_a == 88
    assert tank.idle_wf_b == "惩罚B.pulse"


def test_idle_config_invalid_timeout_resets_field(tmp_path):
    """超时秒数越界时只回退该字段，开关保留。"""
    manager = write_config(tmp_path, {
        "tank": {"idle_enabled": True, "idle_timeout_s": 0.5},
    })
    tank = manager.load().tank
    assert tank.idle_enabled is True
    assert tank.idle_timeout_s == pytest.approx(10.0)


def test_idle_config_invalid_speed_threshold_resets_field(tmp_path):
    """静止阈值越界时只回退该字段。"""
    manager = write_config(tmp_path, {
        "tank": {"idle_speed_max": 80.0},
    })
    tank = manager.load().tank
    assert tank.idle_speed_max == pytest.approx(2.0)


def test_default_template_contains_idle_keys():
    """config.default.json 的 tank 段必须包含静止惩罚键。"""
    with open(os.path.join(ROOT, "config.default.json"),
              encoding="utf-8") as file:
        data = json.load(file)
    idle_keys = {
        "idle_enabled": False, "idle_timeout_s": 10.0,
        "idle_speed_max": 2.0, "idle_ch_a": 0, "idle_ch_b": 0,
        "idle_wf_a": "恒定", "idle_wf_b": "恒定",
        "idle_random_a": False, "idle_random_b": False,
    }
    for key, value in idle_keys.items():
        assert data["tank"][key] == value


def test_idle_random_config_round_trip(tmp_path):
    """静止惩罚随机波形开关从文件加载后字段保留。"""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "tank": {"idle_random_a": True, "idle_random_b": True},
    }, ensure_ascii=False), encoding="utf-8")
    tank = ConfigManager(str(path)).load().tank
    assert tank.idle_random_a is True
    assert tank.idle_random_b is True


def test_idle_wave_scene_registered():
    """波形设置对话框陆战场景必须包含静止惩罚（idle_wf_* 字段）。"""
    from src.gui.main_window import WaveformSettingsDialog

    tank_scenes = WaveformSettingsDialog.SCENES["tank"]
    assert ("静止惩罚", "tank", "idle") in tank_scenes


# ============================================================
# GUI 控件双向绑定
# ============================================================

def test_idle_controls_gui_round_trip(tmp_path):
    """设置面板静止惩罚控件必须同时接入加载与保存。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import Mock as _Mock

    from PySide6.QtWidgets import QApplication

    from src.gui.main_window import MainWindow

    _app = QApplication.instance() or QApplication([])
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager, on_mode_changed=_Mock())
    panel = window.settings_panel
    try:
        panel.tank_idle_enabled.setChecked(True)
        panel.tank_idle_speed_max.setValue(3.0)
        panel.tank_idle_timeout.setValue(15.0)
        panel.tank_idle_ch_a.setValue(45)
        panel.tank_idle_ch_b.setValue(25)
        assert panel.save_settings(show_feedback=False, notify=False)
        tank = manager.config.tank
        assert tank.idle_enabled is True
        assert tank.idle_speed_max == pytest.approx(3.0)
        assert tank.idle_timeout_s == pytest.approx(15.0)
        assert tank.idle_ch_a == 45
        assert tank.idle_ch_b == 25

        panel.tank_idle_enabled.setChecked(False)
        panel.tank_idle_timeout.setValue(5.0)
        panel._load_config()
        assert panel.tank_idle_enabled.isChecked()
        assert panel.tank_idle_timeout.value() == pytest.approx(15.0)
    finally:
        window._exit_requested = True
        window.close()
