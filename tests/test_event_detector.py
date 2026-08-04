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
