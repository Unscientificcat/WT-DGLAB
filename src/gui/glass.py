"""玻璃主题的背景目录、壁纸缓存和卡片绘制组件。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QWidget

from ..runtime_paths import application_directory, resource_path


SUPPORTED_BACKGROUND_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def _pil_to_qimage(image: Image.Image) -> QImage:
    """将 Pillow 图片复制为 Qt 图片，避免引用临时缓冲区。"""
    rgba = image.convert("RGBA")
    return QImage(
        rgba.tobytes("raw", "RGBA"),
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format_RGBA8888,
    ).copy()


class BackgroundCatalog:
    """管理 EXE 同级 backgrounds 目录中的静态壁纸。"""

    def __init__(self, directory: str | Path | None = None,
                 default_path: str | Path | None = None):
        self.directory = (
            Path(directory) if directory is not None
            else Path(application_directory()) / "backgrounds"
        )
        self.default_path = Path(default_path or resource_path("wallpaper_default.png"))
        self._files: dict[str, Path] = {}
        self.reload()

    def ensure_directory(self) -> None:
        """创建用户壁纸目录。"""
        self.directory.mkdir(parents=True, exist_ok=True)

    def reload(self) -> tuple[str, ...]:
        """扫描有效静态壁纸并返回文件名。"""
        self.ensure_directory()
        files: dict[str, Path] = {}
        for path in sorted(self.directory.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.casefold() in SUPPORTED_BACKGROUND_EXTENSIONS:
                files[path.name] = path
        self._files = files
        return tuple(files)

    def choices(self) -> list[str]:
        """返回下拉框选项，默认壁纸始终位于首位。"""
        return ["默认壁纸", *self._files]

    def resolve(self, name: str) -> Optional[Path]:
        """解析壁纸名称；非法或不存在的名称返回空值。"""
        if not name:
            return self.default_path if self.default_path.is_file() else None
        key = name.casefold()
        for filename, path in self._files.items():
            if filename.casefold() == key:
                return path
        return None

    def canonical_name(self, name: str) -> str | None:
        """返回目录中与输入大小写无关的规范文件名。"""
        if not name:
            return ""
        key = name.casefold()
        for filename in self._files:
            if filename.casefold() == key:
                return filename
        return None

    def is_valid_name(self, name: str) -> bool:
        """判断配置中的文件名是否为当前目录内的有效文件。"""
        return self.canonical_name(name) is not None


class BackdropCanvas(QWidget):
    """主窗口底层背景画布，缓存逻辑分辨率的模糊壁纸。"""

    def __init__(self, parent: QWidget | None = None,
                 catalog: BackgroundCatalog | None = None):
        super().__init__(parent)
        self.setObjectName("appSurface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._catalog = catalog or BackgroundCatalog()
        self._enabled = True
        self._name = ""
        self._card_opacity = 72
        self._base = QPixmap()
        self._blurred = QPixmap()
        self._brightness = 1.0
        self._version = 0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(250)
        self._resize_timer.timeout.connect(self._rebuild_cache)
        self._screen_connected = False

    @property
    def catalog(self) -> BackgroundCatalog:
        """返回背景目录。"""
        return self._catalog

    @property
    def background_name(self) -> str:
        """返回当前用户壁纸文件名，空值表示默认壁纸。"""
        return self._name

    @property
    def background_enabled(self) -> bool:
        """返回背景开关状态。"""
        return self._enabled

    @property
    def card_opacity(self) -> int:
        """返回玻璃卡片不透明度百分比。"""
        return self._card_opacity

    def set_card_opacity(self, value: int) -> None:
        """设置玻璃卡片不透明度并刷新所有卡片。"""
        self._card_opacity = max(20, min(90, int(value)))
        self.update()
        self._update_cards()

    @property
    def cache_version(self) -> int:
        """返回背景缓存版本号。"""
        return self._version

    def set_background(self, enabled: bool, name: str = "") -> bool:
        """应用背景开关和文件名，返回是否成功解析所选壁纸。"""
        self._enabled = bool(enabled)
        self._name = name if self._catalog.is_valid_name(name) else ""
        if self._name != name:
            self._name = ""
        self._rebuild_cache()
        return not self._enabled or not self._base.isNull()

    def set_background_name(self, name: str) -> bool:
        """切换壁纸并立即重建缓存。"""
        return self.set_background(self._enabled, name)

    def resizeEvent(self, event) -> None:
        """保留旧缓存并延迟重建，避免拖动窗口时频繁模糊。"""
        super().resizeEvent(event)
        if self._base.isNull():
            self._rebuild_cache()
        else:
            self.update()
            self._resize_timer.start()

    def showEvent(self, event) -> None:
        """窗口首次显示后按最终布局尺寸生成背景缓存。"""
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_connected:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_connected = True
        QTimer.singleShot(0, self._rebuild_cache)

    def _on_screen_changed(self, screen) -> None:
        """切换显示器时重建不同 DPI 下的背景缓存。"""
        self._rebuild_cache()

    def _rebuild_cache(self) -> None:
        """加载、裁切、增强并缓存当前逻辑尺寸的壁纸。"""
        self._version += 1
        if not self._enabled or self.width() <= 0 or self.height() <= 0:
            self._base = QPixmap()
            self._blurred = QPixmap()
            self.update()
            self._update_cards()
            return

        path = self._catalog.resolve(self._name)
        if path is None:
            self._base = QPixmap()
            self._blurred = QPixmap()
            self.update()
            self._update_cards()
            return
        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
                target_w, target_h = max(1, self.width()), max(1, self.height())
                scale = max(target_w / image.width, target_h / image.height)
                size = (max(target_w, int(image.width * scale)),
                        max(target_h, int(image.height * scale)))
                image = image.resize(size, Image.Resampling.LANCZOS)
                left = (image.width - target_w) // 2
                top = (image.height - target_h) // 2
                image = image.crop((left, top, left + target_w, top + target_h))
                image = ImageEnhance.Color(image).enhance(1.15)
                brightness = sum(image.resize((1, 1)).getpixel((0, 0))) / 765
                self._brightness = brightness
                self._base = QPixmap.fromImage(_pil_to_qimage(image))
                blurred = image.filter(ImageFilter.GaussianBlur(32))
                self._blurred = QPixmap.fromImage(_pil_to_qimage(blurred))
        except (OSError, ValueError, TypeError):
            self._base = QPixmap()
            self._blurred = QPixmap()
        self.update()
        self._update_cards()

    def _update_cards(self) -> None:
        """通知同窗口的玻璃卡片重新裁切背景。"""
        root = self.window()
        if root is self:
            return
        for card in root.findChildren(GlassCard):
            card.update()

    def crop_for(self, widget: QWidget) -> QPixmap:
        """裁切指定控件在背景画布中的对应区域。"""
        if self._blurred.isNull():
            return QPixmap()
        point = widget.mapTo(self, QPoint(0, 0))
        rect = QRect(point, widget.size()).intersected(self.rect())
        if rect.isEmpty():
            return QPixmap()
        return self._blurred.copy(rect)

    def overlay_alpha(self) -> int:
        """根据背景亮度返回玻璃白色叠加透明度。"""
        if self._blurred.isNull():
            return 245
        alpha = int(255 * self._card_opacity / 100)
        if self._brightness < 0.48:
            alpha += 18
        return min(245, alpha)

    def paintEvent(self, event) -> None:
        """绘制背景、可读性滤罩和细微噪点。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._base.isNull():
            painter.drawPixmap(self.rect(), self._base)
            painter.fillRect(self.rect(), QColor(244, 247, 252, 72 if self._brightness >= 0.48 else 96))
            painter.setOpacity(0.035)
            painter.fillRect(self.rect(), QColor(255, 255, 255, 255))
            painter.setOpacity(1.0)
        else:
            painter.fillRect(self.rect(), QColor("#F0F6FC"))


class GlassCard(QFrame):
    """从背景缓存裁切并绘制圆角磨砂玻璃面板。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("glassCard", True)

    def _canvas(self) -> BackdropCanvas | None:
        """查找当前窗口的背景画布。"""
        window = self.window()
        canvas = getattr(window, "backdrop", None)
        return canvas if isinstance(canvas, BackdropCanvas) else None

    def paintEvent(self, event) -> None:
        """绘制卡片背景和边框，再交由 Qt 绘制子控件。"""
        if self.property("glassDisabled"):
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        painter.setClipPath(path)
        canvas = self._canvas()
        crop = canvas.crop_for(self) if canvas else QPixmap()
        if not crop.isNull():
            painter.drawPixmap(self.rect(), crop)
            alpha = canvas.overlay_alpha() if canvas else 205
            painter.fillPath(path, QColor(255, 255, 255, alpha))
        else:
            painter.fillPath(path, QColor(255, 255, 255, 245))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 95), 1))
        painter.drawLine(11, 1, max(11, self.width() - 12), 1)
        super().paintEvent(event)
