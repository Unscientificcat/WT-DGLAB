"""游戏数据读取模块 — 通过 HTTP 轮询战争雷霆 127.0.0.1:8111 获取实时遥测数据

参考：
    WarThunder Python 包: https://github.com/PowerBroker2/WarThunder
    localhost 文档: https://github.com/lucasvmx/WarThunder-localhost-documentation

端点说明：
    /state  — 主要遥测数据（载具状态、过载、速度等）
    /indicators — HUD 指示器数据（包含坦克损伤信息）
    /hudmsg — HUD 消息日志（击杀、损伤事件等）
"""

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger("GameReader")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class AircraftData:
    """飞机模式数据"""
    valid: bool = False              # 数据是否有效（是否在游戏中）
    gforce: float = 0.0              # 当前过载 (G)，对应 ny 字段
    speed_kmh: float = 0.0           # 当前速度 (km/h)
    altitude_m: float = 0.0          # 当前高度 (m)
    vehicle_name: str = ""           # 载具名称


@dataclass
class TankDamagePart:
    """坦克单个部件损伤"""
    name: str = ""                   # 部件名称
    health: float = 100.0            # 剩余血量百分比 (0-100)
    is_destroyed: bool = False       # 是否已完全损毁


@dataclass
class TankData:
    """坦克模式数据"""
    valid: bool = False
    vehicle_name: str = ""
    speed_kmh: float = 0.0           # 当前速度 (km/h)
    is_repairing: bool = False       # 是否维修中
    repair_time: float = 0.0         # 剩余维修秒数


@dataclass
class GameState:
    """综合游戏状态"""
    connected: bool = False          # 是否处于已确认的有效对局，可安全驱动输出
    link_ok: bool = False            # 战争雷霆 8111 遥测服务是否可达（主菜单也为 True）
    vehicle_type: str = ""           # "aircraft" / "tank" / "" (未知)
    aircraft: Optional[AircraftData] = None
    tank: Optional[TankData] = None
    raw_state: dict = field(default_factory=dict)
    raw_indicators: dict = field(default_factory=dict)
    raw_map_info: dict = field(default_factory=dict)


# ============================================================
# GameReader — HTTP 轮询
# ============================================================

class GameReader:
    """战争雷霆数据读取器

    用法:
        reader = GameReader()
        state = reader.fetch()
        if state.connected:
            print(f"G-force: {state.aircraft.gforce} G")
    """

    STATE_URL = "http://127.0.0.1:8111/state"
    INDICATORS_URL = "http://127.0.0.1:8111/indicators"
    MAP_INFO_URL = "http://127.0.0.1:8111/map_info.json"
    HUDMSG_URL = "http://127.0.0.1:8111/hudmsg"
    TIMEOUT = 0.5  # 请求超时（秒），127.0.0.1 通常 <10ms

    def __init__(self):
        # trust_env=False：8111 是本机回环服务，绝不能走系统代理或
        # HTTP_PROXY 环境变量（加速器/Clash 设置系统代理后未放行 127.0.0.1
        # 会导致全部请求失败，而浏览器自带回环绕行不受影响）。
        self._session = requests.Session()
        self._session.trust_env = False
        self._session.proxies = {"http": None, "https": None}
        self._last_link_error: str = ""
        self._endpoint_states = {}
        self._hud_local = threading.local()
        self._last_mission_state = None

    def _report_endpoint(self, url, key, message, *, failed=False) -> None:
        """按接口和原因去重，耗时变化本身不触发重复日志。"""
        previous = self._endpoint_states.get(url)
        if previous == key:
            return
        self._endpoint_states[url] = key
        prefix = "接口异常" if failed else "接口正常/恢复"
        (logger.warning if failed else logger.info)(
            "%s：%s；%s", prefix, url, message)

    def _fetch_json(self, session, url, *, params=None):
        """记录请求证据，拒绝重定向及非对象 JSON，不输出完整遥测正文。"""
        started = time.monotonic()
        options = {"timeout": self.TIMEOUT, "allow_redirects": False}
        if params is not None:
            options["params"] = params
        response = None
        try:
            response = session.get(url, **options)
            elapsed = (time.monotonic() - started) * 1000
            content_type = getattr(response, "headers", {}).get("Content-Type", "未提供")
            evidence = (f"HTTP {response.status_code}；耗时={elapsed:.0f}ms；"
                        f"超时阈值={self.TIMEOUT}s；Content-Type={content_type}")
            if response.status_code != 200:
                reason = f"HTTP {response.status_code}"
                hint = "接口返回非成功状态，检查接口路径、拦截或端口占用"
                if 300 <= response.status_code < 400:
                    hint = "出现重定向，已拒绝跟随；本机遥测接口通常不需要重定向"
                self._report_endpoint(url, reason, evidence + "；" + hint, failed=True)
                if url == self.STATE_URL:
                    self._log_link_error(reason)
                return None
            try:
                data = response.json()
            except ValueError as error:
                reason = f"JSON 解析失败：{type(error).__name__}"
                self._report_endpoint(
                    url, "invalid_json", evidence + "；" + reason
                    + "；可能返回了 HTML/拦截页或截断响应", failed=True)
                if url == self.STATE_URL:
                    self._log_link_error(reason)
                return None
            if not isinstance(data, dict):
                reason = f"JSON 顶层类型={type(data).__name__}，预期为对象"
                self._report_endpoint(url, reason, evidence + "；" + reason, failed=True)
                if url == self.STATE_URL:
                    self._log_link_error(reason)
                return None
            slow = elapsed >= self.TIMEOUT * 800
            self._report_endpoint(
                url, "slow" if slow else "ok", evidence
                + ("；接近超时阈值，游戏负载可能导致间歇超时" if slow else "；JSON 对象解析成功"))
            return data
        except requests.RequestException as error:
            elapsed = (time.monotonic() - started) * 1000
            reason = re.sub(r"0x[0-9a-fA-F]+", "0x…", f"{type(error).__name__}: {error}")
            if isinstance(error, requests.ConnectTimeout):
                hint = "建立连接超时，检查监听服务或按进程拦截"
            elif isinstance(error, requests.ReadTimeout):
                hint = "响应读取超时，服务可能繁忙；后台诊断会比较更长超时"
            elif isinstance(error, requests.exceptions.ProxyError):
                hint = "发生代理错误，检查实际运行版本与代理策略"
            elif isinstance(error, requests.Timeout):
                hint = "请求超时，检查游戏负载和接口响应"
            else:
                hint = "检查服务未监听、连接被拒绝/重置或安全软件拦截；仅凭此错误无法确定防火墙原因"
            self._report_endpoint(
                url, reason, f"{reason}；耗时={elapsed:.0f}ms；"
                f"超时阈值={self.TIMEOUT}s；{hint}", failed=True)
            if url == self.STATE_URL:
                self._log_link_error(f"{type(error).__name__}: {error}")
            return None
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()

    def fetch_hudmsg(self, last_dmg_id: int = 0) -> list:
        """获取增量 hudmsg 损伤记录（线程安全，使用独立请求）

        Args:
            last_dmg_id: 上次获取到的最后一条 damage id，只返回此 id 之后的新记录

        Returns:
            [{"id": N, "msg": "...", ...}, ...]  新 damage 记录列表
        """
        _success, records = self.fetch_hudmsg_with_status(last_dmg_id)
        return records

    def fetch_hudmsg_with_status(self, last_dmg_id: int = 0) -> tuple[bool, list]:
        """获取增量 HUD 记录，并区分空结果与请求失败。"""
        if not hasattr(self._hud_local, "session"):
            session = requests.Session()
            session.trust_env = False
            session.proxies = {"http": None, "https": None}
            self._hud_local.session = session
        data = self._fetch_json(
            self._hud_local.session, self.HUDMSG_URL,
            params={"lastEvt": 0, "lastDmg": last_dmg_id})
        if data is None:
            return False, []
        records = data.get("damage", [])
        if not isinstance(records, list):
            self._report_endpoint(self.HUDMSG_URL + "#damage", "invalid_damage",
                                  "damage 字段不是列表，无法读取事件", failed=True)
            return False, []
        if self.HUDMSG_URL + "#damage" in self._endpoint_states:
            self._report_endpoint(self.HUDMSG_URL + "#damage", "ok", "damage 列表已恢复")
        return True, records

    def fetch(self) -> GameState:
        """获取一次游戏数据，返回 GameState

        如果 WT 未运行或连接失败，返回 connected=False 的状态
        """
        state = GameState()

        data = self._fetch_json(self._session, self.STATE_URL)
        if data is None:
            return state
        state.raw_state = data

        # /state 可达即代表战争雷霆遥测服务在线（主菜单同样为 True），
        # 仅用于状态栏连接显示；对局判定仍以 map_info 为准。
        state.link_ok = True
        self._last_link_error = ""

        # /indicators 会在退出对局后保留最后一帧数据，不能单独用于驱动设备。
        # /map_info.json 在未处于对局时返回 {"valid": false}；有效对局则
        # 返回 valid=true 或完整地图元数据。读取失败时按无效处理，优先保证归零。
        map_data = self._fetch_json(self._session, self.MAP_INFO_URL)
        state.raw_map_info = map_data or {}
        active = self._is_active_mission(state.raw_map_info)
        mission_state = (active, "地图接口失败" if map_data is None else
                         "valid=false" if map_data.get("valid") is False else
                         "已确认有效对局" if active else "缺少有效对局标记/地图字段")
        if mission_state != self._last_mission_state:
            self._last_mission_state = mission_state
            logger.info("连接判定：/state 正常，link_ok=True；对局有效=%s；%s；"
                        "机库/主菜单可显示已连接，无有效对局时仍保持零输出",
                        active, mission_state[1])
        if not active:
            return state

        state.connected = True

        # 同时获取 indicators（陆战中 state 可能为 {"valid": false}，但 indicators 有数据）
        state.raw_indicators = self._fetch_json(self._session, self.INDICATORS_URL) or {}

        # 解析载具类型（综合 state + indicators）
        vehicle_type = self._detect_vehicle_type(state.raw_state,
                                                  state.raw_indicators)
        state.vehicle_type = vehicle_type

        if vehicle_type == "aircraft":
            state.aircraft = self._parse_aircraft(state.raw_state)
        elif vehicle_type == "tank":
            state.tank = self._parse_tank(state.raw_state, state.raw_indicators)

        return state

    def _log_link_error(self, message: str) -> None:
        """记录 8111 不可达原因；同一原因只记录一次，恢复后允许再次记录。

        未开游戏时轮询每 200ms 失败一次，直接逐条写会刷爆日志，
        因此仅在原因变化时输出。
        """
        # requests 异常包含每次新建连接对象的地址，不把地址变化当成新故障。
        message = re.sub(r"0x[0-9a-fA-F]+", "0x…", message)
        if message == self._last_link_error:
            return
        self._last_link_error = message
        logger.warning(f"战争雷霆 8111 不可达: {message}")

    @staticmethod
    def _is_active_mission(map_info_json: dict) -> bool:
        """根据地图端点确认当前是否仍在有效对局中。

        新版接口在无效时返回 ``{"valid": false}``，有效时通常返回
        ``valid: true``。部分版本的有效响应不含 ``valid``，但会包含完整的
        地图边界数据，因此也作为有效对局处理。
        """
        if not isinstance(map_info_json, dict):
            return False

        valid = map_info_json.get("valid")
        if isinstance(valid, bool):
            return valid

        required_keys = {
            "grid_steps", "grid_zero", "map_generation", "map_max", "map_min",
        }
        return required_keys.issubset(map_info_json)

    # ============================================================
    # 内部解析方法
    # ============================================================

    def _detect_vehicle_type(self, state_json: dict,
                              indicators_json: dict = None) -> str:
        """综合 /state 和 /indicators 数据判断载具类型"""
        if indicators_json is None:
            indicators_json = {}

        # 方法1：indicators 中有 "army" 字段直接告知载具类型
        army = str(indicators_json.get("army", "")).lower()
        if army == "tank":
            return "tank"
        if army in ("aircraft", "plane"):
            return "aircraft"

        # 方法2：indicators 中的 type 字段（格式如 "tankModels/..."）
        ind_type = str(indicators_json.get("type", "")).lower()
        if ind_type.startswith("tank"):
            return "tank"
        if ind_type.startswith("aircraft") or ind_type.startswith("plane"):
            return "aircraft"

        # 方法3：state 数据中的关键字段
        data_keys_lower = set(k.lower() for k in state_json.keys())

        aircraft_keys = {"ny", "m", "aoa, deg", "ias, km/h", "tas, km/h",
                         "aileron, %", "elevator, %", "rudder, %", "vy, m/s",
                         "h, m"}
        if aircraft_keys & data_keys_lower:
            return "aircraft"

        # 坦克：indicators 中有乘员状态字段
        tank_keys = {"gunner_state", "driver_state", "commander_state",
                     "loader_state", "stabilizer", "crew_total",
                     "first_stage_ammo"}
        ind_keys_lower = set(k.lower() for k in indicators_json.keys())
        if tank_keys & ind_keys_lower:
            return "tank"

        # 方法4：valid 列表兼容旧格式
        valid_fields = state_json.get("valid", [])
        if isinstance(valid_fields, list) and valid_fields:
            valid_set = set(str(v).lower() for v in valid_fields)
            if "ny" in valid_set or "m" in valid_set:
                return "aircraft"
            for tf in tank_keys:
                if tf in valid_set:
                    return "tank"

        return ""

    def _parse_aircraft(self, state_json: dict) -> AircraftData:
        """解析飞机状态数据"""
        data = AircraftData()

        # valid 字段指示数据是否有效
        if "valid" in state_json:
            # valid 可能是 bool 或者 list
            if isinstance(state_json["valid"], bool):
                data.valid = state_json["valid"]
            elif isinstance(state_json["valid"], list):
                data.valid = len(state_json["valid"]) > 0
        else:
            data.valid = True

        # 过载 — 法向加速度 ny（单位：G）
        # 字段名可能是 "ny" 或 "Ny"
        ny = state_json.get("ny", state_json.get("Ny", None))
        if ny is not None:
            try:
                data.gforce = abs(float(ny))
            except (ValueError, TypeError):
                data.gforce = 0.0

        # 速度 — 优先用 IAS，其次 TAS（单位已为 km/h）
        ias = state_json.get("IAS, km/h", None)
        tas = state_json.get("TAS, km/h", None)
        if ias is not None:
            try:
                data.speed_kmh = float(ias)
            except (ValueError, TypeError):
                pass
        elif tas is not None:
            try:
                data.speed_kmh = float(tas)
            except (ValueError, TypeError):
                pass

        # 高度 (m)
        h = state_json.get("H, m", state_json.get("H", None))
        if h is not None:
            try:
                data.altitude_m = float(h)
            except (ValueError, TypeError):
                pass

        # 载具名称
        data.vehicle_name = str(state_json.get("type", ""))

        return data

    def _parse_tank(self, state_json: dict, indicators_json: dict) -> TankData:
        """解析坦克状态 — 提取速度数据"""
        data = TankData()
        data.valid = bool(indicators_json.get("valid", False))
        data.vehicle_name = str(indicators_json.get("type", ""))

        if indicators_json:
            data.speed_kmh = self._safe_float(indicators_json.get("speed"))
            data.is_repairing = (
                self._safe_float(indicators_json.get("is_repairing")) > 0
            )
            data.repair_time = self._safe_float(
                indicators_json.get("repair_time")
            )

        return data

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """将接口字段转换为有限浮点数，异常值回退为默认值。"""
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return result if math.isfinite(result) else default

    def _extract_damage_from_indicators(self, indicators_json: dict) -> list:
        """从 /indicators 数据中提取部件/乘员损伤

        /indicators 实际字段：
        - gunner_state, driver_state, commander_state, loader_state: 0=存活, 1=阵亡
        - crew_current / crew_total: 当前/总乘员数
        - 模块损伤字段名因版本而异，以 _state 后缀为主
        """
        parts = []

        # 乘员状态（0=存活, !=0 阵亡）
        crew_fields = [
            ("gunner_state", "炮手"),
            ("driver_state", "驾驶员"),
            ("commander_state", "车长"),
            ("loader_state", "装填手"),
        ]
        for field, display_name in crew_fields:
            if field in indicators_json:
                val = indicators_json[field]
                # _state 字段：0=完好，非0=损毁
                destroyed = (abs(float(val)) > 0.001)
                part = TankDamagePart(
                    name=display_name,
                    health=0.0 if destroyed else 100.0,
                    is_destroyed=destroyed,
                )
                parts.append(part)

        # 额外模块状态字段
        module_fields = [
            ("engine_state", "引擎"),
            ("transmission_state", "变速箱"),
            ("tracks_state", "履带"),
            ("turret_state", "炮塔"),
            ("gun_state", "主炮"),
            ("breech_state", "炮闩"),
            ("barrel_state", "炮管"),
        ]
        for field, display_name in module_fields:
            if field in indicators_json:
                val = indicators_json[field]
                destroyed = (abs(float(val)) > 0.001)
                part = TankDamagePart(
                    name=display_name,
                    health=0.0 if destroyed else 100.0,
                    is_destroyed=destroyed,
                )
                parts.append(part)

        return parts

    def _extract_damage_from_state(self, state_json: dict) -> list:
        """从 /state 数据中兜底提取损伤信息"""
        # /state 中坦克相关字段较少，主要看 indicators
        # 这里做最简兜底
        parts = []

        # 检查是否有 damage 相关字段
        damage_fields = [k for k in state_json.keys()
                        if "damage" in k.lower() or "health" in k.lower()
                        or "hp" in k.lower()]

        for field in damage_fields:
            val = state_json[field]
            name = field.replace("_", " ").replace("health", "").strip()
            part = self._parse_part_value(name, val)
            parts.append(part)

        return parts

    def _parse_part_value(self, name: str, val) -> TankDamagePart:
        """将字段值解析为 TankDamagePart

        _state 字段: 0 = 正常, 非0 = 损毁
        其他字段：bool, 比例 0-1, 或百分比 0-100
        """
        part = TankDamagePart(name=name)

        if isinstance(val, bool):
            part.is_destroyed = not val
            part.health = 0.0 if part.is_destroyed else 100.0
        elif isinstance(val, (int, float)):
            # _state 字段：0=完好，非0=损毁
            if name.endswith("_state") or name.endswith("状态"):
                part.is_destroyed = (abs(val) > 0.001)
                part.health = 0.0 if part.is_destroyed else 100.0
            elif val <= 1.0 and val >= 0:
                # 比例格式 0-1
                part.health = val * 100.0
                part.is_destroyed = (val <= 0.01)
            else:
                # 百分比格式 0-100
                part.health = float(val)
                part.is_destroyed = (val <= 1.0)

        return part
