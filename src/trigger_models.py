"""游戏触发链路的事件、播放上下文与只读界面快照。"""

from dataclasses import dataclass

from .dglab_state import ChannelTarget, OutputIntent
from .game_reader import GameState


@dataclass(frozen=True)
class GameEvent:
    """一条已识别的游戏事实；开关与输出优先级由触发引擎决定。"""

    event_id: str
    kind: str
    mode: str
    scene: str
    observed_at: float
    session: tuple
    bound: bool
    message: str = ""


@dataclass(frozen=True)
class Playback:
    """接受事件时固定配置、期限和首次观察的设备资格。"""

    event: GameEvent
    a: ChannelTarget
    b: ChannelTarget
    deadline: float | None


@dataclass(frozen=True)
class TriggerSnapshot:
    """主窗口与悬浮窗共用的业务结果，不包含 GUI 控件。"""

    game: GameState
    mode: str
    kind: str = ""
    event_mode: str = ""
    remaining: float = 0.0
    a: int = 0
    b: int = 0
    label: str = ""
    output_allowed: bool = False
    intent: OutputIntent = OutputIntent()
    diagnostic: str = ""
    wave_a: str = "恒定"
    wave_b: str = "恒定"
