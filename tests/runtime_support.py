"""触发引擎测试共用的配置、快照和事实构造器。"""

from src.config_manager import Config
from src.game_reader import GameState, TankData, AircraftData
from src.trigger_models import GameEvent


def config():
    """生成能区分常规、事件和 CAS 的测试配置。"""
    cfg = Config()
    cfg.app.mode = "tank"
    for settings in (cfg.events, cfg.tank_events):
        settings.player_name = "玩家"
        for kind in ("kill", "death"):
            setattr(settings, f"{kind}_enabled", True)
            setattr(settings, f"{kind}_ch_a", 30 if kind == "kill" else 40)
            setattr(settings, f"{kind}_ch_b", 12)
    cfg.tank_events.repair_enabled = True
    cfg.tank_events.repair_ch_a = 20
    cfg.tank_events.hit_enabled = True
    cfg.tank_events.hit_ch_a = 10
    cfg.tank.speed_max = 30
    cfg.tank.channel_a_max = 5
    cfg.tank.channel_b_max = 3
    cfg.aircraft.channel_a_max = 50
    cfg.cas.channel_a_max = 70
    cfg.events.kill_ch_a = 80
    cfg.tank.idle_ch_a = 15
    return cfg


def state(now=100, vehicle="tank", mission="active", **tank):
    """构造具有明确采样时间和设备会话的完整采集结果。"""
    return GameState(
        connected=mission == "active", link_ok=True,
        mission_status=mission, vehicle_type=vehicle, sampled_at=now,
        hud_success=True, hud_sampled_at=now,
        tank=TankData(valid=True, speed_kmh=30, repair_supported=True,
                      damage_supported=True, **tank) if vehicle == "tank" else None,
        aircraft=AircraftData(valid=True, gforce=5) if vehicle == "aircraft" else None,
        event_session=("controller", 1), event_output_bound=True,
    )


def event(kind="kill", now=100, mode="tank", scene="tank", bound=True, session=None):
    """生成含首次观察资格的事件事实。"""
    return GameEvent(f"test:{now}:{kind}", kind, mode, scene, now,
                     session or ("controller", 1), bound)


def observe(engine, cfg, now=100, events=(), snapshot=None):
    """运行生产状态机及后台时钟。"""
    engine.observe(snapshot or state(now), events, cfg, now)
    return engine.tick(cfg, ("controller", 1), True, now)


