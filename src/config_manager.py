"""配置管理模块 — 读写 JSON 配置文件，管理所有用户设置"""

import json
import logging
import math
import os
import shutil
import time
from dataclasses import dataclass, field, fields, asdict
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
    curve: str = "linear"          # 触发曲线: "linear" / "exp" / "log"
    curve_steepness: float = 2.0   # 曲线陡度参数
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
    curve: str = "linear"          # 触发曲线: "linear" / "exp" / "log"
    curve_steepness: float = 2.0   # 曲线陡度参数
    idle_enabled: bool = False     # 静止惩罚：速度为 0 超时后持续电击
    idle_timeout_s: float = 10.0   # 静止持续此时长后触发 (秒)
    idle_speed_max: float = 2.0    # 低于该速度视为静止 (km/h)
    idle_ch_a: int = 0
    idle_ch_b: int = 0
    idle_wf_a: str = "恒定"
    idle_wf_b: str = "恒定"
    idle_random_a: bool = False     # 静止惩罚触发时随机切换波形
    idle_random_b: bool = False
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
    curve: str = "linear"          # 触发曲线: "linear" / "exp" / "log"
    curve_steepness: float = 2.0   # 曲线陡度参数
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
    hit_enabled: bool = False          # 被命中短脉冲开关
    hit_ch_a: int = 0
    hit_ch_b: int = 0
    hit_duration: float = 0.5          # 被命中输出时长 (秒)
    hit_wf_a: str = "恒定"
    hit_wf_b: str = "恒定"
    hit_cooldown: float = 2.0          # 两次被命中之间的冷却 (秒)
    kill_random_a: bool = False
    kill_random_b: bool = False
    death_random_a: bool = False
    death_random_b: bool = False
    repair_random_a: bool = False
    repair_random_b: bool = False
    hit_random_a: bool = False
    hit_random_b: bool = False


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

    # 配置文件各节对应的数据类，用于逐字段预检数值类型
    _SECTION_TYPES = {
        "aircraft": AircraftSettings,
        "tank": TankSettings,
        "cas": CasSettings,
        "events": EventSettings,
        "tank_events": TankEventSettings,
        "app": AppSettings,
    }

    def __init__(self, config_path: str = "config.json"):
        self._config_path = config_path
        self._config: Config = Config()
        self._last_logged_config = self._to_dict()
        # 最近一次 load() 修正过的字段说明，以及原文件备份路径
        self.load_issues: list[str] = []
        self.invalid_backup_path: str = ""
        # 启动时写入失败的原因（如程序目录只读），供界面提示
        self.save_error: str = ""

    @property
    def config(self) -> Config:
        """返回当前内存中的完整配置。"""
        return self._config

    @property
    def config_path(self) -> str:
        """返回配置文件的绝对路径。"""
        return os.path.abspath(self._config_path)

    def load(self) -> Config:
        """从文件加载配置，文件不存在时使用默认值

        单个字段非法时只回退该字段；文件整体无法解析时回退全部默认值。
        两种情况都会先把原文件备份为 config.json.invalid-时间戳，
        避免后续保存覆盖用户设置后无法找回。
        """
        config_path = self.config_path
        self.load_issues = []
        self.invalid_backup_path = ""
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._apply_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                    AttributeError, OverflowError):
                logging.getLogger("ConfigManager").warning(
                    "配置文件无效，使用默认值", exc_info=True)
                # 配置文件损坏时使用默认值
                self._config = Config()
                self.load_issues = ["配置文件无法解析，已全部恢复默认值"]
            if self.load_issues:
                self._backup_invalid_file(config_path)
        self._last_logged_config = self._to_dict()
        return self._config

    def _backup_invalid_file(self, config_path: str) -> None:
        """回退默认值前备份原配置文件，备份失败只记录日志。"""
        log = logging.getLogger("ConfigManager")
        backup_path = (f"{config_path}.invalid-"
                       f"{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(config_path, backup_path)
        except OSError:
            log.error("配置文件备份失败：%s", backup_path, exc_info=True)
        else:
            self.invalid_backup_path = backup_path
            log.warning("原配置文件已备份：%s", backup_path)
        for issue in self.load_issues:
            log.warning("配置修正：%s", issue)

    def load_template(self, template_path: str) -> Config:
        """加载默认配置模板；模板缺失或损坏时回退内置默认值。"""
        template_manager = ConfigManager(template_path)
        template_manager.load()
        self._config = template_manager.config
        self._last_logged_config = self._to_dict()
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
            self._log_changes()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def reset_defaults(self) -> Config:
        """恢复所有默认值"""
        self._config = Config()
        return self._config

    def _log_changes(self) -> None:
        """成功保存后记录关键配置差异，避免自动保存重复刷屏。"""
        current = self._to_dict()
        changes = []
        for section, values in current.items():
            if section not in {"aircraft", "tank", "cas", "events", "tank_events", "app"}:
                continue
            for key, value in values.items():
                if section == "app" and key not in {
                    "mode", "dglab_protocol", "ws_port", "v4_relay_url",
                    "refresh_interval_ms",
                }:
                    continue
                old = self._last_logged_config.get(section, {}).get(key)
                if old != value:
                    changes.append(f"{section}.{key}: {old} → {value}")
        if changes:
            logging.getLogger("ConfigManager").info(
                "关键设置已保存：%s", "；".join(changes))
        self._last_logged_config = current

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
        # 逐字段预检：类型错误或非有限数值的字段丢弃后使用默认值，其余保留
        issues: list[str] = []
        data = self._coerce_sections(data, issues)

        def waveform(value) -> str:
            value = str(value or "恒定")
            # 旧版本预设和随机选项均不再存在。
            return value if value == "恒定" or value.lower().endswith(".pulse") else "恒定"

        def curve(value) -> str:
            # 触发曲线名非法时静默回退线性，与协议字段的容错方式一致。
            value = str(value or "linear").lower()
            return value if value in ("linear", "exp", "log") else "linear"

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
                curve=curve(ac.get("curve")),
                curve_steepness=float(ac.get("curve_steepness", 2.0)),
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
                curve=curve(tk.get("curve")),
                curve_steepness=float(tk.get("curve_steepness", 2.0)),
                idle_enabled=bool(tk.get("idle_enabled", False)),
                idle_timeout_s=float(tk.get("idle_timeout_s", 10.0)),
                idle_speed_max=float(tk.get("idle_speed_max", 2.0)),
                idle_ch_a=int(tk.get("idle_ch_a", 0)),
                idle_ch_b=int(tk.get("idle_ch_b", 0)),
                idle_wf_a=waveform(tk.get("idle_wf_a")),
                idle_wf_b=waveform(tk.get("idle_wf_b")),
                idle_random_a=bool(tk.get("idle_random_a", False)),
                idle_random_b=bool(tk.get("idle_random_b", False)),
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
                hit_enabled=bool(te.get("hit_enabled", False)),
                hit_ch_a=int(te.get("hit_ch_a", 0)),
                hit_ch_b=int(te.get("hit_ch_b", 0)),
                hit_duration=float(te.get("hit_duration", 0.5)),
                hit_wf_a=waveform(te.get("hit_wf_a")),
                hit_wf_b=waveform(te.get("hit_wf_b")),
                hit_cooldown=float(te.get("hit_cooldown", 2.0)),
                kill_random_a=bool(te.get("kill_random_a", False)),
                kill_random_b=bool(te.get("kill_random_b", False)),
                death_random_a=bool(te.get("death_random_a", False)),
                death_random_b=bool(te.get("death_random_b", False)),
                repair_random_a=bool(te.get("repair_random_a", False)),
                repair_random_b=bool(te.get("repair_random_b", False)),
                hit_random_a=bool(te.get("hit_random_a", False)),
                hit_random_b=bool(te.get("hit_random_b", False)),
            )
        if "cas" in data:
            cs = data["cas"]
            self._config.cas = CasSettings(
                enabled=bool(cs.get("enabled", True)),
                gforce_min=float(cs.get("gforce_min", 1.0)),
                gforce_max=float(cs.get("gforce_max", 10.0)),
                channel_a_max=int(cs.get("channel_a_max", 0)),
                channel_b_max=int(cs.get("channel_b_max", 0)),
                curve=curve(cs.get("curve")),
                curve_steepness=float(cs.get("curve_steepness", 2.0)),
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
        self.load_issues = issues + self._sanitize_config()

    @staticmethod
    def _read_overlay_value_px(ap: dict) -> int:
        """读取悬浮窗主字号，旧版"大/中/小"三档字符串自动换算并钳制到有效范围。"""
        raw = ap.get("overlay_size_px")
        if raw is None:
            raw = _OVERLAY_LEGACY_SIZES.get(
                str(ap.get("overlay_size", "中")), OVERLAY_VALUE_PX_DEFAULT
            )
        return max(OVERLAY_VALUE_PX_MIN, min(OVERLAY_VALUE_PX_MAX, int(raw)))

    @classmethod
    def _coerce_sections(cls, data: dict, issues: list[str]) -> dict:
        """逐字段预检数值类型，返回清理后的浅拷贝。

        非对象的节整节丢弃；无法转换为数字、布尔值冒充数字或非有限数值的
        字段从拷贝中删除，由后续构造使用 dataclass 默认值，其余字段保留。
        """
        result = dict(data)
        for section_name, section_type in cls._SECTION_TYPES.items():
            if section_name not in data:
                continue
            raw_section = data[section_name]
            if not isinstance(raw_section, dict):
                issues.append(f"{section_name} 节不是对象，已整节恢复默认")
                result.pop(section_name)
                continue
            section = dict(raw_section)
            numeric = {item.name: item.type for item in fields(section_type)
                       if item.type in (int, float, "int", "float")}
            if section_name in ("aircraft", "tank", "cas"):
                # 旧版随机间隔字段，迁移时会被 random_range 读取
                numeric["random_interval"] = int
            for name, kind in numeric.items():
                if name not in section:
                    continue
                raw = section[name]
                try:
                    if isinstance(raw, bool):
                        raise TypeError("布尔值不能作为数值")
                    value = float(raw)
                    if not math.isfinite(value):
                        raise ValueError("非有限数值")
                    converted = int(value) if kind in (int, "int") else value
                except (TypeError, ValueError, OverflowError):
                    issues.append(
                        f"{section_name}.{name} 值 {repr(raw)[:40]} 无效，已恢复默认")
                    del section[name]
                    continue
                section[name] = converted
            result[section_name] = section
        return result

    def _sanitize_config(self) -> list[str]:
        """把越界、非法枚举或 min>max 的字段逐个恢复为默认值，返回修正说明。"""
        issues: list[str] = []
        defaults = Config()

        def reset(section_name: str, names: tuple[str, ...], reason: str) -> None:
            section = getattr(self._config, section_name)
            default_section = getattr(defaults, section_name)
            for name in names:
                setattr(section, name, getattr(default_section, name))
            issues.append(f"{section_name}.{'/'.join(names)} {reason}，已恢复默认")

        def check_range(section_name: str, name: str, low: float,
                        high: float = math.inf) -> None:
            value = getattr(getattr(self._config, section_name), name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not low <= value <= high):
                bound = f"{low}..{high}" if math.isfinite(high) else f"≥{low}"
                reset(section_name, (name,), f"值 {value!r} 超出 {bound}")

        def check_pair(section_name: str, low_name: str, high_name: str) -> None:
            section = getattr(self._config, section_name)
            if getattr(section, low_name) > getattr(section, high_name):
                reset(section_name, (low_name, high_name), "最小值大于最大值")

        # 各通道强度（含事件强度与模式最大强度）必须在 0..200
        for section_name in ("aircraft", "tank", "cas", "events", "tank_events"):
            for name in vars(getattr(self._config, section_name)):
                if name.endswith(("_ch_a", "_ch_b")) or name in (
                        "channel_a_max", "channel_b_max"):
                    check_range(section_name, name, 0, 200)

        # 触发范围、随机间隔与曲线陡度
        for section_name, low_name, high_name in (
                ("aircraft", "gforce_min", "gforce_max"),
                ("tank", "speed_min", "speed_max"),
                ("cas", "gforce_min", "gforce_max")):
            check_range(section_name, low_name, 0)
            check_range(section_name, high_name, 0)
            check_pair(section_name, low_name, high_name)
            for suffix in ("_a", "_b"):
                check_range(section_name, f"random_min{suffix}", 5, 300)
                check_range(section_name, f"random_max{suffix}", 5, 300)
                check_pair(section_name, f"random_min{suffix}",
                           f"random_max{suffix}")
            check_range(section_name, "curve_steepness", 1.0, 6.0)

        check_range("tank", "idle_timeout_s", 1.0, 120.0)
        check_range("tank", "idle_speed_max", 0, 50.0)

        for section_name in ("events", "tank_events"):
            check_range(section_name, "kill_duration", 0.1, 30)
            check_range(section_name, "death_duration", 0.1, 30)
        check_range("tank_events", "hit_duration", 0.1, 30)
        check_range("tank_events", "hit_cooldown", 0, 30)

        app = self._config.app
        check_range("app", "ws_port", 1024, 65535)
        check_range("app", "refresh_interval_ms", 50, 1000)
        check_range("app", "overlay_size_px",
                    OVERLAY_VALUE_PX_MIN, OVERLAY_VALUE_PX_MAX)
        check_range("app", "card_opacity", 20, 90)
        if app.dglab_protocol not in {"v3", "v4"}:
            reset("app", ("dglab_protocol",), f"值 {app.dglab_protocol!r} 未知")
        if app.mode not in {"aircraft", "tank"}:
            reset("app", ("mode",), f"值 {app.mode!r} 未知")
        background_name = app.background_image
        if background_name and (
                background_name in {".", ".."}
                or "/" in background_name
                or "\\" in background_name
                or ".." in background_name
                or os.path.basename(background_name) != background_name
                or os.path.splitext(background_name)[1].lower()
                not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}):
            reset("app", ("background_image",), "壁纸文件名无效")
        return issues
