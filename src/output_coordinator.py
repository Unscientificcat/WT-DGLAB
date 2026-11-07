"""V3/V4 共用的双通道提交、过期检查和故障恢复协调器。"""

import asyncio
import logging
import time


logger = logging.getLogger("OutputCoordinator")


class OutputCoordinator:
    """适配器提供协议操作；协调过程不依赖任何协议消息格式。"""

    def _intent_valid(self, session, epochs, channels, source):
        """网络等待后重新核对资格；同来源的新目标可在下一轮更新。"""
        with self._intent_lock:
            return (session == self._session and self._status.bound
                    and not self._batch_blocked
                    and (self._intent is None or self._intent.source == source)
                    and all(epochs[ch] == self._epochs[ch]
                            and self._output_allowed(ch)
                            and not self._cmd_queue.has_stop(ch)
                            and not self._faulted[ch] for ch in channels))

    def _queue_interrupted_intent(self, command, channels, intent):
        """单通道撤销保留另一通道；整组过期或替换则停止整组。"""
        _, _, _, session, revision, epochs = command
        with self._intent_lock:
            if session != self._session:
                return
            remaining = tuple(ch for ch in channels
                              if epochs[ch] == self._epochs[ch]
                              and self._output_allowed(ch))
            if self._intent is None and remaining and len(remaining) < len(channels):
                # 单通道 stop_output 清空共享意图，但未撤销另一通道代次。
                self._cmd_queue.put(("output", None, intent, session, revision, epochs))
            else:
                self._cmd_queue.put_stops(channels)

    async def _execute_intent(self, command, execute=None):
        """双通道协调输出；强度均确认后才连续发送首批波形。"""
        _, _, original, session, revision, epochs = command
        started = time.monotonic()
        async with self._output_lock:
            with self._intent_lock:
                intent = self._intent or original
                channels = tuple(ch for ch in ("A", "B")
                                 if epochs[ch] == self._epochs[ch]
                                 and self._output_allowed(ch))
            if (not channels or intent is None
                    or not self._intent_valid(session, epochs, channels, intent.source)):
                return
            source = intent.source
            self._trace_stage("取出执行")
            targets = {"A": intent.a, "B": intent.b}
            changed = tuple(ch for ch in channels
                            if targets[ch] != self._applied_targets[ch]
                            or self._needs_stop[ch])
            if not changed:
                return
            try:
                required = tuple(ch for ch in changed if self._needs_stop[ch])
                if required:
                    await self._stop_batch(required)
                if not self._intent_valid(session, epochs, channels, source):
                    return
                # 停止期间可能收到更新；开始强度阶段前取最新同来源目标。
                intent = self._intent or original
                targets = {"A": intent.a, "B": intent.b}
                revision = self._revision
                changed = tuple(ch for ch in channels
                                if targets[ch] != self._applied_targets[ch]
                                or self._needs_stop[ch])
                self._deferred_channels.update(changed)
                self._applying_intent = True
                self._coordinating_output = True
                for ch in changed:
                    wf = targets[ch].waveform
                    self._set_waveform(ch, wf.name, wf.random_enabled,
                                       wf.random_min, wf.random_max)
                async def apply_current(channel):
                    if self._intent_valid(session, epochs, channels, source):
                        await self._execute_locked(
                            ("strength", channel, targets[channel].strength))

                results = await asyncio.gather(
                    *(apply_current(ch) for ch in changed), return_exceptions=True)
                errors = [r for r in results if isinstance(r, BaseException)]
                if errors:
                    raise RuntimeError(f"双通道强度未确认: {errors}")
                if not self._intent_valid(session, epochs, channels, source):
                    # 到期或被替换的增量可能已执行，必须先归零，不能补发波形。
                    self._queue_interrupted_intent(command, channels, intent)
                    return
                self._trace_stage("强度确认")
                # 事件配置变化不补发旧波形。常规遥测连续变化时则完成已确认
                # 的这一批，再处理邮箱最新目标，避免持续移动期间波形饥饿。
                latest = self._intent or intent
                if source != "normal" and any(
                        targets[ch] != (latest.a if ch == "A" else latest.b)
                        for ch in channels):
                    return
                for ch in changed:
                    if not self._intent_valid(session, epochs, channels, source):
                        self._queue_interrupted_intent(command, channels, intent)
                        return
                    latest = self._intent or intent
                    if source != "normal" and any(
                            targets[name] != (latest.a if name == "A" else latest.b)
                            for name in channels):
                        self._cmd_queue.put_stops(channels)
                        return
                    if self._last_strength[ch] > 0:
                        await self._send_waveform(ch, self._last_strength[ch])
                if not self._intent_valid(session, epochs, channels, source):
                    self._queue_interrupted_intent(command, channels, intent)
                    return
                latest = self._intent or intent
                if source != "normal" and any(
                        targets[ch] != (latest.a if ch == "A" else latest.b)
                        for ch in channels):
                    self._cmd_queue.put_stops(channels)
                    return
                for ch in changed:
                    self._applied_targets[ch] = targets[ch]
                    self._deferred_channels.discard(ch)
                self._output_failures = 0
                self._trace_stage("首批波形发送")
                if source == "normal" and time.monotonic() - self._last_normal_timing >= 1:
                    self._last_normal_timing = time.monotonic()
                    logger.info("常规输出完成 session=%s revision=%s elapsed=%.3f",
                                session, revision, time.monotonic() - started)
            except Exception as error:
                if session != self._session:
                    return
                self._output_failures += 1
                logger.exception("双通道输出失败 session=%s source=%s", session, source)
                for ch in channels:
                    self._stop_confirmed[ch] = None
                    self._needs_stop[ch] = True
                    self._channel_errors[ch] = str(error)
                    if self._output_failures >= 3:
                        self._faulted[ch] = True
                self._cmd_queue.put_stops(channels)
                # 重试仍走协调路径；先停止重建基准，不重放未确认增量。
                if self._output_failures < 3:
                    with self._intent_lock:
                        latest = self._intent
                        if latest is not None:
                            self._cmd_queue.put(("output", None, latest, session,
                                                 self._revision, dict(self._epochs)))
            finally:
                self._applying_intent = False
                self._coordinating_output = False

