"""战争雷霆 HUD 事件检测器。

统一管理跨对局 HUD 游标、击杀/被击落文本匹配和维修边沿检测。
"""

import logging

from .game_reader import GameReader, GameState


logger = logging.getLogger("EventDetector")

ZERO_WIDTH_CHARS = frozenset("​‌‍‎‏⁠﻿")
DESTROY_KEYWORDS = ("击落了", "击毁了")


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
             aircraft_events, tank_events) -> dict:
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

        mode = state.vehicle_type or current_mode
        if mode == "aircraft":
            event_config = aircraft_events
            self._repair_active = False
        elif mode == "tank":
            event_config = tank_events
        else:
            self._repair_active = False
            return {}

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

            is_kill = any(
                keyword in message
                and player_name in message.split(keyword, 1)[0]
                for keyword in DESTROY_KEYWORDS
            )
            is_death = any(
                keyword in message
                and player_name in message.split(keyword, 1)[1]
                for keyword in DESTROY_KEYWORDS
            )
            if not is_death and "已坠毁" in message:
                is_death = True

            if is_kill and getattr(event_config, "kill_enabled", False):
                result = self._build_event("kill", mode, event_config)
            elif is_death and getattr(event_config, "death_enabled", False):
                result = self._build_event("death", mode, event_config)

        return result

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
        """移除战争雷霆 HUD 文本中的 Unicode 零宽字符。"""
        return "".join(char for char in text if char not in ZERO_WIDTH_CHARS)
