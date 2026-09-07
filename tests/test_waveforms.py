from pathlib import Path

from src.waveforms import WaveformCatalog, parse_pulse_text


SAMPLE = "Dungeonlab+pulse:20,1,16=0,30,44,2,1/0.00-1,33.30-0,66.65-0,100.00-1"


def test_parse_official_text_returns_pulses():
    pulses = parse_pulse_text(SAMPLE, "pulse-测试.pulse")
    assert pulses
    assert all(len(freqs) == 4 and len(strengths) == 4
               for freqs, strengths in pulses)


def test_catalog_keeps_full_name_and_skips_invalid(tmp_path: Path):
    (tmp_path / "pulse-有效.pulse").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "坏文件.pulse").write_text("invalid", encoding="utf-8")
    catalog = WaveformCatalog(tmp_path.parent)
    catalog.directory = tmp_path
    result = catalog.reload()
    assert catalog.choices() == ["恒定", "pulse-有效.pulse"]
    assert result.errors and result.errors[0][0] == "坏文件.pulse"


def test_catalog_only_scans_root(tmp_path: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.pulse").write_text(SAMPLE, encoding="utf-8")
    catalog = WaveformCatalog(tmp_path.parent)
    catalog.directory = tmp_path
    catalog.reload()
    assert catalog.choices() == ["恒定"]
