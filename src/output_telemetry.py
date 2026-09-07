"""郊狼输出遥测 — 记录控制器实际下发的波形，供界面显示波形名与电压曲线。

架构：
    控制器 asyncio 线程调用 record_* 记录
    Qt 主线程调用 snapshot() 读取快照（加锁拷贝，互不阻塞）
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

CONSTANT_WAVEFORM = "恒定"
_CHANNELS = ("A", "B")
_PULSE_SUFFIX = ".pulse"


def display_waveform_name(name: str) -> str:
    """返回用于界面显示的波形名：去掉 .pulse 后缀。"""
    text = str(name or CONSTANT_WAVEFORM)
    if text.endswith(_PULSE_SUFFIX):
        return text[: -len(_PULSE_SUFFIX)]
    return text


@dataclass(frozen=True)
class PulseBatch:
    """一次下发的波形批次：4 个 25ms 采样点的最终幅度（0-100）。"""
    t: float                              # 下发时刻（time.monotonic）
    amplitudes: tuple[int, int, int, int]  # 最终幅度字节，电压 = 幅度 × 2
    strength: int                          # 下发时的通道强度 0-200


@dataclass(frozen=True)
class ChannelOutputSnapshot:
    """GUI 可用的单通道输出快照。"""
    name: str            # 当前波形名（"恒定" 或 .pulse 文件名）
    strength: int        # 最近一次指令强度 0-200
    active: bool         # 是否正在输出
    batches: tuple[PulseBatch, ...]  # 最近的下发批次，旧→新


class OutputTelemetry:
    """线程安全的通道输出记录器。

    每个郊狼控制器（V3/V4）持有一个实例；控制器线程在波形切换和
    每次下发波形批次时记录，GUI 主线程只读快照用于波形名显示和
    输出电压曲线窗口。
    """

    def __init__(self, max_batches: int = 40):
        # 可重入锁：允许持锁状态下调用同类加锁方法
        self._lock = threading.RLock()
        self._max_batches = max(1, int(max_batches))
        self._names: dict[str, str] = {key: CONSTANT_WAVEFORM for key in _CHANNELS}
        self._strengths: dict[str, int] = {key: 0 for key in _CHANNELS}
        self._active: dict[str, bool] = {key: False for key in _CHANNELS}
        self._batches: dict[str, deque] = {
            key: deque(maxlen=self._max_batches) for key in _CHANNELS
        }

    @staticmethod
    def _key(channel: str) -> str:
        """归一化通道名，未知通道归入 A。"""
        return channel if channel in _CHANNELS else "A"

    def record_waveform(self, channel: str, name: str) -> None:
        """记录通道当前波形名（切换波形或随机换波时调用）。"""
        with self._lock:
            self._names[self._key(channel)] = str(name or CONSTANT_WAVEFORM)

    def record_pulse(self, channel: str, amplitudes, strength: int) -> None:
        """记录一次实际下发的波形批次。"""
        amps = tuple(max(0, min(100, int(value))) for value in amplitudes)
        while len(amps) < 4:
            amps += (0,)
        batch = PulseBatch(
            time.monotonic(),
            amps[:4],
            max(0, min(200, int(strength))),
        )
        with self._lock:
            key = self._key(channel)
            self._batches[key].append(batch)
            self._strengths[key] = batch.strength
            self._active[key] = batch.strength > 0

    def record_silence(self, channel: str) -> None:
        """记录通道停止输出（强度归零时调用）。"""
        batch = PulseBatch(time.monotonic(), (0, 0, 0, 0), 0)
        with self._lock:
            key = self._key(channel)
            self._batches[key].append(batch)
            self._strengths[key] = 0
            self._active[key] = False

    def reset(self) -> None:
        """清空输出记录（连接断开时调用），波形名保留。"""
        with self._lock:
            for key in _CHANNELS:
                self._batches[key].clear()
                self._strengths[key] = 0
                self._active[key] = False

    def snapshot(self, channel: str) -> ChannelOutputSnapshot:
        """返回通道输出快照（GUI 主线程调用）。"""
        with self._lock:
            key = self._key(channel)
            return ChannelOutputSnapshot(
                name=self._names[key],
                strength=self._strengths[key],
                active=self._active[key],
                batches=tuple(self._batches[key]),
            )
