"""连接面板精简显示及连接生命周期回归。"""

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.dglab_state import ChannelSnapshot, ConnectionSnapshot, DeviceSnapshot
from src.gui.main_window import QRWidget


_APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("protocol", ["v3", "v4"])
@pytest.mark.parametrize("state", ["ready", "recovering", "error"])
def test_bound_panel_only_shows_connected_despite_diagnostics(protocol, state):
    parent = QWidget()
    panel = QRWidget(parent)
    panel.set_protocol(protocol)
    panel.set_connection_snapshot(ConnectionSnapshot(
        state=state, bound=True, address="wss://example.invalid/v4",
        error="RuntimeError: 原始异常", selected_device="one",
        devices=(DeviceSnapshot("one", "设备一", True),
                 DeviceSnapshot("two", "设备二", True)),
        a=ChannelSnapshot(target=30, reported=12, reported_at=1,
                          limit=20, muted=True, pending_stop=True,
                          error="停止未确认"),
    ))
    assert panel.status_text.text() == "已连接"
    for widget in (panel.qr_frame, panel.url_text, panel.output_status,
                   panel.device_selector, panel.lan_notice):
        assert widget.isHidden()
    assert not panel.output_status.text() and not panel.url_text.text()
    assert panel.output_status.minimumHeight() == 0
    assert not panel.v3_button.isHidden() and not panel.v4_button.isHidden()
    assert not any("RuntimeError" in label.text() for label in panel.findChildren(QLabel))
    parent.close()


@pytest.mark.parametrize("protocol", ["v3", "v4"])
def test_disconnect_reconnect_restores_qr_and_simple_status(protocol):
    parent = QWidget()
    panel = QRWidget(parent)
    panel.set_protocol(protocol)
    panel.set_connection_snapshot(ConnectionSnapshot(state="ready", bound=True))
    panel.set_connection_snapshot(ConnectionSnapshot(
        state="error", error="ConnectionError: 私有错误详情"))
    assert panel.status_text.text() == "连接或输出异常"
    assert not panel.qr_frame.isHidden()
    assert panel.url_text.isHidden() and not panel.url_text.text()
    assert panel.output_status.isHidden() and not panel.output_status.text()
    panel.set_connection_snapshot(ConnectionSnapshot(state="waiting_app"))
    assert panel.status_text.text() == "等待手机扫码连接…"
    panel.set_connection_snapshot(ConnectionSnapshot(state="ready", bound=True))
    assert panel.status_text.text() == "已连接"
    assert panel.qr_frame.isHidden()
    parent.close()


def test_protocol_switch_and_manual_selection_remain_available_when_unbound():
    parent = QWidget()
    panel = QRWidget(parent)
    panel.set_protocol("v4")
    panel.set_connection_snapshot(ConnectionSnapshot(
        state="waiting_selection", devices=(DeviceSnapshot("one", "郊狼", True),)))
    assert not panel.device_selector.isHidden()
    panel.set_protocol("v3")
    assert panel.device_selector.isHidden()
    assert not panel.ws_port.isHidden() and panel.v4_relay_url.isHidden()
    panel.set_connection_snapshot(ConnectionSnapshot(state="ready", bound=True))
    panel.set_protocol("v4")
    panel.set_protocol("v3")
    assert panel.lan_notice.isHidden() and panel.qr_frame.isHidden()
    panel.set_connection_snapshot(ConnectionSnapshot(state="waiting_app"))
    assert not panel.lan_notice.isHidden() and not panel.qr_frame.isHidden()
    parent.close()
