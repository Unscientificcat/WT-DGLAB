"""无 GUI、无网络的单线程触发状态机。"""

from collections import deque
import logging
import random

from .dglab_state import ChannelTarget, OutputIntent, WaveformConfig
from .game_reader import GameState
from .mapping_engine import MappingEngine
from .trigger_models import GameEvent, Playback, TriggerSnapshot


logger = logging.getLogger("TriggerEngine")
PRIORITY = {"": 0, "idle": 1, "hit": 2, "repair": 3, "kill": 4, "death": 5}
LABELS = {"kill": "⚔ 击杀!", "repair": "🔧 维修中",
          "hit": "🎯 部件损伤!", "idle": "🛑 静止超时，请移动!"}


class TriggerEngine:
    """串行处理采集批次，维护事件资格、生命状态和播放期限。"""

    DATA_TTL = 1.0
    PENDING_TTL = 1.0
    RESPAWN_MOVE_SECONDS = 1.0

    def __init__(self, catalog=None):
        self.catalog = catalog
        self.game = GameState()
        self.mode = "aircraft"
        self.active = None
        self.repair = None
        self.pending = []
        self.journal = deque(maxlen=1024)
        self._sequence = 0
        self._last_active_at = None
        self._last_vehicle = None
        self._damage = None
        self._last_hit = float("-inf")
        self._idle_since = None
        self._idle_target = None
        self._death_blocked = False
        self._repair_blocked = False
        self._move_since = None
        self._revoked = set()
        self._last_diagnostic = ""

    @property
    def recent_vehicle(self):
        """返回最近有效对局的载具类型，临时接口故障不覆盖它。"""
        return self._last_vehicle or ""

    def _record(self, event, decision):
        self.journal.append((event.event_id, event.kind, decision))
        logger.info("事件仲裁 id=%s kind=%s result=%s",
                    event.event_id, event.kind, decision)

    def _event(self, kind, state, now):
        self._sequence += 1
        return GameEvent(f"state:{self._sequence}:{kind}", kind,
                         state.vehicle_type, "tank", now,
                         state.event_session or (),
                         bool(state.event_output_bound))

    def _playback(self, event, config):
        settings = config.tank_events if event.scene == "tank" else config.events
        choices = ([n for n in self.catalog.choices() if n != "恒定"]
                   if self.catalog else [])
        targets = []
        for ch in ("a", "b"):
            name = getattr(settings, f"{event.kind}_wf_{ch}")
            if getattr(settings, f"{event.kind}_random_{ch}", False) and choices:
                name = random.choice(choices)
            strength = getattr(settings, f"{event.kind}_ch_{ch}")
            targets.append(ChannelTarget(strength, WaveformConfig(name)))
        deadline = (None if event.kind == "repair" else event.observed_at
                    + getattr(settings, f"{event.kind}_duration"))
        return Playback(event, *targets, deadline)

    def _accept(self, event, config, now):
        if event.mode == "aircraft" and event.scene == "tank" and not config.cas.enabled:
            self._record(event, "CAS 已关闭")
            return
        # 即使死亡输出开关关闭，死亡事实仍须取消旧维修、封锁静止惩罚。
        if event.kind == "death":
            self._death_blocked = event.mode == "tank"
            self._repair_blocked = event.mode == "tank"
            self._idle_since = self._idle_target = self._move_since = None
            self.repair = None
            self._damage = None
            if self.active and self.active.event.kind in {"repair", "hit"}:
                self.active = None
        settings = config.tank_events if event.scene == "tank" else config.events
        if not getattr(settings, f"{event.kind}_enabled", False):
            self._record(event, "功能已关闭")
            return
        playback = self._playback(event, config)
        if playback.deadline is not None and playback.deadline <= now:
            self._record(event, "事件已过期")
            return
        if self._death_blocked and event.kind in {"repair", "hit"}:
            self._record(event, "死亡封锁")
            return
        if event.kind == "repair":
            self.repair = playback
        if self.active and PRIORITY[event.kind] < PRIORITY[self.active.event.kind]:
            self._record(event, "被更高优先级抑制")
            return
        self.active = playback
        self._record(event, "接受")

    def _reset_ground(self):
        self._damage = None
        self._idle_since = self._idle_target = self._move_since = None

    def _expire(self, now):
        if self.active and self.active.deadline is not None and now >= self.active.deadline:
            self._record(self.active.event, "到期结束")
            self.active = None

    def observe(self, state, events, config, now):
        """接收同批遥测和全部 HUD 事件；未知对局最多等待一秒确认。"""
        self._expire(now)
        if config.app.mode != self.mode:
            self.mode = config.app.mode
            self.active = self.repair = None
            self.pending.clear()
            self._death_blocked = self._repair_blocked = False
            self._reset_ground()
        previous = self.game
        self.game = state
        if (previous.sampled_at is not None
                and now - previous.sampled_at > self.DATA_TTL):
            self._reset_ground()
        mission = state.mission_status
        # 兼容手动构造的有效快照；生产采集总是明确设置 mission_status。
        if state.connected:
            mission = "active"
        if mission == "inactive":
            for event in (*self.pending, *events):
                self._record(event, "无有效对局")
            self.active = self.repair = None
            self.pending.clear()
            self._death_blocked = self._repair_blocked = False
            self._last_active_at = None
            self._last_vehicle = None
            self._reset_ground()
            return
        if not state.connected or mission == "unknown":
            self._reset_ground()
            for event in events:
                if self._last_active_at is not None and now - self._last_active_at <= self.PENDING_TTL:
                    self.pending.append(event)
                    self._record(event, "对局暂时未知，等待确认")
                else:
                    self._record(event, "缺少近期有效对局证据")
            retained = []
            for event in self.pending:
                if now - event.observed_at <= self.PENDING_TTL:
                    retained.append(event)
                else:
                    self._record(event, "等待确认超时")
            self.pending = retained
            return
        self._last_active_at = now
        if state.vehicle_type != self._last_vehicle:
            self._reset_ground()
            self.repair = None
            self.active = None
            self._death_blocked = self._repair_blocked = False
            self._last_vehicle = state.vehicle_type
        delayed, self.pending = self.pending, []
        batch = []
        for event in delayed:
            if now - event.observed_at <= self.PENDING_TTL:
                batch.append(event)
            else:
                self._record(event, "等待确认超时")
        batch.extend(events)
        ground = self.mode == "tank" and state.vehicle_type == "tank"
        tank = state.tank if ground else None
        if tank and tank.valid:
            # 同批死亡优先于维修/损伤；乘员明确从存活变为全灭也提供死亡证据。
            before = previous.tank if previous.vehicle_type == "tank" else None
            if (before and before.crew_alive is True and tank.crew_alive is False
                    and not any(e.kind == "death" for e in batch)
                    and not self._death_blocked):
                batch.append(self._event("death", state, now))
            if not tank.is_repairing:
                self._repair_blocked = False
                self.repair = None
                if self.active and self.active.event.kind == "repair":
                    self.active = None
            elif (config.tank_events.repair_enabled
                  and not self._repair_blocked and self.repair is None
                  and not any(e.kind == "repair" for e in batch)):
                batch.append(self._event("repair", state, now))
            current = tank.damaged_parts
            if self._damage is not None and current - self._damage:
                if now - self._last_hit >= config.tank_events.hit_cooldown:
                    batch.append(self._event("hit", state, now))
                    self._last_hit = now
            self._damage = current
        else:
            self._reset_ground()
            self.repair = None
            if self.active and self.active.event.kind == "repair":
                self.active = None
        # 从高到低处理，同级保持观测顺序；低级瞬时事件只记录，不积压。
        for event in sorted(batch, key=lambda e: -PRIORITY[e.kind]):
            self._accept(event, config, now)
        if tank and tank.valid:
            self._update_idle(tank, config.tank, now)

    def _update_idle(self, tank, settings, now):
        if tank.crew_alive is False:
            self._idle_since = self._idle_target = self._move_since = None
            return
        if abs(tank.speed_kmh) >= settings.idle_speed_max:
            self._idle_since = self._idle_target = None
            if self._death_blocked:
                if self._move_since is None:
                    self._move_since = now
                elif now - self._move_since >= self.RESPAWN_MOVE_SECONDS:
                    self._death_blocked = False
                    logger.info("死亡封锁解除：已确认持续移动")
            return
        self._move_since = None
        if not settings.idle_enabled or tank.is_repairing:
            self._idle_since = self._idle_target = None
            return
        if self._death_blocked:
            return
        if self._idle_since is None:
            self._idle_since = now
        if now - self._idle_since >= settings.idle_timeout_s and self._idle_target is None:
            choices = ([n for n in self.catalog.choices() if n != "恒定"]
                       if self.catalog else [])
            self._idle_target = tuple(ChannelTarget(
                getattr(settings, f"idle_ch_{ch}"), WaveformConfig(
                    random.choice(choices) if choices and getattr(settings, f"idle_random_{ch}")
                    else getattr(settings, f"idle_wf_{ch}"))) for ch in ("a", "b"))

    def _normal(self, config):
        state = self.game
        if self.mode == "tank" and state.vehicle_type == "tank":
            data, settings = state.tank, config.tank
            values = (MappingEngine.map_tank(
                data.speed_kmh, settings.speed_min, settings.speed_max,
                settings.channel_a_max, settings.channel_b_max,
                settings.curve, settings.curve_steepness)
                if data and data.valid and settings.enabled else (0, 0))
        else:
            data = state.aircraft
            settings = config.cas if self.mode == "tank" else config.aircraft
            values = (MappingEngine.map_aircraft(
                data.gforce, settings.gforce_min, settings.gforce_max,
                settings.channel_a_max, settings.channel_b_max,
                settings.curve, settings.curve_steepness)
                if data and data.valid and settings.enabled else (0, 0))
        return tuple(ChannelTarget(value, WaveformConfig(
            getattr(settings, f"waveform_{ch}"),
            getattr(settings, f"random_enabled_{ch}"),
            getattr(settings, f"random_min_{ch}"),
            getattr(settings, f"random_max_{ch}")))
            for ch, value in zip(("a", "b"), values))

    def tick(self, config, session, bound, now) -> TriggerSnapshot:
        """独立于 GUI 刷新到期状态并生成完整双通道计划。"""
        self._expire(now)
        if self.active:
            settings = config.tank_events if self.active.event.scene == "tank" else config.events
            if (not getattr(settings, f"{self.active.event.kind}_enabled", False)
                    or (self.active.event.mode == "aircraft" and self.mode == "tank"
                        and not config.cas.enabled)):
                self.active = None
        if not config.tank_events.repair_enabled:
            self.repair = None
        if self.active is None and self.repair and not self._repair_blocked:
            self.active = self.repair
        self._revoked.intersection_update(
            p.event.event_id for p in (self.active, self.repair) if p is not None)
        # 资格撤销不可逆；绑定、重连均不得重新授权旧事件或旧维修。
        for playback in (self.active, self.repair):
            if playback and (not bound or playback.event.session != session):
                self._revoked.add(playback.event.event_id)
        state = self.game
        fresh = (state.connected and state.sampled_at is not None
                 and now < state.sampled_at + self.DATA_TTL)
        a, b = self._normal(config)
        kind, mode, remaining, label = "", "", 0.0, ""
        deadline = ((state.sampled_at or 0.0) + self.DATA_TTL)
        allowed = fresh and bound
        source = "normal"
        identified = None
        if self.active:
            playback = self.active
            event = playback.event
            a, b = playback.a, playback.b
            kind, mode = event.kind, event.mode
            identified = event.observed_at
            remaining = (max(0.0, playback.deadline - now)
                         if playback.deadline is not None else 0.0)
            if playback.deadline is not None:
                deadline = min(deadline, playback.deadline)
            allowed = (allowed and event.bound and event.session == session
                       and event.event_id not in self._revoked)
            source = f"{'event' if allowed else 'preview'}:{event.event_id}"
            label = ("💀 坠毁!" if mode == "aircraft" else "💀 被摧毁!") if kind == "death" else LABELS[kind]
            if playback.deadline is not None:
                label += f" ({remaining:.1f}s)"
        elif fresh and self._idle_target and config.tank.idle_enabled:
            a, b = self._idle_target
            kind, mode, label = "idle", "tank", LABELS["idle"]
            source = "idle"
        if not fresh:
            a, b = (a, b) if self.active else (ChannelTarget(), ChannelTarget())
        output_a, output_b = (a, b) if allowed else (ChannelTarget(), ChannelTarget())
        diagnostic = ("对局状态暂时未知，已停止设备输出" if state.mission_status == "unknown"
                      else "遥测已过期，已停止设备输出" if state.connected and not fresh
                      else "")
        if state.tank and not state.tank.repair_supported:
            diagnostic = diagnostic or "维修状态：当前接口未提供"
        if diagnostic != self._last_diagnostic:
            self._last_diagnostic = diagnostic
            if diagnostic:
                logger.info("触发诊断：%s", diagnostic)
        intent = OutputIntent(output_a, output_b, source, deadline,
                              session[1] if session else None, identified)
        return TriggerSnapshot(state, self.mode, kind, mode, remaining,
                               a.strength, b.strength, label, allowed,
                               intent, diagnostic, a.waveform.name, b.waveform.name)
