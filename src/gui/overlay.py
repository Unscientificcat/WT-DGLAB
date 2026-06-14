"""悬浮窗模块 — 透明置顶窗口，显示实时游戏数据

左键拖动移动，右键菜单切换大小。
"""

import tkinter as tk
from tkinter import Menu

# 大小预设
SIZES = {
    "大": {"value": 36, "channel": 18, "mode": 14},
    "中": {"value": 24, "channel": 14, "mode": 11},
    "小": {"value": 16, "channel": 11, "mode": 9},
}


class OverlayWindow:
    """悬浮窗 — 透明背景，始终置顶"""

    def __init__(self):
        self._size = "中"
        self._visible = False
        # 逐字段缓存，避免未变化的标签被重复 config() 导致闪烁
        self._cache_mode = ""
        self._cache_value = ""
        self._cache_unit = ""
        self._cache_cha = ""
        self._cache_chb = ""
        self._cache_event = ""

        self.win = tk.Toplevel()
        self.win.overrideredirect(True)
        self.win.wm_attributes("-topmost", True)
        self.win.wm_attributes("-transparentcolor", "#010101")  # 独特色，不与文字边缘重合
        self.win.configure(bg="#010101")
        self.win.withdraw()

        # === 内容框架 ===
        frame = tk.Frame(self.win, bg="#010101")
        frame.pack(padx=8, pady=4)

        self.mode_label = tk.Label(
            frame, text="空战", fg="#4A90D9", bg="#010101",
            font=("Microsoft YaHei", 11, "bold"))
        self.mode_label.pack(anchor=tk.W)

        self.value_label = tk.Label(
            frame, text="--.-", fg="white", bg="#010101",
            font=("Microsoft YaHei", 24, "bold"))
        self.value_label.pack(anchor=tk.W)

        self.unit_label = tk.Label(
            frame, text="G", fg="#AAAAAA", bg="#010101",
            font=("Microsoft YaHei", 12))
        self.unit_label.pack(anchor=tk.W)

        tk.Frame(frame, bg="#333333", height=1).pack(fill=tk.X, pady=2)

        self.ch_a_label = tk.Label(
            frame, text="A: 0", fg="#FF6666", bg="#010101",
            font=("Microsoft YaHei", 14, "bold"))
        self.ch_a_label.pack(anchor=tk.W)

        self.ch_b_label = tk.Label(
            frame, text="B: 0", fg="#66BBFF", bg="#010101",
            font=("Microsoft YaHei", 14, "bold"))
        self.ch_b_label.pack(anchor=tk.W)

        # === 事件标签 ===
        self.event_label = tk.Label(
            frame, text="", fg="#FFD700", bg="#010101",
            font=("Microsoft YaHei", 11, "bold"))
        self.event_label.pack(anchor=tk.W)

        # === 拖动绑定 ===
        self._drag_x = 0
        self._drag_y = 0
        frame.bind("<Button-1>", self._start_drag)
        frame.bind("<B1-Motion>", self._do_drag)
        # 所有标签也能拖动
        for child in [self.mode_label, self.value_label, self.unit_label,
                      self.ch_a_label, self.ch_b_label, self.event_label]:
            child.bind("<Button-1>", self._start_drag)
            child.bind("<B1-Motion>", self._do_drag)

        # === 右键菜单 ===
        self._menu = Menu(self.win, tearoff=0)
        self._menu.add_command(label="大", command=lambda: self.set_size("大"))
        self._menu.add_command(label="中", command=lambda: self.set_size("中"))
        self._menu.add_command(label="小", command=lambda: self.set_size("小"))
        frame.bind("<Button-3>", lambda e: self._menu.post(e.x_root, e.y_root))
        for child in [self.mode_label, self.value_label, self.unit_label,
                      self.ch_a_label, self.ch_b_label, self.event_label]:
            child.bind("<Button-3>",
                       lambda e: self._menu.post(e.x_root, e.y_root))

        # 默认位置
        self.win.geometry("+100+100")

    def show(self):
        """显示悬浮窗"""
        self._visible = True
        self._cache_mode = ""
        self._cache_value = ""
        self._cache_unit = ""
        self._cache_cha = ""
        self._cache_chb = ""
        self._cache_event = ""
        self.win.deiconify()

    def hide(self):
        """隐藏悬浮窗"""
        self._visible = False
        self.win.withdraw()

    @property
    def visible(self) -> bool:
        return self._visible

    def set_size(self, size: str):
        """切换大小"""
        if size not in SIZES:
            return
        self._size = size
        cfg = SIZES[size]
        self.value_label.config(font=("Microsoft YaHei", cfg["value"], "bold"))
        self.ch_a_label.config(font=("Microsoft YaHei", cfg["channel"], "bold"))
        self.ch_b_label.config(font=("Microsoft YaHei", cfg["channel"], "bold"))
        self.mode_label.config(font=("Microsoft YaHei", cfg["mode"], "bold"))
        self.unit_label.config(font=("Microsoft YaHei", cfg["mode"]))
        self.event_label.config(font=("Microsoft YaHei", cfg["mode"], "bold"))

    def get_size(self) -> str:
        return self._size

    def update(self, mode: str, value: str, unit: str,
               ch_a: int, ch_b: int, event_text: str = ""):
        """同步数据到悬浮窗 — 逐字段对比，只更新真正变化的部分"""
        if not self._visible:
            return

        mode_text = "空战" if mode == "aircraft" else "陆战"
        ch_a_text = f"A: {ch_a}"
        ch_b_text = f"B: {ch_b}"

        # 每个字段独立对比缓存，只更新变了的部分
        if mode_text != self._cache_mode:
            self._cache_mode = mode_text
            self.mode_label.config(text=mode_text)
        if value != self._cache_value:
            self._cache_value = value
            self.value_label.config(text=value)
        if unit != self._cache_unit:
            self._cache_unit = unit
            self.unit_label.config(text=unit)
        if ch_a_text != self._cache_cha:
            self._cache_cha = ch_a_text
            self.ch_a_label.config(text=ch_a_text)
        if ch_b_text != self._cache_chb:
            self._cache_chb = ch_b_text
            self.ch_b_label.config(text=ch_b_text)
        if event_text != self._cache_event:
            self._cache_event = event_text
            self.event_label.config(text=event_text)

    def destroy(self):
        self.win.destroy()

    def _start_drag(self, event):
        self._drag_x = event.x_root - self.win.winfo_x()
        self._drag_y = event.y_root - self.win.winfo_y()

    def _do_drag(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.win.geometry(f"+{x}+{y}")
