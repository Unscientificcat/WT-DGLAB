"""战争雷霆 HUD 事件检测器。

统一管理跨对局 HUD 游标、击杀/被击落文本匹配和维修边沿检测。
"""

import logging
import re
import unicodedata

from .game_reader import GameReader, GameState


logger = logging.getLogger("EventDetector")

ZERO_WIDTH_CHARS = frozenset("​‌‍‎‏⁠﻿")
WHITESPACE_RE = re.compile(r"\s+")

# 被动格式必须优先匹配，避免 "shot down by" 被 "shot down" 抢先识别。
PASSIVE_DESTROY_KEYWORDS = (
    "has been destroyed by",
    "wurde abgeschossen von",
    "wurde zerstört von",
    "shot down by",
    "destroyed by",
    "a été détruit par",
    "abattu par",
    "détruit par",
    "сбит игроком",
    "уничтожен игроком",
    "уничтожен",
    "已被击落,攻击者为",
    "已被击毁,攻击者为",
    "已被摧毁,攻击者为",
    "已被擊落,攻擊者是",
    "已被摧毀,攻擊者為",
)

ACTIVE_DESTROY_KEYWORDS = (
    "shot down",
    "destroyed",
    "abattu",
    "détruit",
    "abgeschossen",
    "zerstört",
    "сбил",
    "уничтожил",
    "击落了",
    "击毁了",
    "擊落了",
    "擊毀了",
    "撃墜されました",
    "によって 撃破されました",
    "によって撃破されました",
)

CRASH_KEYWORDS = (
    "has crashed.",
    "s'est écrasé.",
    "ist abgestürzt.",
    "разбился",
    "已坠毁",
    "已墜毀",
    "は 墜落しました",
    "は墜落しました",
)


class EventDetector:
    """持续消费 HUD 增量记录并返回当前对局的新事件。"""

    def __init__(self, game_reader: GameReader):
        self._game_reader = game_reader
        self._last_dmg_id = 0
        self._cursor_ready = False
        self._repair_active = False

    @property
    def last_dmg_id(self) -> int:
        """返回最后一个已消费的 HUD damage ID。"""
        return self._last_dmg_id

    @property
    def cursor_ready(self) -> bool:
        """返回 HUD 历史基线是否已经成功建立。"""
        return self._cursor_ready

    def poll(self, state: GameState, current_mode: str,
             aircraft_events, tank_events, cas_enabled: bool = True) -> dict:
        """读取一次 HUD 增量并检测事件。

        首次成功读取只建立历史基线；游戏数据无效时继续推进游标但不返回
        事件；有效对局中返回最新的击杀、被击落或维修事件。
        """
        success, records = self._game_reader.fetch_hudmsg_with_status(
            self._last_dmg_id
        )
        if not success:
            if not state.connected:
                self._repair_active = False
            return {}

        was_ready = self._cursor_ready
        new_records = self._consume_records(records)
        self._cursor_ready = True

        if not state.connected:
            self._repair_active = False
            return {}

        if not was_ready:
            logger.info(f"HUD 事件游标已定位到 ID {self._last_dmg_id}")
            return {}

        actual_type = state.vehicle_type
        is_cas = current_mode == "tank" and actual_type == "aircraft"
        if is_cas:
            # 陆战模式上飞机仍使用陆战事件参数，但事件显示保留飞机语义。
            self._repair_active = False
            if not cas_enabled:
                return {}
            mode = "aircraft"
            event_config = tank_events
        elif actual_type == "aircraft" or (
                not actual_type and current_mode == "aircraft"):
            mode = "aircraft"
            event_config = aircraft_events
        elif actual_type == "tank" or (
                not actual_type and current_mode == "tank"):
            mode = "tank"
            event_config = tank_events
        else:
            self._repair_active = False
            return {}

        if mode == "aircraft":
            self._repair_active = False

        repair_event = self._detect_repair(state, mode, event_config)
        hud_event = self._detect_hud_event(new_records, mode, event_config)
        return hud_event or repair_event

    def _consume_records(self, records: list) -> list:
        """按 ID 排序并消费尚未处理的 HUD 记录。"""
        new_records = []
        for record in sorted(records, key=self._record_id):
            record_id = self._record_id(record)
            if record_id <= self._last_dmg_id:
                continue
            self._last_dmg_id = record_id
            new_records.append(record)
        return new_records

    def _detect_repair(self, state: GameState, mode: str, event_config) -> dict:
        """检测坦克维修从未激活到激活的边沿。"""
        tank = state.tank if mode == "tank" else None
        repairing = bool(tank and tank.valid and tank.is_repairing)
        if not repairing:
            self._repair_active = False
            return {}
        if self._repair_active:
            return {}

        self._repair_active = True
        if not getattr(event_config, "repair_enabled", False):
            return {}
        return {
            "kind": "repair",
            "mode": mode,
            "ch_a": event_config.repair_ch_a,
            "ch_b": event_config.repair_ch_b,
            "duration": 60,
            "wf_a": event_config.repair_wf_a,
            "wf_b": event_config.repair_wf_b,
        }

    def _detect_hud_event(self, records: list, mode: str,
                          event_config) -> dict:
        """从新增 HUD 文本中检测击杀和被击落。"""
        player_name = self._normalize(
            str(getattr(event_config, "player_name", ""))
        )
        if not player_name:
            return {}

        result = {}
        for record in records:
            message = self._normalize(str(record.get("msg", "")))
            if player_name not in message:
                continue

            kind = self._classify_hud_message(message, player_name)
            if kind == "kill" and getattr(
                    event_config, "kill_enabled", False):
                result = self._build_event("kill", mode, event_config)
            elif kind == "death" and getattr(
                    event_config, "death_enabled", False):
                result = self._build_event("death", mode, event_config)

        return result

    @staticmethod
    def _classify_hud_message(message: str, player_name: str) -> str:
        """按官方本地化词条判断玩家是击杀方还是被击杀方。"""
        for keyword in PASSIVE_DESTROY_KEYWORDS:
            before, separator, after = message.partition(keyword)
            if not separator:
                continue
            if player_name in before:
                return "death"
            if player_name in after:
                return "kill"

        for keyword in ACTIVE_DESTROY_KEYWORDS:
            before, separator, after = message.partition(keyword)
            if not separator:
                continue
            if player_name in before:
                return "kill"
            if player_name in after:
                return "death"

        for keyword in CRASH_KEYWORDS:
            before, separator, _after = message.partition(keyword)
            if separator and player_name in before:
                return "death"

        return ""

    @staticmethod
    def _build_event(kind: str, mode: str, event_config) -> dict:
        """将匹配结果转换为主控制器使用的标准事件字典。"""
        prefix = "kill" if kind == "kill" else "death"
        return {
            "kind": kind,
            "mode": mode,
            "ch_a": getattr(event_config, f"{prefix}_ch_a"),
            "ch_b": getattr(event_config, f"{prefix}_ch_b"),
            "duration": getattr(event_config, f"{prefix}_duration"),
            "wf_a": getattr(event_config, f"{prefix}_wf_a"),
            "wf_b": getattr(event_config, f"{prefix}_wf_b"),
        }

    @staticmethod
    def _record_id(record: dict) -> int:
        """安全读取 HUD 记录 ID，无效值按 0 处理。"""
        try:
            return int(record.get("id", 0))
        except (AttributeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize(text: str) -> str:
        """统一 HUD 文本的 Unicode、零宽字符、空白和大小写。"""
        normalized = unicodedata.normalize("NFKC", text)
        normalized = "".join(
            char for char in normalized if char not in ZERO_WIDTH_CHARS
        )
        return WHITESPACE_RE.sub(" ", normalized).strip().casefold()
