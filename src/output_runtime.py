"""协议无关的输出意图、期限看门狗和状态发布。"""

import asyncio
import logging
import threading
import time

from .dglab_state import ChannelSnapshot, ConnectionSnapshot, OutputIntent


logger = logging.getLogger(__name__)


class OutputRuntime:
    """由控制器事件循环执行输出，GUI 仅提交不可变意图。"""

    def _init_output_runtime(self):
        self._intent_lock = threading.RLock()
        self._session = 0
        self._revision = 0
        self._epochs = {"A": 0, "B": 0}
        self._intent = None
        self._lease_until = 0.0
        self._intent_mode = False
        self._expired_channels = set()
        self._runtime_state = "idle"
        self._published = ConnectionSnapshot()
        self._channel_errors = {"A": "", "B": ""}
        self._reported_at = {"A": None, "B": None}
        self._targets = {"A": 0, "B": 0}
        self._applied_targets = {"A": None, "B": None}

    def snapshot(self) -> ConnectionSnapshot:
        """返回后台已发布的不可变快照。"""
        with self._intent_lock:
            return self._published

    def select_device(self, slot_id: str) -> None:
        """V3 无设备选择能力；V4 重写此接口。"""
        raise ValueError("V3 协议不支持设备选择")

    def submit_output(self, intent: OutputIntent) -> None:
        """原子提交最新双通道意图，相同内容仅续期，不重复发送。"""
        if not isinstance(intent, OutputIntent):
            raise TypeError("输出必须为 OutputIntent")
        now = time.monotonic()
        with self._intent_lock:
            if not self._running or self._closing or not self._status.bound:
                return
            if (intent.expected_session is not None
                    and intent.expected_session != self._session):
                return
            until = min(now + 1.0, intent.expires_at if intent.expires_at is not None else float("inf"))
            if until <= now:
                return
            previous = self._intent
            changed = (previous is None or bool(self._expired_channels)
                       or (intent.a, intent.b, intent.source)
                       != (previous.a, previous.b, previous.source))
            self._intent_mode = True
            self._intent = intent
            self._lease_until = until
            self._expired_channels.clear()
            if changed:
                self._revision += 1
                if previous is None or previous.source != intent.source:
                    logger.info("输出来源 session=%s revision=%s source=%s deadline=%s",
                                self._session, self._revision, intent.source, until)
                self._cmd_queue.put(("output", None, intent, self._session,
                                     self._revision, dict(self._epochs)))

    def _invalidate_output(self, channel=None):
        with self._intent_lock:
            for name in ((channel,) if channel else ("A", "B")):
                self._epochs[name] += 1
                self._expired_channels.add(name)
                self._targets[name] = 0
                self._applied_targets[name] = None
            self._intent = None

    def _new_session(self):
        with self._intent_lock:
            self._session += 1
            self._invalidate_output()
            self._cmd_queue.clear()
            self._channel_errors = {"A": "", "B": ""}
            self._reported_at = {"A": None, "B": None}
        logger.info("连接会话更新 session=%s", self._session)

    def _output_allowed(self, channel):
        with self._intent_lock:
            return not self._closing and (
                not self._intent_mode or (
                    channel not in self._expired_channels
                    and time.monotonic() < self._lease_until))

    def _queue_latest_target(self, channel):
        """校准只排队标记，执行时再读取目标，避免回放旧采样。"""
        with self._intent_lock:
            if (self._output_allowed(channel)
                    and not getattr(self, "_faulted", {}).get(channel, False)):
                self._cmd_queue.put(("reconcile", channel, self._session,
                                     self._epochs[channel]))

    def _resolve_reconcile(self, command):
        _, channel, session, epoch = command
        with self._intent_lock:
            if (session != self._session or epoch != self._epochs[channel]
                    or not self._output_allowed(channel)):
                return None
            if self._intent is not None:
                target = self._intent.a if channel == "A" else self._intent.b
                value = target.strength
            else:
                value = self._targets[channel]
            return ("strength", channel, value)

    async def _runtime_watchdog(self):
        """独立于 GUI 和网络等待，每 25ms 检查输出期限并发布状态。"""
        while self._running:
            with self._intent_lock:
                expired = (self._intent_mode and time.monotonic() >= self._lease_until
                           and len(self._expired_channels) < 2)
                if expired:
                    logger.info("输出到期 session=%s revision=%s", self._session, self._revision)
                    self.stop_output()
            self._publish_snapshot()
            await asyncio.sleep(0.025)

    def _publish_snapshot(self):
        sent = getattr(self, "_last_strength", getattr(self, "_channel_strength", {}))
        reported = getattr(self, "_app_strength", {})
        limits = getattr(self, "_limits", {})
        muted = getattr(self, "_muted", {})
        channels = [ChannelSnapshot(
            self._targets[ch], sent.get(ch, 0), reported.get(ch), self._reported_at[ch],
            limits.get(ch), muted.get(ch, False),
            self._needs_stop[ch] or self._cmd_queue.has_stop(ch), self._channel_errors[ch])
            for ch in ("A", "B")]
        state = self._runtime_state
        if self._closing:
            state = "stopping"
        elif any(c.error for c in channels):
            state = "error"
        elif self._status.bound:
            state = "recovering" if any(c.pending_stop for c in channels) else "ready"
        elif self._status.error:
            state = "error"
        devices = getattr(self, "_device_snapshots", ())
        snapshot = ConnectionSnapshot(
            self._session, state, self._status.server_running,
            self._status.client_connected, self._status.bound,
            self._status.address, self._status.error, self._qr_url,
            getattr(self, "_slot_id", ""), devices, *channels)
        with self._intent_lock:
            self._published = snapshot
