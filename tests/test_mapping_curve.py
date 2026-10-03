"""常态触发非线性曲线回归测试：映射引擎曲线变换 + 配置读写校验。"""

import json
import math
import os

import pytest

from src.config_manager import ConfigManager
from src.mapping_engine import MappingEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 曲线函数性质
# ============================================================

@pytest.mark.parametrize("curve", ["linear", "exp", "log"])
def test_curve_endpoints_and_bounds(curve):
    """三种曲线均满足 f(0)=0、f(1)=1，且输出始终在 [0,1] 内。"""
    apply_curve = MappingEngine._apply_curve
    assert apply_curve(0.0, curve, 2.0) == 0.0
    assert apply_curve(1.0, curve, 2.0) == 1.0
    samples = [i / 20 for i in range(21)]
    outputs = [apply_curve(t, curve, 2.0) for t in samples]
    assert all(0.0 <= value <= 1.0 for value in outputs)


@pytest.mark.parametrize("curve", ["linear", "exp", "log"])
def test_curve_monotonic(curve):
    """三种曲线在 [0,1] 上单调不减。"""
    apply_curve = MappingEngine._apply_curve
    previous = -0.1
    for i in range(21):
        value = apply_curve(i / 20, curve, 3.0)
        assert value >= previous
        previous = value


def test_linear_curve_is_identity():
    """线性曲线保持归一化值不变。"""
    assert MappingEngine._apply_curve(0.25, "linear", 2.0) == pytest.approx(0.25)


def test_exp_curve_compresses_low_values():
    """指数曲线（后段更猛）：中点输出显著低于 0.5，且符合公式。"""
    expected = (math.exp(2.0 * 0.5) - 1.0) / (math.exp(2.0) - 1.0)
    assert MappingEngine._apply_curve(0.5, "exp", 2.0) == pytest.approx(
        expected)
    assert expected < 0.5


def test_log_curve_amplifies_low_values():
    """对数曲线（前段更猛）：中点输出显著高于 0.5，且符合公式。"""
    expected = math.log1p(2.0 * 0.5) / math.log1p(2.0)
    assert MappingEngine._apply_curve(0.5, "log", 2.0) == pytest.approx(
        expected)
    assert expected > 0.5


def test_exp_steepness_raises_high_end():
    """陡度越大，指数曲线低段被压得越低、高段越陡。"""
    low = MappingEngine._apply_curve(0.5, "exp", 1.5)
    high = MappingEngine._apply_curve(0.5, "exp", 4.0)
    assert high < low


def test_log_steepness_raises_low_end():
    """陡度越大，对数曲线低段抬得越高。"""
    low = MappingEngine._apply_curve(0.5, "log", 1.5)
    high = MappingEngine._apply_curve(0.5, "log", 4.0)
    assert high > low


def test_unknown_curve_falls_back_to_linear():
    """未知曲线名按线性处理，不抛异常。"""
    assert MappingEngine._apply_curve(0.4, "step", 2.0) == pytest.approx(0.4)
    assert MappingEngine._apply_curve(0.4, "", 2.0) == pytest.approx(0.4)


def test_invalid_steepness_falls_back_to_linear():
    """陡度非法（非正/非有限）时按线性处理，不抛异常。"""
    assert MappingEngine._apply_curve(0.4, "exp", 0) == pytest.approx(0.4)
    assert MappingEngine._apply_curve(0.4, "exp", -1.0) == pytest.approx(0.4)
    assert MappingEngine._apply_curve(0.4, "log", float("nan")) == \
        pytest.approx(0.4)
    assert MappingEngine._apply_curve(0.4, "log", float("inf")) == \
        pytest.approx(0.4)


# ============================================================
# 映射入口传参
# ============================================================

def test_map_aircraft_exp_lowers_mid_intensity():
    """空战映射：指数曲线下中段过载强度低于线性。"""
    linear = MappingEngine.map_aircraft(5.5, 1.0, 10.0, 200, 200)
    exponential = MappingEngine.map_aircraft(
        5.5, 1.0, 10.0, 200, 200, curve="exp", steepness=2.0)
    assert linear == (100, 100)
    assert exponential[0] < linear[0]
    assert exponential[1] == exponential[0]


def test_map_tank_log_raises_mid_intensity():
    """陆战映射：对数曲线下中段速度强度高于线性。"""
    linear = MappingEngine.map_tank(30.0, 0.0, 60.0, 200, 200)
    logarithmic = MappingEngine.map_tank(
        30.0, 0.0, 60.0, 200, 200, curve="log", steepness=2.0)
    assert linear == (100, 100)
    assert logarithmic[0] > linear[0]
    assert logarithmic[1] == logarithmic[0]


def test_map_aircraft_curve_keeps_clamping():
    """曲线不影响边界钳制：下限以下为 0，上限以上取通道最大值。"""
    assert MappingEngine.map_aircraft(
        0.5, 1.0, 10.0, 180, 90, curve="exp") == (0, 0)
    assert MappingEngine.map_aircraft(
        20.0, 1.0, 10.0, 180, 90, curve="exp") == (180, 90)
    assert MappingEngine.map_tank(
        5.0, 10.0, 60.0, 120, 60, curve="log") == (0, 0)
    assert MappingEngine.map_tank(
        300.0, 10.0, 60.0, 120, 60, curve="log") == (120, 60)


def test_map_aircraft_default_args_keep_linear():
    """不传曲线参数时保持原有线性行为（旧调用方无需改动）。"""
    assert MappingEngine.map_aircraft(5.5, 1.0, 10.0, 200, 200) == (100, 100)


# ============================================================
# 配置读写与校验
# ============================================================

def write_config(tmp_path, data):
    """写入临时配置文件并返回 ConfigManager。"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ConfigManager(str(path))


def test_curve_config_defaults():
    """三个常态设置段默认曲线为线性、陡度 2.0。"""
    config = ConfigManager(
        os.path.join(ROOT, "config.default.json")).load()
    for section in (config.aircraft, config.tank, config.cas):
        assert section.curve == "linear"
        assert section.curve_steepness == pytest.approx(2.0)


def test_curve_config_round_trip(tmp_path):
    """曲线配置从文件加载后字段保留。"""
    manager = write_config(tmp_path, {
        "aircraft": {"curve": "exp", "curve_steepness": 3.5,
                     "channel_a_max": 60},
        "tank": {"curve": "log", "curve_steepness": 1.5},
        "cas": {"curve": "exp", "curve_steepness": 2.5},
    })
    config = manager.load()
    assert config.aircraft.curve == "exp"
    assert config.aircraft.curve_steepness == pytest.approx(3.5)
    assert config.tank.curve == "log"
    assert config.cas.curve_steepness == pytest.approx(2.5)


def test_curve_config_unknown_name_falls_back(tmp_path):
    """未知曲线名静默回退线性，同段其他字段不受影响。"""
    manager = write_config(tmp_path, {
        "aircraft": {"curve": "step", "channel_a_max": 55},
    })
    config = manager.load()
    assert config.aircraft.curve == "linear"
    assert config.aircraft.channel_a_max == 55


def test_curve_config_steepness_out_of_range_resets_field(tmp_path):
    """陡度越界时只回退陡度，曲线类型与强度上限保留。"""
    manager = write_config(tmp_path, {
        "aircraft": {"curve": "exp", "curve_steepness": 10.0,
                     "channel_a_max": 55},
    })
    config = manager.load()
    assert config.aircraft.curve == "exp"
    assert config.aircraft.channel_a_max == 55
    assert config.aircraft.curve_steepness == pytest.approx(2.0)


def test_default_template_contains_curve_keys():
    """config.default.json 三个常态段必须包含曲线键，防止打包缺键。"""
    with open(os.path.join(ROOT, "config.default.json"),
              encoding="utf-8") as file:
        data = json.load(file)
    for section in ("aircraft", "tank", "cas"):
        assert data[section]["curve"] == "linear"
        assert data[section]["curve_steepness"] == 2.0


# ============================================================
# GUI 控件双向绑定
# ============================================================

def test_curve_controls_gui_round_trip(tmp_path):
    """设置面板曲线控件必须同时接入加载与保存，修改后能持久化。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import Mock

    from PySide6.QtWidgets import QApplication

    from src.gui.main_window import MainWindow

    _app = QApplication.instance() or QApplication([])
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager, on_mode_changed=Mock())
    panel = window.settings_panel
    try:
        assert panel.ac_curve.count() == 3
        assert panel.tank_curve.count() == 3
        assert panel.cas_curve.count() == 3

        panel.ac_curve.setCurrentIndex(1)          # 指数
        panel.ac_curve_steepness.setValue(3.5)
        panel.tank_curve.setCurrentIndex(2)        # 对数
        panel.cas_curve.setCurrentIndex(1)
        assert panel.save_settings(show_feedback=False, notify=False)
        assert manager.config.aircraft.curve == "exp"
        assert manager.config.aircraft.curve_steepness == pytest.approx(3.5)
        assert manager.config.tank.curve == "log"
        assert manager.config.cas.curve == "exp"

        panel.ac_curve.setCurrentIndex(0)
        panel._load_config()
        assert panel.ac_curve.currentIndex() == 1
        assert panel.ac_curve_steepness.value() == pytest.approx(3.5)

        # 线性时陡度置灰，选择非线性后恢复可编辑
        panel.ac_curve.setCurrentIndex(0)
        assert not panel.ac_curve_steepness.isEnabled()
        panel.ac_curve.setCurrentIndex(2)
        assert panel.ac_curve_steepness.isEnabled()
    finally:
        window._exit_requested = True
        window.close()
