"""目录版发布和运行时路径回归测试。"""

import json
import os

import main
from build import validate_package
from src.runtime_paths import resource_path


def test_default_config_template_is_safe():
    """发布默认模板不应包含个人设置或非零输出。"""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "config.default.json"), encoding="utf-8") as file:
        data = json.load(file)

    assert data["app"]["dglab_protocol"] == "v3"
    assert data["app"]["notice_accepted"] is False
    assert data["events"]["player_name"] == ""
    assert data["aircraft"]["channel_a_max"] == 0
    assert data["tank_events"]["repair_ch_b"] == 0


def test_frozen_resource_path_uses_exe_directory(tmp_path, monkeypatch):
    """目录版运行时资源必须位于 EXE 同目录的 resources 下。"""
    exe_path = tmp_path / "WT-DGLAB.exe"
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "executable", str(exe_path))

    assert resource_path("tubiao.ico") == str(
        tmp_path / "resources" / "tubiao.ico"
    )
    assert main._config_file_path() == str(tmp_path / "config.json")


def test_validate_package_accepts_minimal_layout(tmp_path):
    """发布内容检查接受目标目录结构。"""
    package = tmp_path / "WT-DGLAB v1.0"
    (package / "_internal").mkdir(parents=True)
    (package / "resources").mkdir()
    for relative in (
            "WT-DGLAB.exe", "config.default.json", "README.md", "LICENSE",
            "resources/注意事项.txt", "resources/tubiao.ico",
            "resources/tubiao_ui.jpg", "resources/wallpaper_default.png"):
        path = package / relative
        path.write_text("test", encoding="utf-8")

    validate_package(package)


def test_validate_package_rejects_source_files(tmp_path):
    """发布内容检查拒绝源码文件。"""
    package = tmp_path / "package"
    (package / "_internal").mkdir(parents=True)
    (package / "resources").mkdir()
    for relative in (
            "WT-DGLAB.exe", "config.default.json", "README.md", "LICENSE",
            "resources/注意事项.txt", "resources/tubiao.ico",
            "resources/tubiao_ui.jpg", "resources/wallpaper_default.png"):
        path = package / relative
        path.write_text("test", encoding="utf-8")
    (package / "bad.py").write_text("pass", encoding="utf-8")

    try:
        validate_package(package)
    except RuntimeError as error:
        assert "bad.py" in str(error)
    else:
        raise AssertionError("源码文件未被发布内容检查拒绝")
