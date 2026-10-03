"""程序目录只读时的容错回归测试（代码审查修复 D1）。"""

import os
from pathlib import Path
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main
from build import _create_zip
from src.gui.glass import BackgroundCatalog
from src.waveforms import WaveformCatalog


def _deny_mkdir(monkeypatch):
    def fail(self, *args, **kwargs):
        raise PermissionError("只读目录")
    monkeypatch.setattr(Path, "mkdir", fail)


def test_catalogs_degrade_when_directory_unwritable(tmp_path, monkeypatch):
    """壁纸与波形目录无法创建时只保留默认项，不抛异常。"""
    _deny_mkdir(monkeypatch)
    backgrounds = BackgroundCatalog(tmp_path / "bg", tmp_path / "default.png")
    assert backgrounds.ensure_directory() is False
    assert backgrounds.reload() == ()
    assert backgrounds.choices() == ["默认壁纸"]

    waveforms = WaveformCatalog(tmp_path)
    result = waveforms.reload()
    assert result.definitions == () and result.errors == ()
    assert waveforms.choices() == ["恒定"]


def test_config_save_failure_on_first_start_keeps_running(tmp_path, monkeypatch):
    """首次生成配置失败时记录原因并继续使用内存默认配置。"""
    monkeypatch.setattr(main, "_application_directory", lambda: str(tmp_path))

    def fail(self):
        raise PermissionError("拒绝访问")
    monkeypatch.setattr(main.ConfigManager, "save", fail)
    manager = main._load_config_manager()
    assert "程序目录不可写" in manager.save_error
    assert not (tmp_path / "config.json").exists()


def test_zip_contains_empty_placeholders_without_pulse(tmp_path):
    """发布 ZIP 含空的 waveforms/ 与 backgrounds/ 占位，不含个人波形。"""
    package = tmp_path / "WT-DGLAB v1.1"
    (package / "waveforms").mkdir(parents=True)
    (package / "backgrounds").mkdir()
    (package / "README.md").write_text("test", encoding="utf-8")
    zip_path = tmp_path / "out.zip"
    _create_zip(package, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert f"{package.name}/waveforms/" in names
    assert f"{package.name}/backgrounds/" in names
    assert not any(name.endswith(".pulse") for name in names)


def test_validate_package_rejects_personal_waveforms(tmp_path):
    """发布内容检查拒绝混入 waveforms/*.pulse。"""
    from build import validate_package
    package = tmp_path / "package"
    (package / "_internal").mkdir(parents=True)
    (package / "resources").mkdir()
    (package / "waveforms").mkdir()
    for relative in (
            "WT-DGLAB.exe", "config.default.json", "README.md", "LICENSE",
            "resources/注意事项.txt", "resources/tubiao.ico",
            "resources/tubiao_ui.jpg", "resources/wallpaper_default.png"):
        (package / relative).write_text("test", encoding="utf-8")
    (package / "waveforms" / "个人.pulse").write_text("x", encoding="utf-8")
    try:
        validate_package(package)
    except RuntimeError as error:
        assert "个人.pulse" in str(error)
    else:
        raise AssertionError("个人波形未被发布内容检查拒绝")
