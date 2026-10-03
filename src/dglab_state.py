"""郊狼连接与输出的不可变跨线程接口。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WaveformConfig:
    """一个通道的波形与随机策略。"""

    name: str = "恒定"
    random_enabled: bool = False
    random_min: int = 30
    random_max: int = 50


@dataclass(frozen=True)
class ChannelTarget:
    """游戏期望的通道输出。"""

    strength: int = 0
    waveform: WaveformConfig = WaveformConfig()


@dataclass(frozen=True)
class OutputIntent:
    """同一游戏采样的双通道输出；期限使用 monotonic 时钟。"""

    a: ChannelTarget = ChannelTarget()
    b: ChannelTarget = ChannelTarget()
    source: str = "normal"
    expires_at: float | None = None


@dataclass(frozen=True)
class DeviceSnapshot:
    """当前 App 暴露的设备候选。"""

    slot_id: str
    name: str
    available: bool


@dataclass(frozen=True)
class ChannelSnapshot:
    """严格区分游戏目标、发送结果与 App 实际上报。"""

    target: int = 0
    sent: int = 0
    reported: int | None = None
    reported_at: float | None = None
    limit: int | None = None
    muted: bool = False
    pending_stop: bool = False
    error: str = ""


@dataclass(frozen=True)
class ConnectionSnapshot:
    """GUI 读取的完整连接快照，不包含可变容器。"""

    session: int = 0
    state: str = "idle"
    server_running: bool = False
    client_connected: bool = False
    bound: bool = False
    address: str = ""
    error: str = ""
    qr_url: str = ""
    selected_device: str = ""
    devices: tuple[DeviceSnapshot, ...] = ()
    a: ChannelSnapshot = ChannelSnapshot()
    b: ChannelSnapshot = ChannelSnapshot()
