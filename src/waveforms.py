"""DG-LAB 波形资源、官方 .pulse 解析和播放器。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .runtime_paths import application_directory

Pulse = tuple[tuple[int, int, int, int], tuple[int, int, int, int]]
FREQUENCY_DATASET = tuple(list(range(10, 51)) + list(range(52, 81, 2)) + [85, 90, 95, 100] + list(range(110, 201, 10)) + [233, 266, 300, 333, 366, 400] + [450, 500, 550, 600] + [700, 800, 900, 1000])
DURATION_DATASET = tuple([round(i / 10, 1) for i in range(1, 50)] + [5, 5.2, 5.4, 5.6, 5.8, 6, 6.2, 6.4, 6.6, 6.8, 7, 7.2, 7.4, 7.6, 7.8, 8, 8.5, 9, 9.5] + list(range(10, 20)) + [20, 23.4, 26.6, 30, 33.4, 36.6, 40, 45, 50, 55, 60, 70, 80, 90, 100, 120, 140, 160, 180, 200, 250, 300])


@dataclass(frozen=True)
class WaveformDefinition:
    """一条可供控制器播放的自定义波形。"""
    name: str
    path: str
    pulses: tuple[Pulse, ...]


@dataclass(frozen=True)
class ReloadResult:
    """一次波形目录刷新结果。"""
    definitions: tuple[WaveformDefinition, ...]
    errors: tuple[tuple[str, str], ...]


def _frequency_value(index: int) -> int:
    if not 0 <= index < len(FREQUENCY_DATASET):
        raise ValueError("频率索引必须在 0..83 范围内")
    return FREQUENCY_DATASET[index]


def _duration_value(index: int) -> float:
    if not 0 <= index < len(DURATION_DATASET):
        raise ValueError("时长索引必须在 0..99 范围内")
    return DURATION_DATASET[index]


def _frequency_output(value: float) -> int:
    if value <= 100:
        result = value
    elif value <= 600:
        result = (value - 100) / 5 + 100
    else:
        result = (value - 600) / 10 + 200
    return max(10, min(240, int(round(result))))


def _interpolate(values: list[float], length: int) -> list[float]:
    if length <= 0:
        return []
    if len(values) == 1 or length == 1:
        return [values[0]] * length
    result = []
    for i in range(length):
        position = i * (len(values) - 1) / (length - 1)
        left = int(math.floor(position))
        right = min(left + 1, len(values) - 1)
        ratio = position - left
        result.append(values[left] + (values[right] - values[left]) * ratio)
    return result


def parse_pulse_text(text: str, name: str = "") -> tuple[Pulse, ...]:
    """解析官方 Dungeonlab+pulse 文本并编译为 100ms Pulse 帧。"""
    text = "".join(text.split())
    prefix = "Dungeonlab+pulse:"
    if not text.lower().startswith(prefix.lower()):
        raise ValueError("缺少 Dungeonlab+pulse: 前缀")
    parts = text[len(prefix):].split("+section+")
    if not parts or not parts[0] or "=" not in parts[0]:
        raise ValueError("波形缺少全局参数或 section")
    global_part, first_section = parts[0].split("=", 1)
    values = global_part.split(",")
    if len(values) != 3:
        raise ValueError("全局参数必须包含 3 个值")
    try:
        rest_index, speed, _balance = (int(value) for value in values)
    except ValueError as error:
        raise ValueError("全局参数必须为整数") from error
    if speed not in {1, 2, 4}:
        raise ValueError("播放速度只能为 1、2 或 4")
    _duration_value(rest_index)
    if len(parts) > 10:
        raise ValueError("最多支持 10 个 section")

    output: list[Pulse] = []
    for number, section in enumerate([first_section, *parts[1:]], 1):
        if "/" not in section:
            raise ValueError(f"第 {number} 个 section 缺少 /")
        header, shape_text = section.split("/", 1)
        header_values = header.split(",")
        if len(header_values) != 5:
            raise ValueError(f"第 {number} 个 section 参数数量错误")
        try:
            freq_start, freq_end, duration_index, freq_mode, enabled = (int(value) for value in header_values)
        except ValueError as error:
            raise ValueError(f"第 {number} 个 section 参数必须为整数") from error
        start = _frequency_value(freq_start)
        end = _frequency_value(freq_end)
        duration = _duration_value(duration_index)
        if freq_mode not in {1, 2, 3, 4} or enabled not in {0, 1}:
            raise ValueError(f"第 {number} 个 section 参数越界")
        points: list[float] = []
        for item in shape_text.split(","):
            point = item.split("-")
            if len(point) != 2:
                raise ValueError(f"第 {number} 个 section 曲线点错误")
            try:
                strength, anchor = float(point[0]), int(point[1])
            except ValueError as error:
                raise ValueError(f"第 {number} 个 section 曲线点不是数字") from error
            if not 0 <= strength <= 100 or anchor not in {0, 1}:
                raise ValueError(f"第 {number} 个 section 曲线点越界")
            points.append(strength)
        if len(points) < 2:
            raise ValueError(f"第 {number} 个 section 至少需要 2 个曲线点")
        if not enabled:
            continue

        point_count = len(points)
        repeat = max(1, math.ceil(duration / (point_count * 0.1)))
        total_points = point_count * repeat
        strengths = points * repeat
        if freq_mode == 1:
            frequencies = [start] * total_points
        elif freq_mode == 2:
            frequencies = _interpolate([start, end], total_points)
        elif freq_mode == 3:
            frequencies = _interpolate([start, end], point_count) * repeat
        else:
            frequencies = [value for value in _interpolate([start, end], repeat) for _ in range(point_count)]

        point_repeat = {1: 4, 2: 2, 4: 1}[speed]
        freq_samples: list[int] = []
        strength_samples: list[int] = []
        for frequency, strength in zip(frequencies, strengths):
            freq_samples.extend([_frequency_output(frequency)] * point_repeat)
            strength_samples.extend([max(0, min(100, int(round(strength))))] * point_repeat)
        while len(freq_samples) % 4:
            freq_samples.append(10)
            strength_samples.append(0)
        for index in range(0, len(freq_samples), 4):
            output.append((tuple(freq_samples[index:index + 4]), tuple(strength_samples[index:index + 4])))

    if not output:
        raise ValueError("波形没有启用的 section")
    for _ in range(max(0, math.ceil(_duration_value(rest_index) * 10))):
        output.append(((10, 10, 10, 10), (0, 0, 0, 0)))
    return tuple(output)


class WaveformCatalog:
    """管理 EXE 同级 waveforms 目录中的自定义波形。"""
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or application_directory()) / "waveforms"
        self._definitions: dict[str, WaveformDefinition] = {}

    def ensure_directory(self) -> None:
        """创建波形目录。"""
        self.directory.mkdir(parents=True, exist_ok=True)

    def reload(self) -> ReloadResult:
        """扫描并解析波形目录。"""
        self.ensure_directory()
        definitions: dict[str, WaveformDefinition] = {}
        errors: list[tuple[str, str]] = []
        for path in sorted(self.directory.glob("*.pulse"), key=lambda p: p.name.casefold()):
            try:
                pulses = parse_pulse_text(path.read_text(encoding="utf-8-sig"), path.name)
                definitions[path.name] = WaveformDefinition(path.name, str(path), pulses)
            except (OSError, UnicodeError, ValueError) as error:
                errors.append((path.name, str(error)))
        self._definitions = definitions
        return ReloadResult(tuple(definitions.values()), tuple(errors))

    def choices(self) -> list[str]:
        """返回下拉框选项，恒定始终在首位。"""
        return ["恒定", *self._definitions]

    def get(self, name: str) -> WaveformDefinition | None:
        """按完整文件名获取波形。"""
        return self._definitions.get(name)

    @property
    def definitions(self) -> tuple[WaveformDefinition, ...]:
        """返回当前有效波形。"""
        return tuple(self._definitions.values())


class WaveformPlayer:
    """管理单个通道的恒定或自定义波形播放。"""
    def __init__(self, waveform: str = "恒定", catalog: WaveformCatalog | None = None):
        self._index = 0
        self._data: tuple[Pulse, ...] = ()
        self._name = "恒定"
        self._catalog = catalog
        self.set_waveform(waveform)

    def set_catalog(self, catalog: WaveformCatalog | None) -> None:
        """更新资源目录引用。"""
        self._catalog = catalog

    def set_waveform(self, name: str, pulses: tuple[Pulse, ...] | None = None) -> None:
        """切换波形，未知名称回退恒定。"""
        data = pulses
        if data is None and self._catalog:
            definition = self._catalog.get(name)
            data = definition.pulses if definition else None
        self._data = tuple(data or ())
        self._name = name if self._data else "恒定"
        self._index = 0

    def next_pulse(self) -> Optional[Pulse]:
        """获取下一帧并循环。"""
        if not self._data:
            return None
        pulse = self._data[self._index]
        self._index = (self._index + 1) % len(self._data)
        return pulse

    def reset(self) -> None:
        """重置播放位置。"""
        self._index = 0

    @property
    def is_constant(self) -> bool:
        """是否为恒定波形。"""
        return not self._data

    @property
    def current_name(self) -> str:
        """返回当前波形完整名称。"""
        return self._name
