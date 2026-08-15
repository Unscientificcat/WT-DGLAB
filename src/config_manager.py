"""配置管理模块 — 读写 JSON 配置文件，管理所有用户设置"""

import json
import os
from dataclasses import dataclass, field, asdict
from urllib.parse import urlsplit


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
    random_interval: int = 30


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
    random_interval: int = 30


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
    random_interval: int = 30


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


@dataclass
class AppSettings:
    """应用全局设置"""
    ws_port: int = 8765              # WebSocket 服务端口
    dglab_protocol: str = "v3"       # DG-LAB App 协议: "v3" / "v4"
    v4_relay_url: str = "wss://trex.dungeon-lab.cn/v4"
    refresh_interval_ms: int = 200   # 数据刷新间隔(毫秒)
    mode: str = "aircraft"           # 当前模式: "aircraft" 或 "tank"
    overlay_enabled: bool = False    # 悬浮窗开关
    overlay_size: str = "中"          # 悬浮窗大小
    notice_accepted: bool = False     # 是否已同意注意事项


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
            except (json.JSONDecodeError, KeyError, TypeError):
                # 配置文件损坏时使用默认值
                self._config = Config()
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
        if "aircraft" in data:
            ac = data["aircraft"]
            self._config.aircraft = AircraftSettings(
                enabled=bool(ac.get("enabled", True)),
                gforce_min=float(ac.get("gforce_min", 1.0)),
                gforce_max=float(ac.get("gforce_max", 10.0)),
                channel_a_max=int(ac.get("channel_a_max", 0)),
                channel_b_max=int(ac.get("channel_b_max", 0)),
                waveform_a=str(ac.get("waveform_a", "恒定")),
                waveform_b=str(ac.get("waveform_b", "恒定")),
                random_interval=int(ac.get("random_interval", 30)),
            )
        if "tank" in data:
            tk = data["tank"]
            self._config.tank = TankSettings(
                enabled=bool(tk.get("enabled", True)),
                speed_min=float(tk.get("speed_min", 0)),
                speed_max=float(tk.get("speed_max", 60)),
                channel_a_max=int(tk.get("channel_a_max", 0)),
                channel_b_max=int(tk.get("channel_b_max", 0)),
                waveform_a=str(tk.get("waveform_a", "恒定")),
                waveform_b=str(tk.get("waveform_b", "恒定")),
                random_interval=int(tk.get("random_interval", 30)),
            )
        if "tank_events" in data:
            te = data["tank_events"]
            self._config.tank_events = TankEventSettings(
                player_name=str(te.get("player_name", "")),
                kill_enabled=bool(te.get("kill_enabled", False)),
                kill_ch_a=int(te.get("kill_ch_a", 0)),
                kill_ch_b=int(te.get("kill_ch_b", 0)),
                kill_duration=float(te.get("kill_duration", 5.0)),
                kill_wf_a=str(te.get("kill_wf_a", "恒定")),
                kill_wf_b=str(te.get("kill_wf_b", "恒定")),
                death_enabled=bool(te.get("death_enabled", False)),
                death_ch_a=int(te.get("death_ch_a", 0)),
                death_ch_b=int(te.get("death_ch_b", 0)),
                death_duration=float(te.get("death_duration", 5.0)),
                death_wf_a=str(te.get("death_wf_a", "恒定")),
                death_wf_b=str(te.get("death_wf_b", "恒定")),
                repair_enabled=bool(te.get("repair_enabled", False)),
                repair_ch_a=int(te.get("repair_ch_a", 0)),
                repair_ch_b=int(te.get("repair_ch_b", 0)),
                repair_wf_a=str(te.get("repair_wf_a", "恒定")),
                repair_wf_b=str(te.get("repair_wf_b", "恒定")),
            )
        if "cas" in data:
            cs = data["cas"]
            self._config.cas = CasSettings(
                enabled=bool(cs.get("enabled", True)),
                gforce_min=float(cs.get("gforce_min", 1.0)),
                gforce_max=float(cs.get("gforce_max", 10.0)),
                channel_a_max=int(cs.get("channel_a_max", 0)),
                channel_b_max=int(cs.get("channel_b_max", 0)),
                waveform_a=str(cs.get("waveform_a", "恒定")),
                waveform_b=str(cs.get("waveform_b", "恒定")),
                random_interval=int(cs.get("random_interval", 30)),
            )
        if "events" in data:
            ev = data["events"]
            self._config.events = EventSettings(
                player_name=str(ev.get("player_name", "")),
                kill_enabled=bool(ev.get("kill_enabled", False)),
                kill_ch_a=int(ev.get("kill_ch_a", 0)),
                kill_ch_b=int(ev.get("kill_ch_b", 0)),
                kill_duration=float(ev.get("kill_duration", 5.0)),
                kill_wf_a=str(ev.get("kill_wf_a", "恒定")),
                kill_wf_b=str(ev.get("kill_wf_b", "恒定")),
                death_enabled=bool(ev.get("death_enabled", False)),
                death_ch_a=int(ev.get("death_ch_a", 0)),
                death_ch_b=int(ev.get("death_ch_b", 0)),
                death_duration=float(ev.get("death_duration", 5.0)),
                death_wf_a=str(ev.get("death_wf_a", "恒定")),
                death_wf_b=str(ev.get("death_wf_b", "恒定")),
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
                overlay_size=str(ap.get("overlay_size", "中")),
                notice_accepted=bool(ap.get("notice_accepted", False)),
            )
