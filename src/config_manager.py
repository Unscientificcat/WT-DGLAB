"""配置管理模块 — 读写 JSON 配置文件，管理所有用户设置"""

import json
import math
import os
from dataclasses import dataclass, field, asdict
from urllib.parse import urlsplit

# 悬浮窗主字号（G 值大字，像素）线性调节范围
OVERLAY_VALUE_PX_MIN = 13
OVERLAY_VALUE_PX_MAX = 65
OVERLAY_VALUE_PX_DEFAULT = 26
# 旧版"大/中/小"三档对应的主字号，仅用于旧配置迁移
_OVERLAY_LEGACY_SIZES = {"小": 19, "中": 26, "大": 40}


@dataclass
class AircraftSettings:
    """空战模式设置"""
    enabled: bool = True
    gforce_min: float = 1.0
    gforce_max: float = 10.0
    channel_a_max: int = 0
    channel_b_max: int = 0
    waveform_a: str = "恒定"
    waveform_b: str = "恒定"
    random_enabled_a: bool = False
    random_enabled_b: bool = False
    random_min_a: int = 30
    random_max_a: int = 50
    random_min_b: int = 30
    random_max_b: int = 50


@dataclass
class TankSettings:
    """陆战模式设置"""
    enabled: bool = True
    speed_min: float = 0.0
    speed_max: float = 60.0
    channel_a_max: int = 0
    channel_b_max: int = 0
    waveform_a: str = "恒定"
    waveform_b: str = "恒定"
    random_enabled_a: bool = False
    random_enabled_b: bool = False
    random_min_a: int = 30
    random_max_a: int = 50
    random_min_b: int = 30
    random_max_b: int = 50


@dataclass
class CasSettings:
    """CAS（陆战空中支援）设置 — 陆战中上飞机时使用"""
    enabled: bool = True
    gforce_min: float = 1.0
    gforce_max: float = 10.0
    channel_a_max: int = 0
    channel_b_max: int = 0
    waveform_a: str = "恒定"
    waveform_b: str = "恒定"
    random_enabled_a: bool = False
    random_enabled_b: bool = False
    random_min_a: int = 30
    random_max_a: int = 50
    random_min_b: int = 30
    random_max_b: int = 50


@dataclass
class EventSettings:
    """击杀/死亡事件设置"""
    player_name: str = ""              # 游戏昵称
    kill_enabled: bool = False         # 击杀提醒开关
    kill_ch_a: int = 0
    kill_ch_b: int = 0
    kill_duration: float = 5.0
    kill_wf_a: str = "恒定"
    kill_wf_b: str = "恒定"
    death_enabled: bool = False
    death_ch_a: int = 0
    death_ch_b: int = 0
    death_duration: float = 5.0        # 被击落电击持续 (秒)
    death_wf_a: str = "恒定"            # 被击落 A 通道波形
    death_wf_b: str = "恒定"            # 被击落 B 通道波形
    kill_random_a: bool = False
    kill_random_b: bool = False
    death_random_a: bool = False
    death_random_b: bool = False


@dataclass
class TankEventSettings:
    """陆战击杀/死亡事件设置"""
    player_name: str = ""
    kill_enabled: bool = False
    kill_ch_a: int = 0
    kill_ch_b: int = 0
    kill_duration: float = 5.0
    kill_wf_a: str = "恒定"
    kill_wf_b: str = "恒定"
    death_enabled: bool = False
    death_ch_a: int = 0
    death_ch_b: int = 0
    death_duration: float = 5.0
    death_wf_a: str = "恒定"
    death_wf_b: str = "恒定"
    repair_enabled: bool = False
    repair_ch_a: int = 0
    repair_ch_b: int = 0
    repair_wf_a: str = "恒定"
    repair_wf_b: str = "恒定"
    kill_random_a: bool = False
    kill_random_b: bool = False
    death_random_a: bool = False
    death_random_b: bool = False
    repair_random_a: bool = False
    repair_random_b: bool = False


@dataclass
class AppSettings:
    """应用全局设置"""
    ws_port: int = 8765              # WebSocket 服务端口
    dglab_protocol: str = "v3"       # DG-LAB App 协议: "v3" / "v4"
    v4_relay_url: str = "wss://trex.dungeon-lab.cn/v4"
    refresh_interval_ms: int = 200   # 数据刷新间隔(毫秒)
    mode: str = "aircraft"           # 当前模式: "aircraft" 或 "tank"
    overlay_enabled: bool = False    # 悬浮窗开关
    overlay_size_px: int = OVERLAY_VALUE_PX_DEFAULT  # 悬浮窗主字号（像素）
    # 悬浮窗显示内容开关（默认全部显示）
    overlay_show_mode: bool = True          # 当前模式（空战/陆战）
    overlay_show_gforce: bool = True        # 实时过载 (G)
    overlay_show_speed: bool = True         # 实时速度 (km/h)
    overlay_show_event: bool = True         # 事件提示（击杀/坠毁/维修）
    overlay_show_strength_a: bool = True    # A 通道输出强度
    overlay_show_strength_b: bool = True    # B 通道输出强度
    overlay_show_wave_a: bool = True        # A 通道输出波形名
    overlay_show_wave_b: bool = True        # B 通道输出波形名
    notice_accepted: bool = False     # 是否已同意注意事项
    background_enabled: bool = True   # 是否启用壁纸背景
    background_image: str = ""       # backgrounds 目录内文件名，空值为默认壁纸
    card_opacity: int = 72            # 主界面玻璃卡片不透明度（百分比）


@dataclass
class Config:
    """完整配置"""
    aircraft: AircraftSettings = field(default_factory=AircraftSettings)
    tank: TankSettings = field(default_factory=TankSettings)
    cas: CasSettings = field(default_factory=CasSettings)
    events: EventSettings = field(default_factory=EventSettings)
    tank_events: TankEventSettings = field(default_factory=TankEventSettings)
    app: AppSettings = field(default_factory=AppSettings)


class ConfigManager:
    """配置管理器 — 负责配置的加载、保存和默认值重置"""

    def __init__(self, config_path: str = "config.json"):
        self._config_path = config_path
        self._config: Config = Config()

    @property
    def config(self) -> Config:
        """返回当前内存中的完整配置。"""
        return self._config

    @property
    def config_path(self) -> str:
        """返回配置文件的绝对路径。"""
        return os.path.abspath(self._config_path)

    def load(self) -> Config:
        """从文件加载配置，文件不存在时使用默认值"""
        config_path = self.config_path
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._apply_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                    AttributeError, OverflowError):
                # 配置文件损坏时使用默认值
                self._config = Config()
        return self._config

    def load_template(self, template_path: str) -> Config:
        """加载默认配置模板；模板缺失或损坏时回退内置默认值。"""
        template_manager = ConfigManager(template_path)
        template_manager.load()
        self._config = template_manager.config
        return self._config

    def save(self) -> None:
        """使用原子替换将当前配置保存到文件。"""
        config_path = self.config_path
        config_dir = os.path.dirname(config_path)
        os.makedirs(config_dir, exist_ok=True)
        temp_path = f"{config_path}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(
                    self._to_dict(),
                    file,
                    indent=2,
                    ensure_ascii=False,
                )
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, config_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def reset_defaults(self) -> Config:
        """恢复所有默认值"""
        self._config = Config()
        return self._config

    def _to_dict(self) -> dict:
        return {
            "aircraft": asdict(self._config.aircraft),
            "tank": asdict(self._config.tank),
            "cas": asdict(self._config.cas),
            "events": asdict(self._config.events),
            "tank_events": asdict(self._config.tank_events),
            "app": asdict(self._config.app),
        }

    def _apply_dict(self, data: dict) -> None:
        """将字典数据应用到配置对象"""
        if not isinstance(data, dict):
            raise TypeError("配置根节点必须是对象")
        def waveform(value) -> str:
            value = str(value or "恒定")
            # 旧版本预设和随机选项均不再存在。
            return value if value == "恒定" or value.lower().endswith(".pulse") else "恒定"

        def random_range(section: dict, suffix: str = "") -> tuple[bool, int, int]:
            enabled = bool(section.get(f"random_enabled{suffix}", False))
            old = section.get("random_interval")
            minimum = section.get(f"random_min{suffix}", old if old is not None else 30)
            maximum = section.get(f"random_max{suffix}", old if old is not None else 50)
            if old is not None and f"random_min{suffix}" not in section:
                maximum = minimum
            return enabled, int(minimum), int(maximum)

        if "aircraft" in data:
            ac = data["aircraft"]
            ea, mina, maxa = random_range(ac, "_a")
            eb, minb, maxb = random_range(ac, "_b")
            self._config.aircraft = AircraftSettings(
                enabled=bool(ac.get("enabled", True)),
                gforce_min=float(ac.get("gforce_min", 1.0)),
                gforce_max=float(ac.get("gforce_max", 10.0)),
                channel_a_max=int(ac.get("channel_a_max", 0)),
                channel_b_max=int(ac.get("channel_b_max", 0)),
                waveform_a=waveform(ac.get("waveform_a")),
                waveform_b=waveform(ac.get("waveform_b")),
                random_enabled_a=ea, random_enabled_b=eb,
                random_min_a=mina, random_max_a=maxa,
                random_min_b=minb, random_max_b=maxb,
            )
        if "tank" in data:
            tk = data["tank"]
            ea, mina, maxa = random_range(tk, "_a")
            eb, minb, maxb = random_range(tk, "_b")
            self._config.tank = TankSettings(
                enabled=bool(tk.get("enabled", True)),
                speed_min=float(tk.get("speed_min", 0)),
                speed_max=float(tk.get("speed_max", 60)),
                channel_a_max=int(tk.get("channel_a_max", 0)),
                channel_b_max=int(tk.get("channel_b_max", 0)),
                waveform_a=waveform(tk.get("waveform_a")),
                waveform_b=waveform(tk.get("waveform_b")),
                random_enabled_a=ea, random_enabled_b=eb,
                random_min_a=mina, random_max_a=maxa,
                random_min_b=minb, random_max_b=maxb,
            )
        if "tank_events" in data:
            te = data["tank_events"]
            self._config.tank_events = TankEventSettings(
                player_name=str(te.get("player_name", "")),
                kill_enabled=bool(te.get("kill_enabled", False)),
                kill_ch_a=int(te.get("kill_ch_a", 0)),
                kill_ch_b=int(te.get("kill_ch_b", 0)),
                kill_duration=float(te.get("kill_duration", 5.0)),
                kill_wf_a=waveform(te.get("kill_wf_a")),
                kill_wf_b=waveform(te.get("kill_wf_b")),
                death_enabled=bool(te.get("death_enabled", False)),
                death_ch_a=int(te.get("death_ch_a", 0)),
                death_ch_b=int(te.get("death_ch_b", 0)),
                death_duration=float(te.get("death_duration", 5.0)),
                death_wf_a=waveform(te.get("death_wf_a")),
                death_wf_b=waveform(te.get("death_wf_b")),
                repair_enabled=bool(te.get("repair_enabled", False)),
                repair_ch_a=int(te.get("repair_ch_a", 0)),
                repair_ch_b=int(te.get("repair_ch_b", 0)),
                repair_wf_a=waveform(te.get("repair_wf_a")),
                repair_wf_b=waveform(te.get("repair_wf_b")),
                kill_random_a=bool(te.get("kill_random_a", False)),
                kill_random_b=bool(te.get("kill_random_b", False)),
                death_random_a=bool(te.get("death_random_a", False)),
                death_random_b=bool(te.get("death_random_b", False)),
                repair_random_a=bool(te.get("repair_random_a", False)),
                repair_random_b=bool(te.get("repair_random_b", False)),
            )
        if "cas" in data:
            cs = data["cas"]
            self._config.cas = CasSettings(
                enabled=bool(cs.get("enabled", True)),
                gforce_min=float(cs.get("gforce_min", 1.0)),
                gforce_max=float(cs.get("gforce_max", 10.0)),
                channel_a_max=int(cs.get("channel_a_max", 0)),
                channel_b_max=int(cs.get("channel_b_max", 0)),
                waveform_a=waveform(cs.get("waveform_a")),
                waveform_b=waveform(cs.get("waveform_b")),
                random_enabled_a=random_range(cs, "_a")[0], random_enabled_b=random_range(cs, "_b")[0],
                random_min_a=random_range(cs, "_a")[1], random_max_a=random_range(cs, "_a")[2],
                random_min_b=random_range(cs, "_b")[1], random_max_b=random_range(cs, "_b")[2],
            )
        if "events" in data:
            ev = data["events"]
            self._config.events = EventSettings(
                player_name=str(ev.get("player_name", "")),
                kill_enabled=bool(ev.get("kill_enabled", False)),
                kill_ch_a=int(ev.get("kill_ch_a", 0)),
                kill_ch_b=int(ev.get("kill_ch_b", 0)),
                kill_duration=float(ev.get("kill_duration", 5.0)),
                kill_wf_a=waveform(ev.get("kill_wf_a")),
                kill_wf_b=waveform(ev.get("kill_wf_b")),
                death_enabled=bool(ev.get("death_enabled", False)),
                death_ch_a=int(ev.get("death_ch_a", 0)),
                death_ch_b=int(ev.get("death_ch_b", 0)),
                death_duration=float(ev.get("death_duration", 5.0)),
                death_wf_a=waveform(ev.get("death_wf_a")),
                death_wf_b=waveform(ev.get("death_wf_b")),
                kill_random_a=bool(ev.get("kill_random_a", False)), kill_random_b=bool(ev.get("kill_random_b", False)),
                death_random_a=bool(ev.get("death_random_a", False)), death_random_b=bool(ev.get("death_random_b", False)),
            )
        if "app" in data:
            ap = data["app"]
            protocol = str(ap.get("dglab_protocol", "v3")).lower()
            relay_url = str(ap.get(
                "v4_relay_url", "wss://trex.dungeon-lab.cn/v4"
            )).strip()
            parsed_relay = urlsplit(relay_url)
            if (parsed_relay.scheme not in {"ws", "wss"}
                    or not parsed_relay.netloc):
                relay_url = "wss://trex.dungeon-lab.cn/v4"
            self._config.app = AppSettings(
                ws_port=int(ap.get("ws_port", 8765)),
                dglab_protocol=(
                    protocol if protocol in {"v3", "v4"} else "v3"
                ),
                v4_relay_url=relay_url,
                refresh_interval_ms=int(ap.get("refresh_interval_ms", 200)),
                mode=str(ap.get("mode", "aircraft")),
                overlay_enabled=bool(ap.get("overlay_enabled", False)),
                overlay_size_px=self._read_overlay_value_px(ap),
                overlay_show_mode=bool(ap.get("overlay_show_mode", True)),
                overlay_show_gforce=bool(ap.get("overlay_show_gforce", True)),
                overlay_show_speed=bool(ap.get("overlay_show_speed", True)),
                overlay_show_event=bool(ap.get("overlay_show_event", True)),
                overlay_show_strength_a=bool(ap.get("overlay_show_strength_a", True)),
                overlay_show_strength_b=bool(ap.get("overlay_show_strength_b", True)),
                overlay_show_wave_a=bool(ap.get("overlay_show_wave_a", True)),
                overlay_show_wave_b=bool(ap.get("overlay_show_wave_b", True)),
                notice_accepted=bool(ap.get("notice_accepted", False)),
                background_enabled=bool(ap.get("background_enabled", True)),
                background_image=str(ap.get("background_image", "")),
                card_opacity=int(ap.get("card_opacity", 72)),
            )
        self._validate_config()

    @staticmethod
    def _read_overlay_value_px(ap: dict) -> int:
        """读取悬浮窗主字号，旧版"大/中/小"三档字符串自动换算并钳制到有效范围。"""
        raw = ap.get("overlay_size_px")
        if raw is None:
            raw = _OVERLAY_LEGACY_SIZES.get(
                str(ap.get("overlay_size", "中")), OVERLAY_VALUE_PX_DEFAULT
            )
        return max(OVERLAY_VALUE_PX_MIN, min(OVERLAY_VALUE_PX_MAX, int(raw)))

    def _validate_config(self) -> None:
        """校验从磁盘读取的配置，拒绝越界、非有限数值和错误枚举。"""
        sections = (self._config.aircraft, self._config.tank, self._config.cas,
                    self._config.events, self._config.tank_events)
        for section in sections:
            for name, value in vars(section).items():
                if isinstance(value, (int, float)) and not math.isfinite(value):
                    raise ValueError(f"配置字段 {name} 不是有限数值")

        for section in sections:
            for name, value in vars(section).items():
                if name.endswith(("_ch_a", "_ch_b")) and not 0 <= value <= 200:
                    raise ValueError(f"配置字段 {name} 超出 0..200")

        for section, lower_name, upper_name in (
                (self._config.aircraft, "gforce_min", "gforce_max"),
                (self._config.tank, "speed_min", "speed_max"),
                (self._config.cas, "gforce_min", "gforce_max")):
            if (getattr(section, lower_name) < 0
                    or getattr(section, upper_name) < 0
                    or any(not 5 <= getattr(section, n) <= 300 for n in ("random_min_a", "random_max_a", "random_min_b", "random_max_b"))
                    or any(getattr(section, lo) > getattr(section, hi) for lo, hi in (("random_min_a", "random_max_a"), ("random_min_b", "random_max_b")))):
                raise ValueError("触发范围或随机间隔超出有效范围")

        for obj in (self._config.events, self._config.tank_events):
            for field_name in ("kill_duration", "death_duration"):
                duration = getattr(obj, field_name)
                if duration < 0.1 or duration > 30:
                    raise ValueError(f"配置字段 {field_name} 超出有效范围")

        app = self._config.app
        if not 1024 <= app.ws_port <= 65535:
            raise ValueError("V3 端口超出有效范围")
        if not 50 <= app.refresh_interval_ms <= 1000:
            raise ValueError("刷新间隔超出有效范围")
        if app.dglab_protocol not in {"v3", "v4"}:
            raise ValueError("未知 DG-LAB 协议")
        if app.mode not in {"aircraft", "tank"}:
            raise ValueError("未知游戏模式")
        if not OVERLAY_VALUE_PX_MIN <= app.overlay_size_px <= OVERLAY_VALUE_PX_MAX:
            raise ValueError("悬浮窗字号超出有效范围")
        if not 20 <= app.card_opacity <= 90:
            raise ValueError("卡片不透明度超出 20..90 范围")
        background_name = app.background_image
        if background_name:
            if (background_name in {".", ".."}
                    or "/" in background_name
                    or "\\" in background_name
                    or ".." in background_name
                    or os.path.basename(background_name) != background_name
                    or os.path.splitext(background_name)[1].lower()
                    not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}):
                raise ValueError("壁纸文件名无效")
