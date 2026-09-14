"""运行日志的文件边界、异常保留与故障回归测试。"""

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
import subprocess
import sys

import pytest

from src.runtime_logging import RuntimeLogSession, MAX_LINES


@pytest.fixture
def session(tmp_path):
    """提供隔离目录中的日志会话。"""
    value = RuntimeLogSession(tmp_path, install_hooks=False)
    yield value
    value.finish()


def test_normal_exit_only_removes_own_file(session):
    history = session.directory / "run_history.log"
    history.write_text("历史", encoding="utf-8")
    logging.warning("中文内容")
    exported = session.export(session.snapshot())
    session.finish(normal=True)
    assert not session.path.exists()
    assert history.read_text(encoding="utf-8") == "历史"
    assert "中文内容" in exported.read_text(encoding="utf-8")


def test_abnormal_flag_retains_even_after_normal_exit(session):
    session.mark_abnormal("退出清理失败")
    session.finish(normal=True)
    assert "退出清理失败" in session.path.read_text(encoding="utf-8")


def test_export_is_snapshot_and_unique(session):
    logging.warning("点击之前")
    snapshot = session.snapshot()
    logging.warning("点击之后")
    first = session.export(snapshot)
    second = session.export(session.snapshot())
    assert first != second
    assert "点击之后" not in first.read_text(encoding="utf-8")
    assert "点击之后" in second.read_text(encoding="utf-8")


def test_threads_and_view_limit_do_not_truncate_export(session):
    def write_batch(batch):
        for index in range(2600):
            logging.getLogger("并发").info("批次%s记录%s", batch, index)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_batch, range(4)))
    _, lines, truncated = session.recent()
    assert len(lines) == MAX_LINES
    assert truncated
    text = session.export(session.snapshot()).read_text(encoding="utf-8")
    assert len(text.splitlines()) == 10400
    for batch in range(4):
        assert f"批次{batch}记录0" in text
        assert f"批次{batch}记录2599" in text


def test_storage_failure_exports_marked_memory(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("占用", encoding="utf-8")
    value = RuntimeLogSession(blocked, install_hooks=False)
    try:
        logging.warning("仍有内存记录")
        assert "日志保存失败" in value.error
        snapshot = value.snapshot()
        assert not snapshot.complete
        value.directory = tmp_path
        exported = value.export(snapshot).read_text(encoding="utf-8")
        assert "不完整日志" in exported
        assert "仍有内存记录" in exported
    finally:
        value.finish()


def test_export_failure_does_not_publish_file(session, monkeypatch):
    snapshot = session.snapshot()
    monkeypatch.setattr(Path, "replace", lambda *a: (_ for _ in ()).throw(
        OSError("模拟导出失败")))
    with pytest.raises(OSError, match="模拟导出失败"):
        session.export(snapshot)
    assert snapshot.source is None
    assert not list(session.directory.glob("export_*"))


def test_delete_failure_is_recorded(session, monkeypatch):
    original = Path.unlink
    def blocked(path, *args, **kwargs):
        if path == session.path:
            raise PermissionError("模拟占用")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", blocked)
    session.finish(normal=True)
    assert "删除失败" in session.path.read_text(encoding="utf-8")


def test_unhandled_exception_in_child_retains_traceback(tmp_path):
    code = (
        "from src.runtime_logging import RuntimeLogSession\n"
        f"session = RuntimeLogSession({str(tmp_path)!r})\n"
        "raise RuntimeError('child-crash')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode != 0
    text = next(tmp_path.glob("run_*.log")).read_text(encoding="utf-8")
    assert "Traceback" in text and "child-crash" in text


def test_force_termination_retains_flushed_record(tmp_path):
    code = (
        "import logging, time\n"
        "from src.runtime_logging import RuntimeLogSession\n"
        f"session = RuntimeLogSession({str(tmp_path)!r})\n"
        "logging.warning('before-kill')\n"
        "print('ready', flush=True)\n"
        "time.sleep(30)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline().strip() == b"ready"
        child.kill()
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
        child.stdout.close()
    assert "before-kill" in next(tmp_path.glob("run_*.log")).read_text(encoding="utf-8")


def test_background_unhandled_exception_is_retained_on_clean_exit(tmp_path):
    code = (
        "import threading\n"
        "from src.runtime_logging import RuntimeLogSession\n"
        f"session = RuntimeLogSession({str(tmp_path)!r})\n"
        "def fail():\n    raise RuntimeError('thread-crash')\n"
        "thread = threading.Thread(target=fail)\n"
        "thread.start()\nthread.join()\nsession.finish(normal=True)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0
    text = next(tmp_path.glob("run_*.log")).read_text(encoding="utf-8")
    assert "thread-crash" in text and "Traceback" in text


def test_write_failure_keeps_viewer_and_marks_export(session):
    original = session._file
    class FailedWriter:
        def write(self, data):
            raise OSError("磁盘已满")
        def close(self):
            original.close()
    session._file = FailedWriter()
    logging.warning("磁盘写入失败时的记录")
    assert "磁盘已满" in session.error
    assert "磁盘写入失败时的记录" in "\n".join(session.recent()[1])
    snapshot = session.snapshot()
    assert not snapshot.complete
    assert "不完整日志" in session.export(snapshot).read_text(encoding="utf-8")


def test_default_paths_ignore_working_directory(tmp_path, monkeypatch):
    from src import runtime_paths
    monkeypatch.chdir(tmp_path)
    source_directory = Path(runtime_paths.__file__).resolve().parent.parent
    assert Path(runtime_paths.application_directory()) == source_directory
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bundle" / "app.exe"))
    value = RuntimeLogSession(install_hooks=False)
    try:
        assert value.directory == tmp_path / "bundle" / "logs"
    finally:
        value.finish(normal=True)


def test_strength_summary_is_rate_limited(session, monkeypatch):
    from src import runtime_logging
    now = [10.0]
    monkeypatch.setattr(runtime_logging.time, "monotonic", lambda: now[0])
    summary = runtime_logging.StrengthLogSummary()
    summary.observe(1, 2)
    summary.observe(3, 4)
    assert not session.recent()[1]
    now[0] += 1
    summary.observe(2, 3)
    text = "\n".join(session.recent()[1])
    assert "当前 A=2 B=3" in text
    assert "范围 A=1~3 B=2~4" in text
    now[0] += 1
    summary.observe(2, 3)
    assert len(session.recent()[1]) == 1
    summary.observe(0, 0)
    summary.flush()
    assert "当前 A=0 B=0" in session.recent()[1][-1]


def test_connection_object_addresses_do_not_defeat_dedup(session):
    from src.game_reader import GameReader
    reader = GameReader()
    reader._log_link_error("连接 <object at 0x123ABC> 被拒绝")
    reader._log_link_error("连接 <object at 0x456DEF> 被拒绝")
    assert len(session.recent()[1]) == 1


def test_config_changes_are_logged_once_after_save(session, tmp_path):
    from src.config_manager import ConfigManager
    manager = ConfigManager(str(tmp_path / "config.json"))
    manager.config.aircraft.channel_a_max = 17
    manager.save()
    assert "aircraft.channel_a_max: 0 → 17" in "\n".join(session.recent()[1])
    count = len(session.recent()[1])
    manager.save()
    assert len(session.recent()[1]) == count
