"""连接诊断覆盖接口差异、超时、代理、进程证据及安全边界。"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src import connection_diagnostics as diagnostics
from src.game_reader import GameReader


def response(payload=None, *, status=200, body=None, content_type="application/json"):
    """构造真实 requests 响应类型，模拟解析及上下文管理。"""
    result = requests.Response()
    result.status_code = status
    result._content = body if body is not None else json.dumps(payload).encode()
    result._content_consumed = True
    result.headers["Content-Type"] = content_type
    return result


def reader_with_state(state_response):
    """使用隔离响应模拟机库，不访问用户运行中的游戏。"""
    reader = GameReader()
    reader._session = Mock()
    reader._session.get.side_effect = lambda url, **kwargs: (
        state_response if url == reader.STATE_URL else response({"valid": False}))
    return reader


@pytest.mark.parametrize("state_response,reason", [
    (response({}, status=403), "HTTP 403"),
    (response({}, status=302), "重定向"),
    (response(body=b"<html>blocked</html>", content_type="text/html"), "JSON 解析失败"),
    (response([]), "JSON 顶层类型=list"),
    (response(None), "JSON 顶层类型=NoneType"),
])
def test_unusable_state_is_identified_and_deduplicated(caplog, state_response, reason):
    caplog.set_level(logging.INFO)
    reader = reader_with_state(state_response)
    assert not reader.fetch().link_ok
    count = len(caplog.records)
    assert not reader.fetch().link_ok
    assert len(caplog.records) == count
    assert reason in caplog.text
    assert "耗时=" in caplog.text
    assert "Content-Type=" in caplog.text
    assert reader._session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("error,reason", [
    (requests.ConnectTimeout("slow"), "建立连接超时"),
    (requests.ReadTimeout("slow"), "响应读取超时"),
    (requests.exceptions.ProxyError("blocked"), "发生代理错误"),
    (requests.ConnectionError("WinError 10061"), "连接被拒绝/重置"),
])
def test_error_category_and_recovery(caplog, error, reason):
    caplog.set_level(logging.INFO)
    reader = reader_with_state(response({"valid": False}))
    reader._session.get.side_effect = error
    assert not reader.fetch().link_ok
    assert reason in caplog.text
    reader._session.get.side_effect = None
    reader._session.get.return_value = response({"valid": False})
    state = reader.fetch()
    assert state.link_ok and not state.connected
    assert "接口正常/恢复" in caplog.text
    assert "机库/主菜单" in caplog.text


def test_map_failure_does_not_turn_service_link_off(caplog):
    caplog.set_level(logging.INFO)
    reader = reader_with_state(response({"valid": True, "Ny": 1.0}))
    reader._session.get.side_effect = lambda url, **kwargs: (
        response({"valid": True}) if url == reader.STATE_URL else response({}, status=500))
    state = reader.fetch()
    assert state.link_ok and not state.connected
    assert "地图接口失败" in caplog.text
    assert reader.MAP_INFO_URL in caplog.text


def test_hud_uses_direct_session_and_logs_invalid_damage(caplog):
    caplog.set_level(logging.INFO)
    reader = GameReader()
    reader._hud_local.session = Mock()
    reader._hud_local.session.get.return_value = response({"damage": "wrong"})
    assert reader.fetch_hudmsg_with_status() == (False, [])
    count = len(caplog.records)
    assert reader.fetch_hudmsg_with_status() == (False, [])
    assert len(caplog.records) == count
    reader._hud_local.session.get.return_value = response({"damage": []})
    assert reader.fetch_hudmsg_with_status() == (True, [])
    assert "damage 列表已恢复" in caplog.text


def test_hud_session_does_not_use_proxy(monkeypatch):
    reader = GameReader()
    session = Mock()
    session.get.return_value = response({"damage": []})
    monkeypatch.setattr(requests, "Session", lambda: session)
    reader.fetch_hudmsg_with_status(123)
    assert session.trust_env is False
    assert session.proxies == {"http": None, "https": None}
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["params"]["lastDmg"] == 123


def test_probe_threshold_cooldown_and_stop(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: clock[0])
    worker = Mock()
    worker.is_alive.return_value = False
    factory = Mock(return_value=worker)
    monkeypatch.setattr(diagnostics.threading, "Thread", factory)
    value = diagnostics.ConnectionDiagnostics()
    value.observe(False)
    value.observe(False)
    factory.assert_not_called()
    value.observe(False)
    factory.assert_called_once()
    for _ in range(30):
        value.observe(False)
    assert factory.call_count == 1
    clock[0] += 60
    value.observe(False)
    assert factory.call_count == 2
    assert value.stop()
    clock[0] += 60
    value.observe(False)
    assert factory.call_count == 2


def test_probe_compares_homepage_and_state_without_changing_reader(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.side_effect = [response(body=b"<html>ok</html>", content_type="text/html"),
                               response({}, status=404)]
    monkeypatch.setattr(requests, "Session", lambda: session)
    value = diagnostics.ConnectionDiagnostics()
    monkeypatch.setattr(value, "_listener_info", lambda: None)
    value._probe()
    assert "首页可达但 /state 不可用" in caplog.text
    assert session.trust_env is False
    for call in session.get.call_args_list:
        assert call.kwargs["timeout"] == (2, 2)
        assert call.kwargs["allow_redirects"] is False


def test_long_timeout_success_is_not_reported_as_proven_cause(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    value = diagnostics.ConnectionDiagnostics()
    monkeypatch.setattr(value, "_probe_http", lambda *args: True)
    monkeypatch.setattr(value, "_listener_info", lambda: None)
    value._probe()
    assert "不能仅据本次探测认定超时是根因" in caplog.text


def test_windows_listener_reports_only_matching_port(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    runner = Mock(side_effect=[
        SimpleNamespace(returncode=0, stdout=(
            " TCP 127.0.0.1:8111 0.0.0.0:0 LISTENING 123\n"
            " TCP 127.0.0.1:9999 0.0.0.0:0 LISTENING 789\n")),
        SimpleNamespace(returncode=0, stdout='"aces.exe","123","Console","1","1 K"'),
    ])
    monkeypatch.setattr(diagnostics.subprocess, "run", runner)
    value = diagnostics.ConnectionDiagnostics()
    value._listener_info()
    assert "aces.exe" in caplog.text and "PID=123" in caplog.text
    assert "789" not in caplog.text
    assert runner.call_count == 2


def test_proxy_evidence_does_not_include_credentials(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(diagnostics, "getproxies", lambda: {
        "http": "http://user:secret@proxy:80", "no": "localhost"})
    diagnostics.ConnectionDiagnostics()
    assert "http" in caplog.text
    assert "secret" not in caplog.text
    assert diagnostics.DIAGNOSTIC_REVISION in caplog.text


def test_diagnostic_start_failure_does_not_stop_polling(caplog, monkeypatch):
    worker = Mock()
    worker.start.side_effect = RuntimeError("线程资源不足")
    monkeypatch.setattr(diagnostics.threading, "Thread", lambda **kwargs: worker)
    value = diagnostics.ConnectionDiagnostics()
    for _ in range(3):
        value.observe(False)
    assert value.stop()
    assert "业务轮询继续" in caplog.text
