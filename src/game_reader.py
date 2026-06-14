"""游戏数据读取模块 — 通过 HTTP 轮询战争雷霆 127.0.0.1:8111 获取实时遥测数据

参考：
    WarThunder Python 包: https://github.com/PowerBroker2/WarThunder
    localhost 文档: https://github.com/lucasvmx/WarThunder-localhost-documentation

端点说明：
    /state  — 主要遥测数据（载具状态、过载、速度等）
    /indicators — HUD 指示器数据（包含坦克损伤信息）
    /hudmsg — HUD 消息日志（击杀、损伤事件等）
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import requests


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
    connected: bool = False          # WT 是否在运行且可连接
    vehicle_type: str = ""           # "aircraft" / "tank" / "" (未知)
    aircraft: Optional[AircraftData] = None
    tank: Optional[TankData] = None
    raw_state: dict = field(default_factory=dict)
    raw_indicators: dict = field(default_factory=dict)


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
    HUDMSG_URL = "http://127.0.0.1:8111/hudmsg"
    TIMEOUT = 0.5  # 请求超时（秒），127.0.0.1 通常 <10ms

    def __init__(self):
        self._session = requests.Session()

    def fetch_hudmsg(self, last_dmg_id: int = 0) -> list:
        """获取增量 hudmsg 损伤记录（线程安全，使用独立请求）

        Args:
            last_dmg_id: 上次获取到的最后一条 damage id，只返回此 id 之后的新记录

        Returns:
            [{"id": N, "msg": "...", ...}, ...]  新 damage 记录列表
        """
        try:
            resp = requests.get(
                self.HUDMSG_URL,
                params={"lastEvt": 0, "lastDmg": last_dmg_id},
                timeout=self.TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("damage", [])
        except Exception:
            pass
        return []

    def fetch(self) -> GameState:
        """获取一次游戏数据，返回 GameState

        如果 WT 未运行或连接失败，返回 connected=False 的状态
        """
        state = GameState()

        try:
            resp = self._session.get(self.STATE_URL, timeout=self.TIMEOUT)
            if resp.status_code != 200:
                return state
            state.raw_state = resp.json()
        except (requests.ConnectionError, requests.Timeout,
                requests.RequestException, json.JSONDecodeError):
            return state

        # 标记已连接
        state.connected = True

        # 同时获取 indicators（陆战中 state 可能为 {"valid": false}，但 indicators 有数据）
        try:
            ind_resp = self._session.get(self.INDICATORS_URL,
                                         timeout=self.TIMEOUT)
            if ind_resp.status_code == 200:
                state.raw_indicators = ind_resp.json()
        except Exception:
            pass

        # 解析载具类型（综合 state + indicators）
        vehicle_type = self._detect_vehicle_type(state.raw_state,
                                                  state.raw_indicators)
        state.vehicle_type = vehicle_type

        if vehicle_type == "aircraft":
            state.aircraft = self._parse_aircraft(state.raw_state)
        elif vehicle_type == "tank":
            state.tank = self._parse_tank(state.raw_state, state.raw_indicators)

        return state

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
            data.speed_kmh = float(indicators_json.get("speed", 0))
            data.is_repairing = (indicators_json.get("is_repairing") is not None
                                 and float(indicators_json.get("is_repairing", 0)) > 0)
            data.repair_time = float(indicators_json.get("repair_time", 0))

        return data

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
