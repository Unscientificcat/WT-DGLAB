"""程序入口与退出清理的日志生命周期回归。"""

import os
from types import SimpleNamespace
from unittest.mock import Mock
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import main
from src.runtime_logging import RuntimeLogSession, StrengthLogSummary


_APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mode,retained", [
    ("normal", False), ("unexpected", True), ("init_failure", True),
    ("run_failure", True), ("instance_cleanup_failure", True),
])
def test_main_only_deletes_on_expected_exit(tmp_path, monkeypatch, mode, retained):
    session = RuntimeLogSession(tmp_path, install_hooks=False)
    monkeypatch.setattr(main, "start_session", lambda: session)
    instance = Mock()
    instance.acquire.return_value = True
    if mode == "instance_cleanup_failure":
        instance.close.side_effect = RuntimeError("单实例清理失败")
    monkeypatch.setattr(main, "SingleInstance", lambda: instance)
    class FakeApp:
        def __init__(self):
            if mode == "init_failure":
                raise RuntimeError("启动失败")
            self._shutdown_started = False
            self._shutdown_complete = False
            self.window = Mock()
        def run(self):
            if mode == "run_failure":
                raise RuntimeError("运行失败")
            if mode != "unexpected":
                self._on_close()
        def _on_close(self):
            self._shutdown_started = True
            self._shutdown_complete = True
    monkeypatch.setattr(main, "App", FakeApp)
    if mode in {"init_failure", "run_failure"}:
        with pytest.raises(RuntimeError):
            main.main()
        assert "Traceback" in session.path.read_text(encoding="utf-8")
    else:
        main.main()
    assert session.path.exists() == retained


def test_cleanup_failure_does_not_skip_other_resources(tmp_path, monkeypatch):
    import src.runtime_logging as runtime_logging
    session = RuntimeLogSession(tmp_path, install_hooks=False)
    monkeypatch.setattr(runtime_logging, "_session", session)
    app = main.App.__new__(main.App)
    app._shutdown_started = False
    app._stop_event = threading.Event()
    app._running = True
    app.window = Mock()
    app.window.save_current_settings.side_effect = OSError("配置不可写")
    app.config_mgr = Mock()
    app.coyote = Mock()
    app._controllers = [app.coyote]
    app._start_workers = []
    app._strength_summary = StrengthLogSummary()
    app._scope_dialogs = {"A": Mock()}
    app.overlay = Mock()
    try:
        app._on_close()
        app.coyote.stop.assert_called()
        app.window.stop_runtime_log_view.assert_called_once()
        app.overlay.dispose.assert_called_once()
        app.window.quit.assert_called_once()
        assert not app._shutdown_complete
        assert session.abnormal
        session.finish(normal=True)
        assert session.path.exists()
    finally:
        session.finish()


def test_shutdown_waits_share_one_deadline(monkeypatch):
    """多个卡住的后台线程共享总等待时长，而非每个 13 秒（C5）。"""
    import main
    from src.runtime_logging import StrengthLogSummary

    timeouts = []
    now = [100.0]

    class StuckThread:
        name = "stuck"

        def join(self, timeout=None):
            # 每个线程实际等待 3 秒后仍未结束
            timeouts.append(timeout)
            now[0] += 3.0

        def is_alive(self):
            return True

    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    app = main.App.__new__(main.App)
    app._shutdown_started = False
    app._stop_event = threading.Event()
    app._running = True
    app.window = Mock()
    app.config_mgr = Mock()
    app.coyote = Mock()
    app._controllers = [app.coyote]
    app._start_workers = [StuckThread(), StuckThread(), StuckThread()]
    app._strength_summary = StrengthLogSummary()
    app._scope_dialogs = {}
    app.overlay = Mock()
    monkeypatch.setattr(main, "mark_runtime_abnormal", lambda *_: None)
    app._on_close()
    assert timeouts == [5.0, 2.0, 0.0]
