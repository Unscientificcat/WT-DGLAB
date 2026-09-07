"""输出遥测记录器回归测试。"""

import threading

from src.output_telemetry import (
    CONSTANT_WAVEFORM,
    OutputTelemetry,
    display_waveform_name,
)


def test_display_name_strips_pulse_suffix():
    """显示名称去掉 .pulse 后缀，恒定原样返回。"""
    assert display_waveform_name("挥鞭.pulse") == "挥鞭"
    assert display_waveform_name("恒定") == "恒定"
    assert display_waveform_name("") == CONSTANT_WAVEFORM
    assert display_waveform_name(None) == CONSTANT_WAVEFORM
    assert display_waveform_name("脉冲.pulse.pulse") == "脉冲.pulse"


def test_snapshot_defaults_to_constant_and_silent():
    """新记录器默认恒定波形且无输出。"""
    telemetry = OutputTelemetry()

    snapshot = telemetry.snapshot("A")

    assert snapshot.name == CONSTANT_WAVEFORM
    assert snapshot.strength == 0
    assert not snapshot.active
    assert snapshot.batches == ()


def test_record_pulse_keeps_strength_and_amplitudes():
    """记录批次后快照携带波形名、强度和最终幅度。"""
    telemetry = OutputTelemetry()
    telemetry.record_waveform("A", "挥鞭.pulse")

    telemetry.record_pulse("A", (10, 50, 90, 120), 160)
    snapshot = telemetry.snapshot("A")

    assert snapshot.name == "挥鞭.pulse"
    assert snapshot.strength == 160
    assert snapshot.active
    assert snapshot.batches[-1].amplitudes == (10, 50, 90, 100)


def test_record_pulse_pads_and_clamps_amplitudes():
    """幅度不足 4 个补零，负值钳为 0，超大值钳为 100。"""
    telemetry = OutputTelemetry()

    telemetry.record_pulse("B", (-5, 50, 300), 100)
    snapshot = telemetry.snapshot("B")

    assert snapshot.batches[-1].amplitudes == (0, 50, 100, 0)
    assert snapshot.strength == 100


def test_record_silence_clears_output_state():
    """记录静默后强度归零且附带零幅度批次。"""
    telemetry = OutputTelemetry()
    telemetry.record_pulse("A", (80, 80, 80, 80), 120)

    telemetry.record_silence("A")
    snapshot = telemetry.snapshot("A")

    assert not snapshot.active
    assert snapshot.strength == 0
    assert snapshot.batches[-1].amplitudes == (0, 0, 0, 0)
    # 静默前的批次仍然保留在窗口内
    assert len(snapshot.batches) == 2


def test_batch_window_is_trimmed_to_maxlen():
    """批次窗口按 maxlen 裁剪，只保留最近的记录。"""
    telemetry = OutputTelemetry(max_batches=3)

    for _ in range(6):
        telemetry.record_pulse("A", (50, 50, 50, 50), 100)

    snapshot = telemetry.snapshot("A")
    assert len(snapshot.batches) == 3


def test_reset_clears_batches_but_keeps_waveform_name():
    """重置清空输出记录，波形名保留供界面继续显示。"""
    telemetry = OutputTelemetry()
    telemetry.record_waveform("A", "挥鞭.pulse")
    telemetry.record_pulse("A", (80, 80, 80, 80), 120)

    telemetry.reset()

    snapshot = telemetry.snapshot("A")
    assert snapshot.name == "挥鞭.pulse"
    assert snapshot.batches == ()
    assert not snapshot.active


def test_unknown_channel_falls_back_to_a():
    """未知通道名归入 A，不产生越界记录。"""
    telemetry = OutputTelemetry()

    telemetry.record_waveform("C", "挥鞭.pulse")
    telemetry.record_pulse("C", (10, 10, 10, 10), 50)

    assert telemetry.snapshot("C").name == "挥鞭.pulse"
    assert telemetry.snapshot("A").name == "挥鞭.pulse"
    assert len(telemetry.snapshot("A").batches) == 1


def test_snapshot_is_safe_during_concurrent_recording():
    """记录线程持续写入时快照线程可安全读取。"""
    telemetry = OutputTelemetry()
    errors = []

    def writer():
        for index in range(200):
            try:
                telemetry.record_pulse("A", (index % 100,) * 4, index % 200)
                telemetry.snapshot("A")
            except Exception as error:  # pragma: no cover - 保护网
                errors.append(error)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(telemetry.snapshot("A").batches) == 40
