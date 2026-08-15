"""窗口图标和左上角品牌图片回归测试。"""

import os

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.config_manager import ConfigManager
from src.gui.main_window import MainWindow, _resource_path


def test_windows_icon_contains_multiple_standard_sizes():
    """tubiao1 转换后的图标包含 Windows 常用的多档尺寸。"""
    project_root = os.path.dirname(os.path.dirname(__file__))
    icon_path = os.path.join(project_root, "tubiao.ico")
    expected_sizes = {
        (16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
        (48, 48), (64, 64), (128, 128), (256, 256),
    }

    with Image.open(icon_path) as icon:
        assert icon.format == "ICO"
        assert icon.ico.sizes() == expected_sizes

    with Image.open(os.path.join(project_root, "tubiao_ui.jpg")) as brand:
        assert brand.size == (256, 256)

    with Image.open(os.path.join(project_root, "tubiao1.jpg")) as source:
        assert source.size == (2048, 2048)


def test_tubiao1_outputs_are_used_for_window_and_brand_icons(tmp_path):
    """窗口和左上角标记均成功加载 tubiao1 的转换产物。"""
    manager = ConfigManager(str(tmp_path / "config.json"))
    window = MainWindow(manager)

    assert window.windowTitle() == "郊狼雷霆 v1 beta_1"
    assert os.path.basename(_resource_path("tubiao_ui.jpg")) == "tubiao_ui.jpg"
    assert os.path.basename(_resource_path("tubiao.ico")) == "tubiao.ico"
    assert not window.windowIcon().isNull()
    assert window.status_bar.brand_mark.pixmap() is not None
    assert not window.status_bar.brand_mark.pixmap().isNull()
    assert window.status_bar.brand_mark.pixmap().size().width() == 38
    assert window.status_bar.brand_mark.pixmap().size().height() == 38
    window.close()


def test_refresh_interval_lives_on_dashboard_and_still_saves(tmp_path):
    """刷新间隔位于左侧仪表盘，并沿用原配置保存字段。"""
    config_path = tmp_path / "config.json"
    manager = ConfigManager(str(config_path))
    manager.config.app.refresh_interval_ms = 350
    window = MainWindow(manager)

    assert window.dashboard.isAncestorOf(window.dashboard.refresh_ms)
    assert not hasattr(window.qr_widget, "refresh_ms")
    assert window.dashboard.refresh_ms.value() == 350

    window.dashboard.refresh_ms.setValue(420)
    window.settings_panel.save_button.click()

    assert manager.config.app.refresh_interval_ms == 420
    assert ConfigManager(str(config_path)).load().app.refresh_interval_ms == 420
    window.close()


def test_cas_enabled_setting_loads_and_saves(tmp_path):
    """CAS 总开关在界面和配置之间正确同步。"""
    config_path = tmp_path / "config.json"
    manager = ConfigManager(str(config_path))
    manager.config.cas.enabled = False
    window = MainWindow(manager)

    assert window.settings_panel.cas_enabled.isChecked() is False
    window.settings_panel.cas_enabled.setChecked(True)
    window.settings_panel.save_button.click()

    assert manager.config.cas.enabled is True
    assert ConfigManager(str(config_path)).load().cas.enabled is True
    window.close()
