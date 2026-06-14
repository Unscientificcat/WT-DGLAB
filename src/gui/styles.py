"""淡蓝色主题样式定义 — tkinter ttk 样式配置"""

import tkinter as tk
from tkinter import ttk

# 颜色常量（与设计规范一致）
COLORS = {
    "bg_main": "#F0F6FC",
    "bg_card": "#FFFFFF",
    "primary": "#4A90D9",
    "primary_hover": "#357ABD",
    "accent": "#5BA0E8",
    "text_primary": "#2C3E50",
    "text_secondary": "#7F8C8D",
    "success": "#27AE60",
    "error": "#E74C3C",
    "progress_bg": "#E8F0F8",
    "border": "#D6E4F0",
    "input_bg": "#F7FAFD",
}

FONTS = {
    "default": ("Microsoft YaHei", 10),
    "heading": ("Microsoft YaHei", 12, "bold"),
    "value": ("Microsoft YaHei", 28, "bold"),
    "unit": ("Microsoft YaHei", 12),
    "small": ("Microsoft YaHei", 9),
    "mono": ("Consolas", 10),
}


def setup_styles():
    """配置 ttk 主题样式，实现淡蓝色主题"""
    style = ttk.Style()

    # 尝试使用更现代的主题
    available = style.theme_names()
    preferred = "clam"  # clam 主题支持较好的自定义
    if preferred in available:
        style.theme_use(preferred)

    # === 全局背景 ===
    style.configure(".", background=COLORS["bg_main"], foreground=COLORS["text_primary"])

    # === 框架 ===
    style.configure("Card.TFrame", background=COLORS["bg_card"])
    style.configure("StatusBar.TFrame", background=COLORS["bg_card"])
    style.configure("Panel.TFrame", background=COLORS["bg_main"])

    # === 标签 ===
    style.configure("TLabel", background=COLORS["bg_main"], foreground=COLORS["text_primary"])
    style.configure("Card.TLabel", background=COLORS["bg_card"], foreground=COLORS["text_primary"])
    style.configure("StatusBar.TLabel", background=COLORS["bg_card"], foreground=COLORS["text_primary"])
    style.configure("Heading.TLabel", font=FONTS["heading"], foreground=COLORS["text_primary"])
    style.configure("Value.TLabel", font=FONTS["value"], foreground=COLORS["primary"])
    style.configure("Unit.TLabel", font=("Microsoft YaHei", 12), foreground=COLORS["text_secondary"])
    style.configure("Hint.TLabel", font=FONTS["small"], foreground=COLORS["text_secondary"])
    style.configure("Success.TLabel", foreground=COLORS["success"], font=("Microsoft YaHei", 10, "bold"))
    style.configure("Error.TLabel", foreground=COLORS["error"], font=("Microsoft YaHei", 10, "bold"))
    style.configure("Section.TLabel", font=("Microsoft YaHei", 12, "bold"), foreground=COLORS["primary"])

    # === 按钮 ===
    style.configure("TButton",
                    background=COLORS["primary"],
                    foreground="white",
                    borderwidth=0,
                    font=("Microsoft YaHei", 10, "bold"),
                    padding=(16, 6))
    style.map("TButton",
              background=[("active", COLORS["primary_hover"]),
                          ("disabled", "#B0C4DE")],
              foreground=[("disabled", "#E8E8E8")])

    style.configure("Secondary.TButton",
                    background=COLORS["bg_card"],
                    foreground=COLORS["primary"],
                    borderwidth=1,
                    font=("Microsoft YaHei", 10),
                    padding=(16, 6))
    style.map("Secondary.TButton",
              background=[("active", COLORS["bg_main"])])

    style.configure("Success.TButton",
                    background=COLORS["success"],
                    foreground="white",
                    font=("Microsoft YaHei", 10, "bold"),
                    padding=(16, 6))

    # === 进度条 ===
    style.configure("TProgressbar",
                    background=COLORS["primary"],
                    troughcolor=COLORS["progress_bg"],
                    borderwidth=0,
                    thickness=16)

    # === 单选按钮 ===
    style.configure("TRadiobutton",
                    background=COLORS["bg_card"],
                    foreground=COLORS["text_primary"],
                    font=("Microsoft YaHei", 10))

    # === 输入框 ===
    style.configure("TEntry",
                    fieldbackground=COLORS["input_bg"],
                    borderwidth=1,
                    padding=4)

    # === 标签框架 ===
    style.configure("TLabelframe",
                    background=COLORS["bg_card"],
                    bordercolor=COLORS["border"],
                    relief="solid")
    style.configure("TLabelframe.Label",
                    background=COLORS["bg_card"],
                    foreground=COLORS["primary"],
                    font=("Microsoft YaHei", 11, "bold"))

    # === 分隔线 ===
    style.configure("TSeparator", background=COLORS["border"])

    return style
