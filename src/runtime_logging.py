"""本次运行日志：线程安全记录、快照导出和正常退出清理。"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import BinaryIO
from uuid import uuid4

from .runtime_paths import application_directory


_session = None
MAX_LINES = 10_000


@dataclass
class LogSnapshot:
    """固定在点击时刻的文件边界，读取句柄由导出操作负责关闭。"""

    source: BinaryIO | None
    size: int
    fallback: bytes
    complete: bool

    def close(self) -> None:
        """释放快照持有的读取句柄。"""
        if self.source is not None:
            self.source.close()
            self.source = None


class RuntimeLogSession(logging.Handler):
    """接收各模块日志，并仅在确认正常结束时删除自己的自动文件。"""

    def __init__(self, directory=None, *, install_hooks=True):
        super().__init__(logging.INFO)
        self.directory = Path(directory or Path(application_directory()) / "logs")
        self.started = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        self.path = self.directory / f"run_{self.started}_{os.getpid()}.log"
        self.error = ""
        self.abnormal = False
        self.finished = False
        self._file = None
        self._lines = deque(maxlen=MAX_LINES)
        self._sequence = 0
        self._hooks_installed = install_hooks
        self.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("xb")
        except OSError as error:
            self._storage_failed(error)
        root = logging.getLogger()
        self._old_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(self)
        if install_hooks:
            self._old_sys_hook = sys.excepthook
            self._old_thread_hook = threading.excepthook
            sys.excepthook = self._sys_exception
            threading.excepthook = self._thread_exception

    def _storage_failed(self, error) -> None:
        self.error = f"日志保存失败，记录可能不完整：{error}"
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def emit(self, record) -> None:
        """在 Handler 锁内追加文件和有界界面缓存，不触碰 Qt 控件。"""
        if self.finished:
            return
        message = self.format(record)
        for line in message.splitlines():
            self._sequence += 1
            self._lines.append((self._sequence, line))
        if self._file is not None:
            try:
                self._file.write((message + "\n").encode("utf-8"))
                self._file.flush()
            except OSError as error:
                self._storage_failed(error)

    def recent(self, after=0) -> tuple[int, list[str], bool]:
        """返回游标之后的最近行，以及是否需要重建显示缓存。"""
        with self.lock:
            truncated = bool(self._lines and after < self._lines[0][0] - 1)
            return (self._sequence,
                    [line for seq, line in self._lines if seq > after],
                    truncated)

    def mark_abnormal(self, reason: str) -> None:
        """标记需要保留本次自动日志的异常，不改变程序控制流程。"""
        self.abnormal = True
        logging.getLogger("WT-DGLAB").error("本次运行异常：%s", reason)

    def _sys_exception(self, kind, value, traceback) -> None:
        self.abnormal = True
        logging.getLogger("WT-DGLAB").critical(
            "主线程未处理异常", exc_info=(kind, value, traceback))
        self._old_sys_hook(kind, value, traceback)

    def _thread_exception(self, args) -> None:
        self.abnormal = True
        logging.getLogger("WT-DGLAB").critical(
            "后台线程未处理异常：%s", args.thread.name if args.thread else "未知",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        self._old_thread_hook(args)

    def snapshot(self) -> LogSnapshot:
        """固定当前文件长度；存储故障时提供明确标记的不完整内存副本。"""
        with self.lock:
            if not self.error and self._file is not None:
                try:
                    self._file.flush()
                    source = self.path.open("rb")
                    return LogSnapshot(source, os.fstat(source.fileno()).st_size,
                                       b"", True)
                except OSError as error:
                    self._storage_failed(error)
            text = "【不完整日志：仅包含仍可用的最近内存记录】\n"
            text += "\n".join(line for _, line in self._lines) + "\n"
            return LogSnapshot(None, 0, text.encode("utf-8"), False)

    def export(self, snapshot: LogSnapshot) -> Path:
        """将固定快照写入唯一文件；无论成功失败都释放源文件句柄。"""
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        suffix = uuid4().hex[:8]
        target = self.directory / f"export_{self.started}_{stamp}_{suffix}.log"
        temporary = target.with_suffix(".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as output:
                if snapshot.source is not None:
                    remaining = snapshot.size
                    while remaining:
                        chunk = snapshot.source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise OSError("源日志长度发生变化，无法完成导出")
                        output.write(chunk)
                        remaining -= len(chunk)
                else:
                    output.write(snapshot.fallback)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(target)
            return target
        finally:
            snapshot.close()
            if temporary.exists():
                temporary.unlink()

    def finish(self, normal=False) -> None:
        """停止接收日志；正常且无未处理异常时仅删除本次自动文件。"""
        global _session
        with self.lock:
            if self.finished:
                return
            logging.getLogger("WT-DGLAB").info(
                "运行结束：%s",
                "正常退出，清理完成" if normal and not self.abnormal
                else "异常结束或存在未处理异常，保留日志")
            self.finished = True
            if self._file is not None:
                try:
                    self._file.close()
                except OSError as error:
                    self.error = f"日志关闭失败：{error}"
                    self.abnormal = True
                self._file = None
        logging.getLogger().removeHandler(self)
        logging.getLogger().setLevel(self._old_level)
        if self._hooks_installed:
            if sys.excepthook == self._sys_exception:
                sys.excepthook = self._old_sys_hook
            if threading.excepthook == self._thread_exception:
                threading.excepthook = self._old_thread_hook
        if normal and not self.abnormal:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as error:
                self.error = f"本次自动日志删除失败，文件已保留：{error}"
                # 文件无法删除时尽力在原文件中留下原因，不触碰历史日志。
                try:
                    with self.path.open("ab") as output:
                        output.write((self.error + "\n").encode("utf-8"))
                except OSError:
                    pass
                logging.getLogger("WT-DGLAB").warning(self.error)
        if _session is self:
            _session = None
        super().close()


def start_session() -> RuntimeLogSession:
    """启动本进程会话，重复调用返回同一个活动服务。"""
    global _session
    if _session is None or _session.finished:
        _session = RuntimeLogSession()
    return _session


def current_session() -> RuntimeLogSession | None:
    """返回当前运行日志服务，未启动时返回空。"""
    return _session


def mark_runtime_abnormal(reason: str) -> None:
    """供后台清理流程标记异常，有日志会话时保留诊断记录。"""
    if _session is not None:
        _session.mark_abnormal(reason)


class StrengthLogSummary:
    """按一秒窗口汇总变化的目标强度，不影响实际指令频率。"""

    def __init__(self):
        self._since = time.monotonic()
        self._last = None
        self._minimum = None
        self._maximum = None
        self._changed = False

    def observe(self, a: int, b: int) -> None:
        """收集目标值，仅在窗口结束且值变化时输出汇总。"""
        values = (a, b)
        if values != self._last:
            self._changed = True
        self._last = values
        self._minimum = values if self._minimum is None else tuple(
            min(x, y) for x, y in zip(self._minimum, values))
        self._maximum = values if self._maximum is None else tuple(
            max(x, y) for x, y in zip(self._maximum, values))
        if time.monotonic() - self._since >= 1:
            self.flush()

    def flush(self) -> None:
        """输出剩余变化窗口，退出时也保留最后一次变化。"""
        if self._changed:
            logging.getLogger("WT-DGLAB").info(
                "目标强度汇总：当前 A=%s B=%s；范围 A=%s~%s B=%s~%s",
                *self._last, self._minimum[0], self._maximum[0],
                self._minimum[1], self._maximum[1])
        self._changed = False
        self._minimum = self._maximum = None
        self._since = time.monotonic()
