"""单实例互斥和已有窗口激活回归测试。"""

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import main
from src.single_instance import SingleInstance

_APP = QApplication.instance() or QApplication([])


def test_existing_server_prevents_second_instance(monkeypatch):
    """已有本地服务时第二实例不能取得所有权。"""
    instance = SingleInstance()
    monkeypatch.setattr(main.sys, "platform", "linux")
    monkeypatch.setattr(instance, "_connect_existing_instance", lambda: True)

    assert instance.acquire() is False


def test_activation_message_waits_for_callback():
    """窗口未构造时收到的激活消息应在设置回调后补触发。"""
    instance = SingleInstance()
    socket = Mock()
    socket.readAll.return_value = b"activate"
    callback = Mock()

    instance._handle_socket_data(socket)
    assert instance._pending_activation is True
    instance.set_activate_callback(callback)
    _APP.processEvents()

    assert callback.called
    socket.write.assert_called_once_with(b"ok")


def test_main_does_not_create_app_for_second_instance(monkeypatch):
    """重复启动时主入口不得初始化第二套业务控制器。"""
    instance = Mock()
    instance.acquire.return_value = False
    app_class = Mock()
    monkeypatch.setattr(main, "SingleInstance", lambda: instance)
    monkeypatch.setattr(main, "App", app_class)

    main.main()

    app_class.assert_not_called()
