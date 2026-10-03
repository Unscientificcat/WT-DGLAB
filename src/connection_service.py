"""GUI 之外串行管理连接启动、替换、重试和退出。"""

import logging
import threading
import time


logger = logging.getLogger(__name__)


class ConnectionService:
    """一个监督线程管理当前协议适配器，避免过期启动回调复活连接。"""

    RETRY_SECONDS = 5.0

    def __init__(self, controller):
        self._lock = threading.Lock()
        self._desired = controller
        self._active = None
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._thread = None

    def start(self):
        """非阻塞启动监督线程。"""
        with self._lock:
            if self._closed.is_set() or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="郊狼连接会话")
            self._thread.start()

    def replace(self, controller):
        """请求切换；监督线程先停旧适配器，再启动新适配器。"""
        with self._lock:
            self._desired = controller
        self._wake.set()

    def _run(self):
        retry_at = 0.0
        was_running = False
        try:
            while not self._closed.is_set():
                with self._lock:
                    desired = self._desired
                if desired is not self._active:
                    if self._active is not None:
                        self._active.stop()
                        old_thread = self._active._thread
                        if old_thread is not None and old_thread.is_alive():
                            desired.status.error = "旧连接尚未停止，等待释放连接资源"
                            self._wake.wait(0.1)
                            self._wake.clear()
                            continue
                    self._active = desired
                    retry_at = 0.0
                    was_running = False
                if self._closed.is_set():
                    break
                if was_running and not desired._running:
                    retry_at = time.monotonic() + self.RETRY_SECONDS
                was_running = desired._running
                if not desired._running and time.monotonic() >= retry_at:
                    try:
                        desired.start()
                    except Exception as error:
                        desired.status.error = str(error)
                        logger.exception("连接启动失败")
                    retry_at = time.monotonic() + self.RETRY_SECONDS
                    was_running = desired._running
                loop = getattr(desired, "_loop", None)
                if loop is not None and loop.is_running():
                    try:
                        loop.call_soon_threadsafe(desired._publish_snapshot)
                    except RuntimeError:
                        pass  # 事件循环刚好关闭，退出路径会发布最终快照。
                else:
                    desired._publish_snapshot()
                self._wake.wait(0.05)
                self._wake.clear()
        finally:
            if self._active is not None:
                self._active.stop()

    def stop(self, timeout=5.0):
        """取消重连，限定整个会话清理的总等待时间。"""
        self._closed.set()
        self._wake.set()
        active = self._active
        if active is not None:
            active.stop(wait=False)
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            return not self._thread.is_alive()
        return True
