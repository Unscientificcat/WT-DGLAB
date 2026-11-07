"""8111 遥测失效时的安全归零回归测试。"""


import requests

from src.game_reader import GameReader


class FakeResponse:
    """提供固定 JSON 响应的简易 HTTP 响应对象。"""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        """返回预设 JSON 数据。"""
        return self.payload


class FakeSession:
    """按 URL 返回预设响应，记录读取顺序。"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, timeout, **kwargs):
        """模拟 requests.Session.get。"""
        self.calls.append(url)
        return self.responses[url]


def make_reader(responses):
    """创建使用伪 HTTP 会话的游戏读取器。"""
    reader = GameReader()
    reader._session = FakeSession(responses)
    return reader


def test_menu_stale_indicators_do_not_create_tank_data():
    """游戏菜单的残留速度不可被当成有效坦克遥测。"""
    reader = make_reader({
        GameReader.STATE_URL: FakeResponse({"valid": False}),
        GameReader.MAP_INFO_URL: FakeResponse({"valid": False}),
        GameReader.INDICATORS_URL: FakeResponse({
            "valid": True,
            "army": "tank",
            "speed": 68.0,
        }),
    })

    state = reader.fetch()

    assert not state.connected
    assert state.link_ok
    assert state.vehicle_type == ""
    assert state.tank is None
    assert reader._session.calls == [
        GameReader.STATE_URL,
        GameReader.MAP_INFO_URL,
    ]


def test_unreachable_game_reports_link_down():
    """战争雷霆未运行（连接拒绝）时 link_ok 为 False。"""

    class RaisingSession:
        def get(self, url, timeout, **kwargs):
            raise requests.ConnectionError("connection refused")

    reader = GameReader()
    reader._session = RaisingSession()

    state = reader.fetch()

    assert not state.link_ok
    assert not state.connected


def test_session_ignores_system_proxy():
    """8111 回环请求必须绕过系统代理与代理环境变量。

    加速器/Clash 设置系统代理后若未放行 127.0.0.1，浏览器因内置绕行
    仍可打开 8111，但走代理的 requests 会全部失败——状态灯误报未连接。
    """
    reader = GameReader()

    assert reader._session.trust_env is False
    assert reader._session.proxies == {"http": None, "https": None}


def test_link_failure_reason_logged_once_per_cause():
    """8111 失败原因按防抖记录：同一原因只写一次，恢复后允许再次记录。"""

    class FlakySession:
        def __init__(self):
            self.fail = True

        def get(self, url, timeout, **kwargs):
            if self.fail:
                raise requests.ConnectionError("connection refused")
            return FakeResponse({"valid": False})

    reader = GameReader()
    session = FlakySession()
    reader._session = session

    reader.fetch()
    reader.fetch()
    assert reader._last_link_error == (
        "ConnectionError: connection refused")

    session.fail = False
    reader.fetch()
    assert reader._last_link_error == ""

    session.fail = True
    reader.fetch()
    assert reader._last_link_error != ""


def test_http_error_status_logged():
    """8111 被其他程序占用（返回非 200）时也计入失败原因。"""
    reader = make_reader({
        GameReader.STATE_URL: FakeResponse({}, status_code=404),
    })

    state = reader.fetch()

    assert not state.link_ok
    assert "404" in reader._last_link_error


def test_active_tank_uses_complete_map_metadata_when_valid_flag_is_omitted():
    """兼容有效地图响应未提供 valid 字段的 8111 版本。"""
    reader = make_reader({
        GameReader.STATE_URL: FakeResponse({"valid": False}),
        GameReader.MAP_INFO_URL: FakeResponse({
            "grid_steps": ["3250.0", "3250.0"],
            "grid_zero": ["-32768.0", "32768.0"],
            "map_generation": "1",
            "map_max": ["32768.0", "32768.0"],
            "map_min": ["-32768.0", "-32768.0"],
        }),
        GameReader.INDICATORS_URL: FakeResponse({
            "valid": True,
            "army": "tank",
            "type": "tankModels/us_m1a1_hc_usmc_sm",
            "speed": 68.0,
        }),
    })

    state = reader.fetch()

    assert state.connected
    assert state.vehicle_type == "tank"
    assert state.tank is not None
    assert state.tank.valid
    assert state.tank.speed_kmh == 68.0


