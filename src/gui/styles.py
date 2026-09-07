"""PySide6 浅色主题样式定义。"""

from PySide6.QtWidgets import QApplication


COLORS = {
    "bg_main": "#F4F7FC",
    "bg_panel": "#FFFFFF",
    "bg_soft": "#EDF4FC",
    "primary": "#4B89D8",
    "primary_hover": "#3474C4",
    "aqua": "#62BFD1",
    "pink": "#EC8DA7",
    "text_primary": "#26364A",
    "text_secondary": "#718095",
    "success": "#46B68A",
    "warning": "#E6A85D",
    "error": "#E36D7D",
    "border": "#D8E3F0",
    "input": "#F9FBFE",
}

FONTS = {
    "default": "Microsoft YaHei, Segoe UI",
    "mono": "Cascadia Mono, Consolas",
}


STYLESHEET = f"""
QMainWindow#appWindow, QWidget#appSurface {{
    background: transparent;
    color: {COLORS['text_primary']};
    font-family: {FONTS['default']};
    font-size: 13px;
}}
QFrame#headerBar, QFrame#dashboardPanel, QFrame#settingsPanel, QFrame#connectionPanel,
QFrame#noticeBottom {{
    background: transparent;
    border: 0;
    border-radius: 8px;
}}
QFrame#sectionCard {{
    background: transparent;
    border: 0;
    border-radius: 10px;
}}
QFrame#headerBar {{
    min-height: 62px;
}}
QLabel#brandMark {{
    background: {COLORS['primary']};
    border-radius: 8px;
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
}}
QLabel#brandTitle {{
    color: {COLORS['text_primary']};
    font-size: 19px;
    font-weight: 700;
}}
QLabel#brandSubtitle, QLabel#hintText, QLabel#addressText {{
    color: {COLORS['text_secondary']};
}}
QLabel#sectionTitle {{
    color: {COLORS['text_primary']};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#eyebrow {{
    color: {COLORS['primary']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#liveValue {{
    color: {COLORS['text_primary']};
    font-size: 50px;
    font-weight: 700;
}}
QLabel#liveUnit {{
    color: {COLORS['text_secondary']};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#eventText {{
    color: {COLORS['pink']};
    font-size: 13px;
    font-weight: 700;
}}
QFrame#statusPill {{
    background: {COLORS['bg_soft']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}
QLabel#statusDot {{
    font-size: 15px;
}}
QLabel#statusName {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
}}
QLabel#statusValue {{
    color: {COLORS['text_primary']};
    font-size: 12px;
    font-weight: 700;
}}
QFrame#channelCard {{
    background: transparent;
    border: 0;
}}
QFrame#waveformHeader, QFrame#waveformNav, QFrame#waveformEditor,
QFrame#waveformFooter {{
    background: transparent;
    border: 0;
}}
QFrame#waveformChannelCard {{
    background: transparent;
    border: 0;
}}
QListWidget#waveformSceneList {{
    background: transparent;
    border: 0;
    outline: 0;
    color: {COLORS['text_secondary']};
}}
QListWidget#waveformSceneList::item {{
    padding: 10px 9px;
    border-radius: 6px;
    margin: 2px 0;
}}
QListWidget#waveformSceneList::item:selected {{
    color: {COLORS['primary']};
    background: white;
    font-weight: 700;
}}
QFrame#statusSeparator {{
    background: {COLORS['border']};
    max-height: 1px;
    border: 0;
}}
QLabel#channelName {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#channelValue {{
    color: {COLORS['text_primary']};
    font-size: 20px;
    font-weight: 700;
}}
QProgressBar {{
    background: {COLORS['bg_soft']};
    border: 0;
    border-radius: 4px;
    min-height: 7px;
    max-height: 7px;
}}
QProgressBar::chunk {{
    background: {COLORS['primary']};
    border-radius: 4px;
}}
QProgressBar#channelB::chunk {{
    background: {COLORS['aqua']};
}}
QToolButton#modeButton, QToolButton#dashboardModeButton, QToolButton#sizeButton, QPushButton#modeButton {{
    color: {COLORS['text_secondary']};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 12px;
    font-weight: 700;
}}
QToolButton#eventToggle {{
    color: {COLORS['text_primary']};
    background: rgba(255, 255, 255, 175);
    border: 1px solid rgba(216, 227, 240, 200);
    border-radius: 8px;
    padding: 0 12px;
    min-height: 38px;
    text-align: left;
    font-weight: 700;
}}
QToolButton#eventToggle:hover {{
    background: rgba(255, 255, 255, 220);
    border-color: rgba(75, 137, 216, 150);
}}
QToolButton#eventToggle:checked {{
    background: rgba(237, 244, 252, 220);
    border-color: {COLORS['primary']};
    color: {COLORS['primary']};
}}
QToolButton#modeButton:checked, QToolButton#dashboardModeButton:checked, QToolButton#sizeButton:checked, QPushButton#modeButton:checked {{
    color: {COLORS['primary']};
    background: {COLORS['bg_soft']};
    border-color: {COLORS['border']};
}}
QToolButton#dashboardModeButton {{
    padding: 1px 5px;
    font-size: 12px;
}}
QPushButton {{
    background: {COLORS['primary']};
    color: white;
    border: 0;
    border-radius: 6px;
    min-height: 34px;
    padding: 0 14px;
    font-weight: 700;
}}
QPushButton:hover {{ background: {COLORS['primary_hover']}; }}
QPushButton#secondaryButton, QPushButton#overlayContentButton {{
    background: {COLORS['bg_panel']};
    color: {COLORS['primary']};
    border: 1px solid {COLORS['border']};
}}
QPushButton#secondaryButton:hover, QPushButton#overlayContentButton:hover {{ background: {COLORS['bg_soft']}; }}
QPushButton#textButton, QPushButton#aboutButton {{
    background: transparent;
    color: {COLORS['primary']};
    border: 0;
    padding: 0 6px;
    min-height: 28px;
}}
QCheckBox {{
    color: {COLORS['text_primary']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    background: white;
}}
QCheckBox::indicator:checked {{
    background: {COLORS['primary']};
    border-color: {COLORS['primary']};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    color: {COLORS['text_primary']};
    background: {COLORS['input']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    min-height: 30px;
    padding: 0 8px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {COLORS['primary']};
    background: white;
}}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox QAbstractItemView {{
    background: white;
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['bg_soft']};
}}
QLabel#formLabel {{
    color: {COLORS['text_secondary']};
}}
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport,
QWidget#settingsContent, QStackedWidget#settingsPages,
QWidget#appearancePage, QWidget#waveformPage, QWidget#collapsibleContent,
QSplitter#mainSplitter, QFrame#protocolSelector {{
    background: transparent;
    border: 0;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QFrame#qrFrame {{
    background: white;
    border: 1px dashed {COLORS['border']};
    border-radius: 8px;
}}
QMenu#trayMenu {{
    background: rgba(255, 255, 255, 245);
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 5px;
}}
QMenu#trayMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 5px; }}
QMenu#trayMenu::item:selected {{ background: {COLORS['bg_soft']}; color: {COLORS['primary']}; }}
QMenu#overlaySizeMenu {{
    background: rgba(255, 255, 255, 245);
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu#overlaySizeMenu QLabel#overlaySizeValue {{
    color: {COLORS['primary']};
    font-weight: 700;
    background: transparent;
}}
QTextBrowser#noticeText {{
    color: {COLORS['text_primary']};
    background: {COLORS['input']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px;
}}
QLabel#qrImage {{
    color: {COLORS['text_secondary']};
    font-weight: 700;
}}
QFrame#overlaySurface {{
    background: transparent;
    border: 0;
}}
QFrame#overlaySurface QLabel {{
    background: transparent;
}}
QLabel#overlayValue {{
    color: {COLORS['text_primary']};
    font-weight: 700;
}}
QLabel#overlayA {{ color: {COLORS['pink']}; font-weight: 700; }}
QLabel#overlayB {{ color: {COLORS['aqua']}; font-weight: 700; }}
QLabel#overlayMode {{ color: {COLORS['primary']}; font-weight: 700; }}
QLabel#overlayWave {{
    color: {COLORS['text_secondary']};
    font-weight: 600;
}}
QLabel#channelWaveName {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
}}
QLabel#channelWaveHint {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
}}
QDialog#channelScopeDialog {{
    background: {COLORS['bg_panel']};
}}
QLabel#scopeInfoLabel {{
    color: {COLORS['text_secondary']};
    font-size: 13px;
    font-weight: 700;
}}
QDialog#overlayContentDialog {{
    background: {COLORS['bg_panel']};
}}
QDialog#aboutDialog {{
    background: {COLORS['bg_panel']};
}}
QLabel#aboutTitle {{
    color: {COLORS['text_primary']};
    font-size: 19px;
    font-weight: 700;
}}
QLabel#aboutSubtitle {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#aboutVersion {{
    color: {COLORS['primary']};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#aboutInfo {{
    color: {COLORS['text_primary']};
    font-weight: 600;
}}
QLabel#aboutLink {{
    color: {COLORS['text_primary']};
}}
QLabel#aboutNote {{
    color: {COLORS['text_secondary']};
    font-size: 11px;
}}
QFrame#aboutSeparator {{
    background: {COLORS['border']};
    max-height: 1px;
    border: 0;
}}
"""


def setup_styles(app: QApplication | None = None) -> None:
    """为 Qt 应用设置统一的浅色样式。"""
    application = app or QApplication.instance()
    if application is None:
        return
    application.setStyle("Fusion")
    application.setStyleSheet(STYLESHEET)
