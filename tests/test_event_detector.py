"""战争雷霆 HUD 事件检测器回归测试。"""

import pytest

from src.config_manager import EventSettings, TankEventSettings
from src.event_detector import EventDetector
from src.game_reader import GameState, TankData


class QueuedReader:
    """按顺序返回预设 HUD 读取结果。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.last_dmg_ids = []

    def fetch_hudmsg_with_status(self, last_dmg_id):
        """返回下一组读取结果并记录调用游标。"""
        self.last_dmg_ids.append(last_dmg_id)
        return self.responses.pop(0)


def make_configs():
    """创建可区分空战和陆战输出的事件配置。"""
    aircraft = EventSettings(
        player_name="玩家",
        kill_enabled=True,
        kill_ch_a=11,
        kill_ch_b=12,
        kill_duration=3.0,
        kill_wf_a="空战击杀A",
        kill_wf_b="空战击杀B",
        death_enabled=True,
        death_ch_a=13,
        death_ch_b=14,
        death_duration=4.0,
        death_wf_a="空战坠毁A",
        death_wf_b="空战坠毁B",
    )
    tank = TankEventSettings(
        player_name="玩家",
        kill_enabled=True,
        kill_ch_a=21,
        kill_ch_b=22,
        kill_duration=5.0,
        kill_wf_a="陆战击杀A",
        kill_wf_b="陆战击杀B",
        death_enabled=True,
        death_ch_a=23,
        death_ch_b=24,
        death_duration=6.0,
        death_wf_a="陆战被毁A",
        death_wf_b="陆战被毁B",
        repair_enabled=True,
        repair_ch_a=25,
        repair_ch_b=26,
        repair_wf_a="维修A",
        repair_wf_b="维修B",
    )
    return aircraft, tank


def active_state(vehicle_type="tank", repairing=False):
    """创建有效对局状态。"""
    tank = None
    if vehicle_type == "tank":
        tank = TankData(valid=True, is_repairing=repairing)
    return GameState(
        connected=True,
        vehicle_type=vehicle_type,
        tank=tank,
    )


def test_first_successful_read_only_establishes_history_baseline():
    """首次成功读取只定位历史游标，不触发旧记录。"""
    reader = QueuedReader([(True, [
        {"id": 3, "msg": "玩家击毁了敌人"},
        {"id": 5, "msg": "玩家击毁了另一个敌人"},
    ])])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event == {}
    assert detector.cursor_ready
    assert detector.last_dmg_id == 5
    assert reader.last_dmg_ids == [0]


def test_failed_read_does_not_establish_history_baseline():
    """请求失败不能伪装成已读取到空历史。"""
    detector = EventDetector(QueuedReader([(False, [])]))
    aircraft, tank = make_configs()

    event = detector.poll(GameState(), "tank", aircraft, tank)

    assert event == {}
    assert not detector.cursor_ready
    assert detector.last_dmg_id == 0


def test_menu_consumes_new_ids_without_triggering_events():
    """菜单阶段持续推进游标，但不输出历史事件。"""
    reader = QueuedReader([
        (True, [{"id": 7, "msg": "旧记录"}]),
        (True, [{"id": 8, "msg": "玩家击毁了敌人"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(GameState(), "tank", aircraft, tank)

    assert event == {}
    assert detector.last_dmg_id == 8
    assert reader.last_dmg_ids == [0, 7]


def test_first_event_after_entering_a_new_match_triggers_immediately():
    """菜单已建立游标后，新对局首轮新增消息立即生效。"""
    reader = QueuedReader([
        (True, [{"id": 8, "msg": "菜单前的旧记录"}]),
        (True, [{"id": 9, "msg": "玩家击毁了敌人"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event["kind"] == "kill"
    assert event["mode"] == "tank"
    assert event["ch_a"] == 21
    assert detector.last_dmg_id == 9


def test_zero_width_characters_do_not_break_player_name_matching():
    """HUD 插入零宽字符后仍能识别玩家昵称。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": "玩\u200b家击落了敌人"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "aircraft", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "aircraft", aircraft, tank)

    assert event["kind"] == "kill"
    assert event["ch_a"] == 11


@pytest.mark.parametrize(
    "message",
    ["敌人击落了玩家", "玩家的载具已坠毁"],
)
def test_death_messages_are_detected(message):
    """被击落和自行坠毁文本均识别为死亡事件。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "aircraft", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "aircraft", aircraft, tank)

    assert event["kind"] == "death"
    assert event["ch_a"] == 13


@pytest.mark.parametrize(
    "message",
    [
        "玩家 (Spitfire) shot down Enemy (Bf 109)",
        "玩家 (T-34) destroyed Enemy (Panther)",
        "玩家 (Yak-3) сбил Enemy (Bf 109)",
        "玩家 (T-34) уничтожил Enemy (Panther)",
        "玩家 (Mirage) abattu Enemy (MiG-21)",
        "玩家 (Leclerc) détruit Enemy (T-80)",
        "玩家 (F-4F) abgeschossen Enemy (MiG-23)",
        "玩家 (Leopard) zerstört Enemy (T-72)",
        "玩家 (M1A1) 击毁了 Enemy (T-62)",
        "玩家 (M1A1) 擊毀了 Enemy (T-62)",
        "玩家 (F-15J) 撃墜されました Enemy (Su-27)",
        "玩家 (Type 90) によって\t撃破されました Enemy (T-80)",
    ],
)
def test_active_multilingual_kill_messages(message):
    """七种目标语言的主动击落和击毁格式均识别为击杀。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event["kind"] == "kill"
    assert event["ch_a"] == 21


@pytest.mark.parametrize(
    "message",
    [
        "Enemy (Spitfire) shot down 玩家 (Bf 109)",
        "Enemy (T-34) destroyed 玩家 (Panther)",
        "Enemy (Yak-3) сбил 玩家 (Bf 109)",
        "Enemy (T-34) уничтожил 玩家 (Panther)",
        "Enemy (Mirage) abattu 玩家 (MiG-21)",
        "Enemy (Leclerc) détruit 玩家 (T-80)",
        "Enemy (F-4F) abgeschossen 玩家 (MiG-23)",
        "Enemy (Leopard) zerstört 玩家 (T-72)",
        "Enemy (M1A1) 击毁了 玩家 (T-62)",
        "Enemy (M1A1) 擊毀了 玩家 (T-62)",
        "Enemy (F-15J) 撃墜されました 玩家 (Su-27)",
        "Enemy (Type 90) によって\t撃破されました 玩家 (T-80)",
    ],
)
def test_active_multilingual_death_messages(message):
    """七种目标语言的主动击落和击毁格式均能识别玩家死亡。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event["kind"] == "death"
    assert event["ch_a"] == 23


@pytest.mark.parametrize(
    "message",
    [
        "玩家 (Spitfire) has crashed.",
        "玩家 (Yak-3) разбился",
        "玩家 (Mirage) s'est écrasé.",
        "玩家 (F-4F) ist abgestürzt.",
        "玩家的载具已坠毁。",
        "玩家的載具已墜毀",
        "玩家 (F-15J) は\t墜落しました",
    ],
)
def test_multilingual_crash_messages(message):
    """七种目标语言的自行坠毁格式均识别为死亡。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "aircraft", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "aircraft", aircraft, tank)

    assert event["kind"] == "death"
    assert event["ch_a"] == 13


@pytest.mark.parametrize(
    ("message", "expected_kind"),
    [
        ("玩家 (Spitfire) shot down by Enemy (Bf 109)", "death"),
        ("Enemy (Spitfire) shot down by 玩家 (Bf 109)", "kill"),
        ("玩家 (Mirage) abattu par Enemy (MiG-21)", "death"),
        ("Enemy (Mirage) abattu par 玩家 (MiG-21)", "kill"),
        ("玩家 (F-4F) wurde abgeschossen von Enemy", "death"),
        ("Enemy wurde abgeschossen von 玩家 (F-4F)", "kill"),
        ("玩家 (Yak-3) сбит игроком Enemy", "death"),
        ("Enemy сбит игроком 玩家 (Yak-3)", "kill"),
        ("玩家已被击落，攻击者为 Enemy", "death"),
        ("Enemy 已被击落，攻击者为 玩家", "kill"),
        ("玩家已被擊落，攻擊者是 Enemy", "death"),
        ("Enemy 已被擊落，攻擊者是 玩家", "kill"),
    ],
)
def test_passive_multilingual_messages(message, expected_kind):
    """被动格式按玩家在关系词前后正确区分死亡和击杀。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event["kind"] == expected_kind


def test_damage_and_fire_messages_do_not_trigger_events():
    """普通损伤和点燃记录不能误报为击杀。"""
    reader = QueuedReader([
        (True, []),
        (True, [
            {"id": 1, "msg": "玩家 (Yak-141) damaged Enemy (BV 238)"},
            {"id": 2, "msg": "玩家 (Yak-141) set afire Enemy (BV 238)"},
        ]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "aircraft", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "aircraft", aircraft, tank)

    assert event == {}


@pytest.mark.parametrize(
    "message",
    [
        "=CLAN= TestPilot (◍\u200bM1A1 HC) 击\u200b毁\u200b了 IT-1",
        "=CLAN= TestPilot (◍M1A1 HC) によって\t撃破されました IT-1",
        "=CLAN= TestPilot (◍M1A1 HC) destroyed IT-1",
    ],
)
def test_captured_8111_kill_message_formats(message):
    """真实 8111 格式中的军团标签、特殊符号和隐藏字符不影响识别。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": message}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()
    aircraft.player_name = "TestPilot"
    tank.player_name = "TestPilot"

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state(), "tank", aircraft, tank)

    assert event["kind"] == "kill"


def test_duplicate_id_does_not_trigger_twice():
    """接口重复返回同一 ID 时只触发一次。"""
    record = {"id": 2, "msg": "玩家击毁了敌人"}
    reader = QueuedReader([
        (True, [{"id": 1, "msg": "旧记录"}]),
        (True, [record]),
        (True, [record]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    first = detector.poll(active_state(), "tank", aircraft, tank)
    duplicate = detector.poll(active_state(), "tank", aircraft, tank)

    assert first["kind"] == "kill"
    assert duplicate == {}
    assert reader.last_dmg_ids == [0, 1, 2]


def test_repair_only_triggers_on_rising_edge():
    """维修持续期间不重复触发，结束后再次维修可重新触发。"""
    reader = QueuedReader([(True, [])] * 5)
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(active_state(repairing=False), "tank", aircraft, tank)
    first = detector.poll(active_state(repairing=True), "tank", aircraft, tank)
    held = detector.poll(active_state(repairing=True), "tank", aircraft, tank)
    ended = detector.poll(active_state(repairing=False), "tank", aircraft, tank)
    second = detector.poll(active_state(repairing=True), "tank", aircraft, tank)

    assert first["kind"] == "repair"
    assert first["ch_a"] == 25
    assert held == {}
    assert ended == {}
    assert second["kind"] == "repair"


def test_kill_takes_priority_when_repair_starts_in_same_poll():
    """同轮开始维修并击杀时先返回击杀，维修边沿保持已消费状态。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": "玩家击毁了敌人"}]),
        (True, []),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(active_state(repairing=False), "tank", aircraft, tank)
    kill = detector.poll(active_state(repairing=True), "tank", aircraft, tank)
    held = detector.poll(active_state(repairing=True), "tank", aircraft, tank)

    assert kill["kind"] == "kill"
    assert held == {}


def test_actual_vehicle_type_selects_event_configuration():
    """实际载具类型优先于 UI 模式选择事件配置。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": "玩家击毁了敌人"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "aircraft", aircraft, tank)
    event = detector.poll(active_state("tank"), "aircraft", aircraft, tank)

    assert event["mode"] == "tank"
    assert event["ch_a"] == 21
    assert event["wf_a"] == "陆战击杀A"


def test_land_cas_uses_tank_event_configuration():
    """陆战模式上飞机时，CAS 事件使用陆战击杀/死亡参数。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": "玩家击落了敌机"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "tank", aircraft, tank,
                          cas_enabled=True)

    assert event["kind"] == "kill"
    assert event["mode"] == "aircraft"
    assert event["ch_a"] == 21
    assert event["ch_b"] == 22


def test_land_cas_disabled_consumes_records_without_event():
    """关闭 CAS 触发后仍推进 HUD 游标，但不输出飞机事件。"""
    reader = QueuedReader([
        (True, []),
        (True, [{"id": 1, "msg": "玩家击落了敌机"}]),
    ])
    detector = EventDetector(reader)
    aircraft, tank = make_configs()

    detector.poll(GameState(), "tank", aircraft, tank)
    event = detector.poll(active_state("aircraft"), "tank", aircraft, tank,
                          cas_enabled=False)

    assert event == {}
    assert detector.last_dmg_id == 1
