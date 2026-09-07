"""悬浮窗显示内容开关、设置对话框与配置持久化回归测试。"""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.gui.main_window import OverlayContentDialog
from src.gui.overlay import OVERLAY_CONTENT_FLAGS, OverlayWindow

_APP = QApplication.instance() or QApplication([])


def _write_config(tmp_path, app_overrides: dict) -> str:
    """写入仅含 app 段的临时配置文件。"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"app": app_overrides}, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(path)


def test_content_flags_default_all_true(tmp_path):
    """默认配置下所有显示项均为开启。"""
    cfg = ConfigManager(str(tmp_path / "config.json")).load()

    for key in OVERLAY_CONTENT_FLAGS:
        assert getattr(cfg.app, f"overlay_show_{key}") is True


def test_content_flags_round_trip_and_corrupted_values(tmp_path):
    """显示开关可保存重载，手工损坏的值按布尔化处理不致命。"""
    path = _write_config(tmp_path, {
        "overlay_show_mode": False,
        "overlay_show_speed": False,
        "overlay_show_wave_b": False,
    })
    cfg = ConfigManager(path).load()

    assert cfg.app.overlay_show_mode is False
    assert cfg.app.overlay_show_speed is False
    assert cfg.app.overlay_show_wave_b is False
    assert cfg.app.overlay_show_gforce is True

    cfg.app.overlay_show_mode = True
    manager = ConfigManager(path)
    manager.load()
    manager.config.app.overlay_show_mode = True
    manager.save()
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["app"]["overlay_show_mode"] is True

    corrupted = ConfigManager(_write_config(tmp_path, {
        "overlay_show_event": "不是布尔",
    })).load()
    assert corrupted.app.overlay_show_event is True


def test_set_content_flags_hides_overlay_widgets():
    """关闭对应开关后悬浮窗控件隐藏，开启后恢复。"""
    overlay = OverlayWindow()

    overlay.set_content_flags({
        "mode": False, "gforce": False, "speed": False, "event": False,
        "strength_a": False, "strength_b": False,
        "wave_a": False, "wave_b": False,
    })
    assert not overlay.mode_label.isVisibleTo(overlay)
    assert not overlay.g_row.isVisibleTo(overlay)
    assert not overlay.speed_row.isVisibleTo(overlay)
    assert not overlay.event_label.isVisibleTo(overlay)
    assert not overlay.a_label.isVisibleTo(overlay)
    assert not overlay.a_wave_label.isVisibleTo(overlay)

    overlay.set_content_flags({"mode": True, "strength_a": True})
    assert overlay.mode_label.isVisibleTo(overlay)
    assert overlay.a_label.isVisibleTo(overlay)
    assert not overlay.b_label.isVisibleTo(overlay)
    overlay.destroy()


def test_update_hides_metric_rows_without_data():
    """指标行可见性 = 开关 且 该指标有数据；空文本隐藏对应行。"""
    overlay = OverlayWindow()

    overlay.update("aircraft", "3.5", "", 120, 80, "挥鞭.pulse", "恒定", "")
    assert overlay.g_row.isVisibleTo(overlay)
    assert not overlay.speed_row.isVisibleTo(overlay)
    assert overlay.g_value_label.text() == "3.5"
    assert overlay.a_label.text() == "A: 120"
    assert overlay.a_wave_label.text() == "挥鞭"

    # 开关关闭时即使有数据也不显示
    overlay.set_content_flags({"gforce": False})
    assert not overlay.g_row.isVisibleTo(overlay)
    overlay.destroy()


def test_update_only_rewrites_changed_fields():
    """悬浮窗差量更新：值不变时不重复 setText。"""
    overlay = OverlayWindow()
    calls = []
    original_set_text = overlay.a_label.setText

    def spy_set_text(text):
        calls.append(text)
        original_set_text(text)

    overlay.a_label.setText = spy_set_text

    overlay.update("aircraft", "2.0", "", 100, 100, "恒定", "恒定", "")
    calls.clear()
    overlay.update("aircraft", "2.0", "", 100, 100, "恒定", "恒定", "")
    assert calls == []

    overlay.update("aircraft", "2.0", "", 101, 100, "恒定", "恒定", "")
    assert calls == ["A: 101"]
    overlay.destroy()


def test_sync_overlay_shows_only_mode_trigger_metric():
    """空战/CAS 只显示过载，陆战地面只显示速度（各自触发指标）。"""
    from src.game_reader import AircraftData, GameState, TankData
    from main import App

    def make_app(state, last_g="", last_speed=""):
        app = App.__new__(App)
        app._apply_overlay_settings = Mock()
        app._last_state = state
        app._event_remaining = 0.0
        app._event_kind = ""
        app._event_mode = ""
        app._overlay_last_g = last_g
        app._overlay_last_speed = last_speed
        app.overlay = SimpleNamespace(visible=True, update=Mock())
        return app

    air_state = GameState(
        connected=True,
        vehicle_type="aircraft",
        aircraft=AircraftData(valid=True, gforce=2.5, speed_kmh=300),
    )
    app = make_app(air_state)
    app._sync_overlay("aircraft", 50, 40)
    app.overlay.update.assert_called_once_with(
        "aircraft", "2.5", "", 50, 40, "恒定", "恒定", "")
    assert app._overlay_last_speed == ""

    ground_state = GameState(
        connected=True,
        vehicle_type="tank",
        tank=TankData(valid=True, speed_kmh=45),
    )
    app = make_app(ground_state)
    app._sync_overlay("tank", 30, 20)
    app.overlay.update.assert_called_once_with(
        "tank", "", "45", 30, 20, "恒定", "恒定", "")

    cas_state = GameState(
        connected=True,
        vehicle_type="aircraft",
        aircraft=AircraftData(valid=True, gforce=1.8, speed_kmh=260),
    )
    app = make_app(cas_state, last_speed="68")
    app._sync_overlay("tank", 20, 10)
    # CAS 只显示过载，且陆战期间的速度值不得残留
    app.overlay.update.assert_called_once_with(
        "tank", "1.8", "", 20, 10, "恒定", "恒定", "")
    assert app._overlay_last_speed == ""


def test_sync_overlay_reuses_last_value_only_within_context():
    """数据短暂无效时沿用上次值，但仅在相同触发上下文内。"""
    from src.game_reader import AircraftData, GameState
    from main import App

    invalid_air = GameState(
        connected=True,
        vehicle_type="aircraft",
        aircraft=AircraftData(valid=False),
    )
    app = App.__new__(App)
    app._apply_overlay_settings = Mock()
    app._last_state = invalid_air
    app._event_remaining = 0.0
    app._event_kind = ""
    app._event_mode = ""
    app._overlay_last_g = "2.1"
    app._overlay_last_speed = "55"
    app.overlay = SimpleNamespace(visible=True, update=Mock())

    app._sync_overlay("aircraft", 0, 0)

    # 空中沿用过载，速度缓存不跨上下文泄漏
    app.overlay.update.assert_called_once_with(
        "aircraft", "2.1", "", 0, 0, "恒定", "恒定", "")
    assert app._overlay_last_speed == ""


def test_sync_overlay_shows_placeholder_when_not_in_battle():
    """未进入对局时按当前模式显示 -- 占位（过载或速度），恢复旧版行为。"""
    from src.game_reader import GameState
    from main import App

    app = App.__new__(App)
    app._apply_overlay_settings = Mock()
    app._last_state = GameState()   # 未连接，无有效对局数据
    app._event_remaining = 0.0
    app._event_kind = ""
    app._event_mode = ""
    app._overlay_last_g = ""
    app._overlay_last_speed = ""
    app.overlay = SimpleNamespace(visible=True, update=Mock())

    app._sync_overlay("aircraft", 0, 0)
    app.overlay.update.assert_called_once_with(
        "aircraft", "--", "", 0, 0, "恒定", "恒定", "")

    app.overlay.update.reset_mock()
    app._sync_overlay("tank", 0, 0)
    app.overlay.update.assert_called_once_with(
        "tank", "", "--", 0, 0, "恒定", "恒定", "")


def test_content_dialog_emits_flags_on_toggle():
    """对话框勾选变化立即回调最新开关集合。"""
    seen = []
    dialog = OverlayContentDialog(
        {key: True for key in OVERLAY_CONTENT_FLAGS}, on_change=seen.append)

    dialog._checkboxes["mode"].setChecked(False)

    assert seen and seen[-1]["mode"] is False
    assert seen[-1]["gforce"] is True

    dialog._checkboxes["mode"].setChecked(True)
    assert seen[-1]["mode"] is True
    dialog.deleteLater()


def test_content_dialog_reset_defaults_and_set_flags():
    """恢复默认勾选全部显示项；set_flags 同步不触发回调。"""
    seen = []
    dialog = OverlayContentDialog(
        {key: True for key in OVERLAY_CONTENT_FLAGS}, on_change=seen.append)

    dialog._checkboxes["speed"].setChecked(False)
    count = len(seen)
    dialog.set_flags({key: False for key in OVERLAY_CONTENT_FLAGS})
    assert len(seen) == count
    assert dialog.flags() == {key: False for key in OVERLAY_CONTENT_FLAGS}

    dialog._reset_defaults()
    assert seen[-1] == {key: True for key in OVERLAY_CONTENT_FLAGS}
    dialog.deleteLater()


def test_app_applies_content_flags_and_persists(tmp_path):
    """App 应用开关：写配置、更新悬浮窗并保存，值不变时不重复落盘。"""
    from main import App

    path = _write_config(tmp_path, {})
    manager = ConfigManager(path)
    manager.load()
    app = App.__new__(App)
    app.config_mgr = manager
    app.overlay = SimpleNamespace(set_content_flags=Mock())

    flags = {key: True for key in OVERLAY_CONTENT_FLAGS}
    flags["mode"] = False
    app._apply_overlay_content(flags)

    app.overlay.set_content_flags.assert_called_once_with(flags)
    assert manager.config.app.overlay_show_mode is False
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["app"]["overlay_show_mode"] is False

    app.overlay.set_content_flags.reset_mock()
    manager.save = Mock()
    app._apply_overlay_content(flags)
    assert app.overlay.set_content_flags.call_count == 1
    # 开关未变化时不再重复写盘
    manager.save.assert_not_called()


def test_app_opens_content_dialog_as_singleton():
    """App 维护显示内容对话框单例，重复打开复用并同步勾选。"""
    from main import App

    app = App.__new__(App)
    app.config_mgr = SimpleNamespace(config=SimpleNamespace(app=SimpleNamespace(
        **{f"overlay_show_{key}": True for key in OVERLAY_CONTENT_FLAGS})))
    app.overlay = object()
    app.window = None
    app._overlay_content_dialog = None

    created = []

    def fake_dialog(flags, on_change, parent):
        dialog = SimpleNamespace(
            flags_value=flags,
            set_flags=Mock(side_effect=lambda f: setattr(
                dialog, "flags_value", f)),
            show=Mock(), raise_=Mock(), activateWindow=Mock(),
        )
        created.append(dialog)
        return dialog

    import main as main_module
    original = main_module.OverlayContentDialog
    main_module.OverlayContentDialog = fake_dialog
    try:
        app._open_overlay_content_dialog()
        app._open_overlay_content_dialog()
    finally:
        main_module.OverlayContentDialog = original

    assert len(created) == 1
    assert app._overlay_content_dialog is created[0]
    assert created[0].show.call_count == 2


def test_right_click_menu_contains_content_entry():
    """悬浮窗右键菜单首项为"显示内容…"，选中后发出请求信号。"""
    from PySide6.QtCore import QPoint

    overlay = OverlayWindow()
    seen = []
    overlay.content_settings_requested.connect(lambda: seen.append(True))

    menu, content_action = overlay._build_settings_menu()
    assert menu.actions()[0].text() == "显示内容…"
    assert menu.actions()[0] is content_action

    # 实例级补丁模拟用户选中"显示内容…"，避免真实的模态 exec 循环
    menu.exec = lambda pos: content_action
    overlay._build_settings_menu = lambda: (menu, content_action)
    overlay._show_settings_menu(QPoint(0, 0))

    assert seen == [True]
    menu.close()
    overlay.destroy()
