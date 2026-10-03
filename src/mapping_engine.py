"""映射引擎 — 将游戏数据映射为电击强度

支持飞机模式（过载 → 强度）和坦克模式（速度 → 强度）。
归一化后可叠加非线性触发曲线：线性 / 指数 / 对数，未知曲线名回退线性。
"""

import math
from typing import Tuple

# 支持的触发曲线标识（与配置文件中的 curve 字段一致）
CURVES = ("linear", "exp", "log")


class MappingEngine:
    """游戏数据 → 电击强度 映射器

    用法:
        engine = MappingEngine()
        a, b = engine.map_aircraft(gforce=5.0, g_min=1.0, g_max=10.0,
                                    ch_a_max=200, ch_b_max=150)
        # → (89, 66)
    """

    # ============================================================
    # 公开 API
    # ============================================================

    @staticmethod
    def map_aircraft(gforce: float,
                     g_min: float, g_max: float,
                     ch_a_max: int, ch_b_max: int,
                     curve: str = "linear",
                     steepness: float = 2.0) -> Tuple[int, int]:
        """飞机模式：过载 → A/B 通道强度

        Args:
            gforce: 当前过载值 (G)
            g_min: 过载下限
            g_max: 过载上限
            ch_a_max: A 通道最大强度
            ch_b_max: B 通道最大强度
            curve: 触发曲线 ("linear" / "exp" / "log")，未知值回退线性
            steepness: 曲线陡度参数 (>0，越大非线性越明显)

        Returns:
            (intensity_a, intensity_b) 各通道强度 (0-200)
        """
        intensity = MappingEngine._apply_curve(
            MappingEngine._linear(gforce, g_min, g_max), curve, steepness)
        a = int(intensity * ch_a_max)
        b = int(intensity * ch_b_max)
        return (
            MappingEngine._clamp(a, 0, 200),
            MappingEngine._clamp(b, 0, 200),
        )

    @staticmethod
    def map_tank(speed: float,
                 s_min: float, s_max: float,
                 ch_a_max: int, ch_b_max: int,
                 curve: str = "linear",
                 steepness: float = 2.0) -> Tuple[int, int]:
        """陆战模式：速度 → A/B 通道强度

        Args:
            speed: 当前速度 (km/h)
            s_min: 速度下限
            s_max: 速度上限
            ch_a_max: A 通道最大强度
            ch_b_max: B 通道最大强度
            curve: 触发曲线 ("linear" / "exp" / "log")，未知值回退线性
            steepness: 曲线陡度参数 (>0，越大非线性越明显)

        Returns:
            (intensity_a, intensity_b) 各通道强度 (0-200)
        """
        intensity = MappingEngine._apply_curve(
            MappingEngine._linear(abs(speed), s_min, s_max),
            curve, steepness)
        a = int(intensity * ch_a_max)
        b = int(intensity * ch_b_max)
        return (
            MappingEngine._clamp(a, 0, 200),
            MappingEngine._clamp(b, 0, 200),
        )

    # ============================================================
    # 内部
    # ============================================================

    @staticmethod
    def _linear(value: float, v_min: float, v_max: float) -> float:
        """线性插值，返回归一化比例 [0.0, 1.0]

        小于下限 → 0.0，大于上限 → 1.0
        """
        if v_max <= v_min:
            return 0.0
        if value <= v_min:
            return 0.0
        if value >= v_max:
            return 1.0
        return (value - v_min) / (v_max - v_min)

    @staticmethod
    def _apply_curve(t: float, curve: str, steepness: float) -> float:
        """将归一化比例 t 经触发曲线变换，返回值仍为 [0.0, 1.0]

        - linear: t' = t（线性）
        - exp:    t' = (e^(k·t) − 1) / (e^k − 1)（低值段温和、高值段陡增）
        - log:    t' = ln(1 + k·t) / ln(1 + k)（低值段明显、高值段平缓）
        三种曲线均满足 f(0)=0、f(1)=1 且单调递增。
        """
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        k = steepness
        if not math.isfinite(k) or k <= 0:
            return t
        if curve == "exp":
            return (math.exp(k * t) - 1.0) / (math.exp(k) - 1.0)
        if curve == "log":
            return math.log1p(k * t) / math.log1p(k)
        return t

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        """限幅到 [lo, hi]"""
        if value < lo:
            return lo
        if value > hi:
            return hi
        return value
