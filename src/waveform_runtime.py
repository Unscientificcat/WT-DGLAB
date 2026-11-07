"""两种 App 协议共用波形配置、随机选择和原始幅度语义。"""

import asyncio
import logging
import random


logger = logging.getLogger("WaveformRuntime")
CONSTANT_PULSE = ((10, 10, 10, 10), (100, 100, 100, 100))


class WaveformRuntime:
    """协议适配器只负责发送帧，不再自行缩放或生成恒定波形。"""

    def _pulse_at(self, channel, at):
        player = self._player_a if channel == "A" else self._player_b
        return CONSTANT_PULSE if player.is_constant else player.pulse_at(at)

    def _set_waveform(self, channel, name, enabled=False, minimum=30, maximum=50):
        config = (name, enabled, minimum, maximum)
        if self._waveform_configs.get(channel) == config:
            return False
        self._waveform_configs[channel] = config
        self._stop_random(channel)
        player = self._player_a if channel == "A" else self._player_b
        player.set_waveform(name)
        self.telemetry.record_waveform(channel, player.current_name)
        if enabled:
            self._start_random(channel, minimum, maximum)
        return True

    def _stop_random(self, channel):
        task = self._random_tasks.pop(channel, None)
        if task and not task.done():
            task.cancel()

    def _start_random(self, channel, minimum, maximum):
        self._stop_random(channel)
        self._random_tasks[channel] = asyncio.ensure_future(
            self._random_loop(channel, minimum, maximum))

    async def _random_loop(self, channel, minimum, maximum):
        while self._running:
            await asyncio.sleep(random.uniform(max(5, minimum), max(maximum, minimum)))
            choices = [name for name in self._catalog.choices() if name != "恒定"]
            if not choices:
                continue
            try:
                async with self._output_lock:
                    if (self._closing or self._batch_blocked
                            or not self._output_allowed(channel)):
                        continue
                    player = self._player_a if channel == "A" else self._player_b
                    player.set_waveform(random.choice(
                        [n for n in choices if n != player.current_name] or choices))
                    self.telemetry.record_waveform(channel, player.current_name)
                    if (self._status.bound and not self._needs_stop[channel]
                            and not self._cmd_queue.has_stop(channel)
                            and self._last_strength[channel] > 0):
                        await self._send_waveform(channel, self._last_strength[channel])
            except Exception:
                logger.exception("随机波形切换失败：通道 %s", channel)

    # 旧公开测试与独立调用者仍可启动随机策略，全部委托同一实现。
    def _start_channel_random(self, channel, minimum, maximum):
        self._start_random(channel, minimum, maximum)

    def _stop_channel_random(self, channel):
        self._stop_random(channel)

    def _start_random_task(self, channel, minimum, maximum):
        self._start_random(channel, minimum, maximum)

    def _stop_random_task(self, channel):
        self._stop_random(channel)

    async def _channel_random_loop(self, channel, minimum, maximum):
        await self._random_loop(channel, minimum, maximum)

    async def _random_waveform_loop(self, channel, minimum, maximum):
        await self._random_loop(channel, minimum, maximum)
