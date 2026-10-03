"""最新命令邮箱的回归测试（代码审查修复 B1）。"""

import queue
import threading

import pytest

from src.command_mailbox import CommandMailbox


def test_same_type_and_channel_keeps_latest():
    """同一 (类型, 通道) 只保留最新命令。"""
    box = CommandMailbox()
    for value in (10, 20, 30):
        box.put(("strength", "A", value))
    assert len(box) == 1
    assert box.get_nowait() == ("strength", "A", 30)
    assert box.empty()


def test_channels_are_independent():
    """A/B 通道命令互不覆盖。"""
    box = CommandMailbox()
    box.put(("strength", "A", 10))
    box.put(("strength", "B", 20))
    got = {box.get_nowait(), box.get_nowait()}
    assert got == {("strength", "A", 10), ("strength", "B", 20)}


def test_waveform_is_taken_before_strength():
    """同一轮内波形命令先于强度命令取出。"""
    box = CommandMailbox()
    box.put(("strength", "A", 50))
    box.put(("waveform", "A", "测试.pulse", False, 30, 50))
    assert box.get_nowait()[0] == "waveform"
    assert box.get_nowait()[0] == "strength"


def test_empty_raises_queue_empty():
    """无命令时与 queue.Queue 一样抛出 queue.Empty。"""
    with pytest.raises(queue.Empty):
        CommandMailbox().get_nowait()


def test_drop_removes_only_given_type():
    """drop 只丢弃指定类型，保留波形配置。"""
    box = CommandMailbox()
    box.put(("strength", "A", 10))
    box.put(("strength", "B", 10))
    box.put(("waveform", "A", "恒定", False, 30, 50))
    box.drop("strength")
    assert box.get_nowait()[0] == "waveform"
    assert box.empty()


def test_clear_removes_everything():
    """clear 丢弃全部命令。"""
    box = CommandMailbox()
    box.put(("strength", "A", 10))
    box.put(("waveform", "B", "恒定"))
    box.clear()
    assert box.empty()


def test_concurrent_put_is_bounded():
    """多线程高频提交时命令数不超过键数量。"""
    box = CommandMailbox()

    def worker(channel):
        for value in range(2000):
            box.put(("strength", channel, value % 200))

    threads = [threading.Thread(target=worker, args=(ch,)) for ch in "AB"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(box) == 2
