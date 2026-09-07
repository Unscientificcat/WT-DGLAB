"""玻璃主题背景、配置和离屏绘制回归测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QToolButton, QWidget
from PySide6.QtCore import Qt

from src.config_manager import ConfigManager
from src.gui.glass import BackgroundCatalog, BackdropCanvas, GlassCard
from src.gui.main_window import MainWindow


_APP = QApplication.instance() or QApplication([])


def test_background_catalog_filters_static_images(tmp_path):
    """目录只暴露支持的静态图片文件。"""
    directory = tmp_path / "backgrounds"
    directory.mkdir()
    Image.new("RGB", (20, 20), "red").save(directory / "Night.PNG")
    Image.new("RGB", (20, 20), "blue").save(directory / "day.jpg")
    (directory / "animated.gif").write_bytes(b"not a supported background")

    catalog = BackgroundCatalog(directory=directory, default_path=tmp_path / "default.png")

    assert catalog.choices() == ["默认壁纸", "day.jpg", "Night.PNG"]
    assert catalog.resolve("day.jpg") == directory / "day.jpg"
    assert catalog.resolve("NIGHT.png") == directory / "Night.PNG"
    assert catalog.resolve("../day.jpg") is None


def test_background_config_round_trip_and_invalid_name_fallback(tmp_path):
    """新字段可保存，路径穿越配置会回退安全默认值。"""
    path = tmp_path / "config.json"
    manager = ConfigManager(str(path))
    manager.config.app.background_enabled = False
    manager.config.app.background_image = "custom.png"
    manager.save()
    loaded = ConfigManager(str(path)).load()
    assert loaded.app.background_enabled is False
    assert loaded.app.background_image == "custom.png"

    path.write_text('{"app": {"background_image": "../secret.png"}}', encoding="utf-8")
    fallback = ConfigManager(str(path)).load()
    assert fallback.app.background_image == ""


def test_backdrop_and_glass_card_render_offscreen(tmp_path):
    """有效壁纸和玻璃卡片可以在无窗口环境绘制。"""
    image_path = tmp_path / "wallpaper.png"
    Image.new("RGB", (80, 50), (50, 100, 180)).save(image_path)
    catalog = BackgroundCatalog(directory=tmp_path / "backgrounds", default_path=image_path)
    canvas = BackdropCanvas(catalog=catalog)
    canvas.resize(320, 180)
    card = GlassCard(canvas)
    card.resize(120, 80)
    canvas.show()
    _APP.processEvents()

    assert not canvas._blurred.isNull()
    assert not card.grab().isNull()
    canvas.close()


def test_appearance_toggle_is_persisted_immediately(tmp_path):
    """外观开关点击后立即写入配置文件。"""
    path = tmp_path / "config.json"
    manager = ConfigManager(str(path))
    window = MainWindow(manager)
    window.settings_panel.appearance_button.click()
    window.settings_panel.background_enabled.setChecked(False)

    loaded = ConfigManager(str(path)).load()
    assert loaded.app.background_enabled is False
    assert window.backdrop.background_enabled is False
    window.close()


def test_card_opacity_slider_applies_and_persists(tmp_path):
    """卡片不透明度滑条即时更新玻璃层并持久化。"""
    path = tmp_path / "config.json"
    window = MainWindow(ConfigManager(str(path)))
    window.show()
    _APP.processEvents()
    slider = window.settings_panel.card_opacity_slider
    assert slider.objectName() == "cardOpacitySlider"
    assert (slider.minimum(), slider.maximum(), slider.value()) == (20, 90, 72)

    slider.setValue(35)
    _APP.processEvents()
    assert window.settings_panel.card_opacity_value.text() == "35%"
    assert window.backdrop.card_opacity == 35
    assert ConfigManager(str(path)).load().app.card_opacity == 35

    slider.setValue(72)
    window.close()


def test_card_opacity_validation_falls_back(tmp_path):
    """卡片不透明度越界时恢复默认值。"""
    path = tmp_path / "config.json"
    path.write_text('{"app": {"card_opacity": 99}}', encoding="utf-8")
    loaded = ConfigManager(str(path)).load()
    assert loaded.app.card_opacity == 72


def test_settings_are_split_into_mode_specific_cards(tmp_path):
    """参数页按当前模式显示对应的触发、CAS 和事件卡片。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    window.show()
    _APP.processEvents()

    panel = window.settings_panel
    assert panel.air_trigger_card.isVisible()
    assert panel.air_event_card.isVisible()
    assert not panel.tank_trigger_card.isVisible()
    assert not panel.cas_card.isVisible()
    assert panel.layout().contentsMargins().left() == 14
    assert panel.air_trigger_card.layout().contentsMargins().left() == 14
    assert isinstance(window.status_bar, GlassCard)
    assert not isinstance(window.dashboard, GlassCard)
    assert not isinstance(panel, GlassCard)
    assert not isinstance(window.qr_widget, GlassCard)
    assert isinstance(panel.air_trigger_card, GlassCard)
    assert panel.objectName() == "settingsPanel"

    panel.tank_button.click()
    _APP.processEvents()
    assert panel.tank_trigger_card.isVisible()
    assert panel.cas_card.isVisible()
    assert panel.tank_event_card.isVisible()
    window.close()


def test_event_card_is_always_expanded(tmp_path):
    """事件卡直接展示内容，不再提供折叠按钮。"""
    window = MainWindow(ConfigManager(str(tmp_path / "config.json")))
    window.show()
    _APP.processEvents()
    card = window.settings_panel.air_event_card
    assert card.findChild(QToolButton, "eventToggle") is None
    assert card.findChild(QWidget, "collapsibleContent") is None
    assert card.isVisible()
    window.close()
