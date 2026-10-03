"""陆战静止惩罚回归测试：状态机、豁免、优先级与配置校验。"""

import os
import queue
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as main_module
from main import App
from src.config_manager import Config, ConfigManager, TankSettings
from src.game_reader import GameState, TankData

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tank_state(speed=0.0, repairing=False, valid=True, crew_alive=None):
    """创建有效战局中的坦克遥测。"""
    return GameState(
        connected=True, link_ok=True, vehicle_type="tank",
        tank=TankData(valid=valid, is_repairing=repairing,
                      speed_kmh=speed, crew_alive=crew_alive),
    )


@pytest.fixture
def app():
    """保留真实事件、状态机与映射逻辑，仅替换界面及设备边界。"""
    instance = App.__new__(App)
    cfg = Config()
    cfg.tank.enabled = False
    cfg.cas.enabled = False
    cfg.tank.idle_enabled = True
    cfg.tank.idle_timeout_s = 10.0
    cfg.tank.idle_speed_max = 2.0
    cfg.tank.idle_ch_a = 60
    cfg.tank.idle_ch_b = 30
    cfg.tank.idle_wf_a = "静止A"
    cfg.tank.idle_wf_b = "静止B"
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
    instance._idle_move_frames = 0
    instance._wt_connected = True
    instance._wt_fail_count = 0
    instance._overlay_tick = 0
    instance._running = False
    instance._event_queue = queue.Queue()
    instance._data_queue = queue.Queue()
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


def kill_event():
    """构造击杀事件字典。"""
    return dict(kind="kill", mode="tank", ch_a=81, ch_b=42, duration=5,
                wf_a="击杀A", wf_b="击杀B")


# ============================================================
# 状态机与输出
# ============================================================

def test_idle_triggers_after_timeout(app, clock):
    """静止累计超过超时秒数后进入惩罚输出。"""
    tick(app, tank_state(speed=0))          # t=1000 计时开始
    assert not app._idle_active
    clock[0] += 5
    tick(app, tank_state(speed=0))          # 仍在累计
    assert not app._idle_active
    app._send_strength.assert_called_with(0, 0)
    clock[0] += 5.1
    tick(app, tank_state(speed=0))          # 超过 10 秒 → 触发
    assert app._idle_active
    app._send_strength.assert_called_with(60, 30)
    app.coyote.set_waveform_a.assert_called_with("静止A", False, 30, 50)
    app.window.dashboard.show_event.assert_called_with("🛑 静止超时，请移动!")


def test_idle_output_persists_until_moving(app, clock):
    """惩罚输出持续到恢复移动，期间每轮都输出惩罚强度。"""
    tick(app, tank_state(speed=0))          # 建立计时起点
    clock[0] += 11
    tick(app, tank_state(speed=0))          # 超时 → 触发
    assert app._idle_active
    clock[0] += 0.2
    tick(app, tank_state(speed=0))
    app._send_strength.assert_called_with(60, 30)
    clock[0] += 0.2
    tick(app, tank_state(speed=1))          # 仍低于阈值 → 继续惩罚
    app._send_strength.assert_called_with(60, 30)
    clock[0] += 0.2
    tick(app, tank_state(speed=30))         # 恢复移动 → 惩罚结束
    assert not app._idle_active
    app._send_strength.assert_called_with(0, 0)
    app.window.dashboard.show_event.assert_called_with("")


def test_idle_timer_resets_after_movement(app, clock):
    """恢复移动重置计时；再次静止需重新累计完整超时时长。"""
    tick(app, tank_state(speed=0))
    clock[0] += 9
    tick(app, tank_state(speed=40))         # 移动，重置
    assert app._idle_start_time is None
    clock[0] += 1
    tick(app, tank_state(speed=0))          # 重新计时
    clock[0] += 9
    tick(app, tank_state(speed=0))          # 仅累计 9 秒，不触发
    assert not app._idle_active
    clock[0] += 1.1
    tick(app, tank_state(speed=0))
    assert app._idle_active


def test_idle_disabled_never_triggers(app, clock):
    """功能关闭时不触发。"""
    app.config_mgr.config.tank.idle_enabled = False
    tick(app, tank_state(speed=0))
    clock[0] += 60
    tick(app, tank_state(speed=0))
    assert not app._idle_active
    app._send_strength.assert_called_with(0, 0)


# ============================================================
# 豁免
# ============================================================

def test_repairing_exempts_idle(app, clock):
    """维修中不累计静止时间。"""
    tick(app, tank_state(speed=0, repairing=True))
    clock[0] += 60
    tick(app, tank_state(speed=0, repairing=True))
    assert not app._idle_active


def test_destroyed_tank_exempts_idle(app, clock):
    """乘员全灭（被击毁）期间不累计静止时间。"""
    tick(app, tank_state(speed=0, crew_alive=False))
    clock[0] += 60
    tick(app, tank_state(speed=0, crew_alive=False))
    assert not app._idle_active


def test_respawned_tank_resumes_idle_counting(app, clock):
    """复活后乘员存活恢复，静止重新开始计时并可触发。"""
    tick(app, tank_state(speed=0, crew_alive=False))
    clock[0] += 60
    tick(app, tank_state(speed=0, crew_alive=True))   # 复活，重新计时
    assert not app._idle_active
    clock[0] += 10.1
    tick(app, tank_state(speed=0, crew_alive=True))
    assert app._idle_active


def test_leaving_ground_resets_idle(app, clock):
    """CAS 上飞机后静止惩罚状态与提示被重置。"""
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0))
    assert app._idle_active
    app._idle_label_shown = True
    from src.game_reader import AircraftData
    cas_state = GameState(connected=True, link_ok=True,
                          vehicle_type="aircraft",
                          aircraft=AircraftData(valid=True))
    tick(app, cas_state)
    assert not app._idle_active
    assert not app._idle_label_shown


def test_disconnect_resets_idle(app, clock):
    """退出对局后静止惩罚重置且输出归零。"""
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0))
    assert app._idle_active
    tick(app, GameState())
    assert not app._idle_active
    app._send_strength.assert_called_with(0, 0)


# ============================================================
# 事件优先级
# ============================================================

def test_kill_event_overrides_idle_output(app, clock):
    """击杀事件输出优先于静止惩罚，事件结束后惩罚恢复。"""
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0), [kill_event()])
    assert app._idle_active
    app._send_strength.assert_called_with(81, 42)   # 事件强度优先
    app._event_remaining = 0.05
    clock[0] += 0.2
    tick(app, tank_state(speed=0))                  # 事件到期 → 惩罚恢复
    app._send_strength.assert_called_with(60, 30)


def test_idle_timer_keeps_running_during_kill_event(app, clock):
    """击杀事件期间静止计时继续，事件结束后立即进入惩罚。"""
    tick(app, tank_state(speed=0))                  # 开始计时
    clock[0] += 2
    tick(app, tank_state(speed=0), [kill_event()])  # 事件 5 秒
    assert not app._idle_active
    clock[0] += 9                                   # 计时继续累计 11 秒
    app._event_remaining = 0.05
    tick(app, tank_state(speed=0))
    assert app._idle_active
    app._send_strength.assert_called_with(60, 30)


# ============================================================
# 死亡封锁（阶段11-1 修复：死亡后选车界面不再持续惩罚）
# ============================================================

def death_event():
    """构造陆战被击毁事件字典。"""
    return dict(kind="death", mode="tank", ch_a=91, ch_b=92, duration=5,
                wf_a="毁A", wf_b="毁B")


def test_death_event_blocks_idle_and_stops_output(app, clock):
    """被击毁事件立即结束静止惩罚并封锁，选车界面残留帧不再触发。"""
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0))
    assert app._idle_active
    tick(app, tank_state(speed=0), [death_event()])
    assert not app._idle_active
    assert app._idle_death_blocked
    app._send_strength.assert_called_with(91, 92)   # 被击毁惩罚正常输出
    app._event_remaining = 0.05
    clock[0] += 60
    tick(app, tank_state(speed=0))                  # 事件到期 + 残留静止帧
    assert not app._idle_active
    app._send_strength.assert_called_with(0, 0)


def test_respawn_first_movement_unblocks(app, clock):
    """复活后持续开动满确认帧数才解除封锁，之后静止重新正常计时。"""
    tick(app, tank_state(speed=0), [death_event()])
    assert app._idle_death_blocked
    clock[0] += 30
    tick(app, tank_state(speed=40))          # 单帧移动不解除
    assert app._idle_death_blocked
    for _ in range(app.IDLE_UNBLOCK_FRAMES - 1):
        clock[0] += 0.2
        tick(app, tank_state(speed=40))      # 持续移动累计确认帧
    assert not app._idle_death_blocked
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0))
    assert app._idle_active


def test_death_speed_residue_does_not_unblock(app, clock):
    """死亡瞬间残留速度帧（被击毁时仍在滑行）不会误解除封锁。"""
    tick(app, tank_state(speed=0), [death_event()])
    clock[0] += 0.2
    tick(app, tank_state(speed=25))          # 死亡残帧：速度残留（实机日志场景）
    assert app._idle_death_blocked
    clock[0] += 0.2
    tick(app, tank_state(speed=18))          # 第二帧残留，仍未满确认帧数
    assert app._idle_death_blocked
    clock[0] += 0.2
    tick(app, tank_state(speed=0))           # 选车界面静止 → 清零移动确认
    assert app._idle_death_blocked
    clock[0] += 60
    tick(app, tank_state(speed=0))           # 久置不触发
    assert not app._idle_active
    for _ in range(app.IDLE_UNBLOCK_FRAMES):
        clock[0] += 0.2
        tick(app, tank_state(speed=30))      # 复活后真实驾驶 → 解除
    assert not app._idle_death_blocked


def test_movement_counter_resets_on_stationary_frame(app, clock):
    """移动确认被静止帧打断后重新计数。"""
    tick(app, tank_state(speed=0), [death_event()])
    for _ in range(app.IDLE_UNBLOCK_FRAMES - 1):
        tick(app, tank_state(speed=30))      # 差一帧满确认
    assert app._idle_death_blocked
    tick(app, tank_state(speed=0))           # 静止帧打断
    tick(app, tank_state(speed=30))
    assert app._idle_death_blocked           # 计数已清零，重新累计
    for _ in range(app.IDLE_UNBLOCK_FRAMES - 1):
        tick(app, tank_state(speed=30))
    assert not app._idle_death_blocked


def test_spawn_camping_blocked_until_sustained_movement(app, clock):
    """死亡封锁中在出生点久置不触发；持续移动后恢复正常计时。"""
    tick(app, tank_state(speed=0), [death_event()])
    clock[0] += 120
    tick(app, tank_state(speed=0))
    assert not app._idle_active
    clock[0] += 1
    for _ in range(app.IDLE_UNBLOCK_FRAMES):
        tick(app, tank_state(speed=30))
    assert not app._idle_death_blocked
    tick(app, tank_state(speed=0))
    clock[0] += 11
    tick(app, tank_state(speed=0))
    assert app._idle_active


def test_repair_frames_keep_death_block(app, clock):
    """封锁中维修豁免帧不解除封锁。"""
    tick(app, tank_state(speed=0), [death_event()])
    assert app._idle_death_blocked
    clock[0] += 30
    tick(app, tank_state(speed=0, repairing=True))
    assert app._idle_death_blocked


def test_disconnect_clears_death_block(app, clock):
    """退出对局解除死亡封锁。"""
    tick(app, tank_state(speed=0), [death_event()])
    assert app._idle_death_blocked
    tick(app, GameState())
    assert not app._idle_death_blocked
    assert not app._idle_active


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


def test_idle_waveform_honors_random_flags(app, clock):
    """静止惩罚输出按配置传递随机波形开关与间隔。"""
    app.config_mgr.config.tank.idle_random_a = True
    app.config_mgr.config.tank.random_min_a = 20
    app.config_mgr.config.tank.random_max_a = 45
    app._set_idle_waveforms(app.config_mgr.config.tank)
    app.coyote.set_waveform_a.assert_called_with("静止A", True, 20, 45)
    app.coyote.set_waveform_b.assert_called_with("静止B", False, 30, 50)


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
