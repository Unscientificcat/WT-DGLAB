"""单实例控制：阻止重复启动并通知已有实例显示主窗口。"""

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance:
    """使用 Windows 互斥锁和 Qt 本地 IPC 管理单个程序实例。"""

    _SERVER_NAME = "WT-DGLAB-single-instance"
    _MUTEX_NAME = "Local\\WT-DGLAB-single-instance"
    _ERROR_ALREADY_EXISTS = 183

    def __init__(self) -> None:
        self._mutex_handle = None
        self._server = QLocalServer()
        self._owns_server = False
        self._activate_callback: Callable[[], None] | None = None
        self._pending_activation = False

    def acquire(self) -> bool:
        """尝试成为唯一实例；已有实例存在时通知它并返回 False。"""
        if sys.platform == "win32":
            if not self._acquire_windows_mutex():
                self._notify_existing_instance()
                self.close()
                return False
        elif self._connect_existing_instance():
            self.close()
            return False

        QLocalServer.removeServer(self._SERVER_NAME)
        self._server.newConnection.connect(self._handle_new_connection)
        if not self._server.listen(self._SERVER_NAME):
            # Windows 互斥锁已经保证不会有第二个业务实例，监听失败时
            # 仍保留当前实例运行，只是本次无法响应后续激活消息。
            return True
        self._owns_server = True
        return True

    def set_activate_callback(self, callback: Callable[[], None]) -> None:
        """设置收到重复启动消息时调用的窗口激活回调。"""
        self._activate_callback = callback
        if self._pending_activation:
            self._pending_activation = False
            QTimer.singleShot(0, callback)

    def close(self) -> None:
        """释放本地 IPC 和 Windows 互斥锁资源。"""
        self._server.close()
        if self._owns_server:
            QLocalServer.removeServer(self._SERVER_NAME)
            self._owns_server = False
        if self._mutex_handle is not None:
            ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            self._mutex_handle = None

    def _acquire_windows_mutex(self) -> bool:
        """创建 Windows 本地互斥锁并返回是否成功取得所有权。"""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        create_mutex.restype = wintypes.HANDLE
        self._mutex_handle = create_mutex(None, False, self._MUTEX_NAME)
        if not self._mutex_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.get_last_error() != self._ERROR_ALREADY_EXISTS

    def _connect_existing_instance(self) -> bool:
        """非 Windows 环境下尝试连接已有本地服务器。"""
        socket = QLocalSocket()
        socket.connectToServer(self._SERVER_NAME)
        if not socket.waitForConnected(250):
            return False
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(250)
        # 等待首实例确认，避免 Windows 命名管道尚未接受连接时消息丢失。
        if socket.waitForReadyRead(750):
            socket.readAll()
        socket.disconnectFromServer()
        return True

    def _notify_existing_instance(self) -> None:
        """通知已有 Windows 实例显示主窗口，兼容启动竞态。"""
        for _ in range(10):
            if self._connect_existing_instance():
                return
            time.sleep(0.1)

    def _handle_new_connection(self) -> None:
        """接收重复启动消息并触发窗口激活。"""
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(
                lambda current=socket: self._handle_socket_data(current)
            )
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._handle_socket_data(socket)

    def _handle_socket_data(self, socket: QLocalSocket) -> None:
        """读取激活消息并调用回调。"""
        if not socket.readAll():
            return
        if self._activate_callback is None:
            self._pending_activation = True
        else:
            self._activate_callback()
        socket.write(b"ok")
        socket.flush()
        socket.disconnectFromServer()
