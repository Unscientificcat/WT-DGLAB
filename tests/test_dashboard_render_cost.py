"""仪表盘动画与样式刷新开销回归测试（代码审查修复 C3）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.main_window import ChannelCard, Dashboard

_APP = QApplication.instance() or QApplication([])


def test_event_glow_style_is_quantized_and_deduplicated(monkeypatch):
    """呼吸边框透明度按 0.05 量化，相同档位不重复 setStyleSheet。"""
    dashboard = Dashboard(None)
    dashboard.event_label.setText("被击中")
    calls = []
    original = dashboard.setStyleSheet
    monkeypatch.setattr(dashboard, "setStyleSheet",
                        lambda style: (calls.append(style), original(style)))
    for glow in (0.51, 0.52, 0.53, 0.54):
        dashboard.setProperty("eventGlow", glow)
        dashboard._update_event_style()
    # 0.35 + glow*0.45 落在 0.58~0.59，量化后同为 0.60，只设置一次
    assert len(calls) == 1
    assert "rgba(236, 141, 167, 0.60)" in calls[0]
    dashboard.show_event("")
    assert calls[-1] == ""


def test_channel_card_same_target_keeps_animation():
    """强度目标不变时不重启进度动画。"""
    card = ChannelCard("A", "channelProgressA")
    card.set_value(80)
    first = card._animation.currentTime()
    started = card._animation.state()
    card.set_value(80)
    assert card._animation.endValue() == 80
    assert card._animation.state() == started
    assert card._animation.currentTime() >= first
    card.set_value(90)
    assert card._animation.endValue() == 90
    assert card.value.text() == "90"


def test_lan_notice_only_shown_for_v3():
    """V3 二维码区域显示局域网开放提示，切到 V4 时隐藏（代码审查修复 D6）。"""
    from PySide6.QtWidgets import QWidget
    from src.gui.main_window import QRWidget
    host = QWidget()
    widget = QRWidget(host)
    assert widget.lan_notice.text() == "V3 服务对局域网开放，请仅在可信网络使用"
    widget.set_protocol("v3")
    assert not widget.lan_notice.isHidden()
    widget.set_protocol("v4")
    assert widget.lan_notice.isHidden()
