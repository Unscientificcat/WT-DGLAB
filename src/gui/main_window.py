"""主窗口 — 使用 tkinter 实现，包含状态栏、仪表盘、设置面板、QR 码区域"""

import tkinter as tk
from tkinter import ttk
from .styles import setup_styles, COLORS, FONTS
from .disclaimer_dialog import show_disclaimer_dialog
from ..config_manager import ConfigManager


class StatusBar(ttk.Frame):
    """顶部状态栏 — 显示战争雷霆和郊狼连接状态"""

    def __init__(self, parent):
        super().__init__(parent, style="StatusBar.TFrame")
        self._build()

    def _build(self):
        # WT 状态指示灯 + 文字
        self.wt_dot = tk.Label(self, text="●", fg=COLORS["error"],
                               bg=COLORS["bg_card"], font=("Microsoft YaHei", 12))
        self.wt_dot.pack(side=tk.LEFT, padx=(16, 4))

        self.wt_label = tk.Label(self, text="WT: 未连接", fg=COLORS["text_primary"],
                                 bg=COLORS["bg_card"], font=FONTS["small"])
        self.wt_label.pack(side=tk.LEFT, padx=(0, 20))

        # 分隔
        ttk.Separator(self, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # 郊狼状态
        self.dg_dot = tk.Label(self, text="●", fg=COLORS["error"],
                               bg=COLORS["bg_card"], font=("Microsoft YaHei", 12))
        self.dg_dot.pack(side=tk.LEFT, padx=(8, 4))

        self.dg_label = tk.Label(self, text="郊狼: 未连接", fg=COLORS["text_primary"],
                                 bg=COLORS["bg_card"], font=FONTS["small"])
        self.dg_label.pack(side=tk.LEFT, padx=(0, 20))

        # 地址信息（填充剩余空间）
        self.addr_label = tk.Label(self, text="", fg=COLORS["text_secondary"],
                                   bg=COLORS["bg_card"], font=FONTS["small"])
        self.addr_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 注意事项按钮
        self.disclaimer_btn = tk.Label(self, text="注意事项", fg=COLORS["accent"],
                                       bg=COLORS["bg_card"], font=FONTS["small"],
                                       cursor="hand2")
        self.disclaimer_btn.pack(side=tk.RIGHT, padx=(0, 16))
        self.disclaimer_btn.bind("<Button-1>", self._show_disclaimer)

    def set_wt_status(self, connected: bool):
        color = COLORS["success"] if connected else COLORS["error"]
        text = "WT: 已连接" if connected else "WT: 未连接"
        self.wt_dot.config(fg=color)
        self.wt_label.config(text=text)

    def set_coyote_status(self, connected: bool, address: str = ""):
        color = COLORS["success"] if connected else COLORS["error"]
        text = "郊狼: 已连接" if connected else "郊狼: 未连接"
        self.dg_dot.config(fg=color)
        self.dg_label.config(text=text)
        self.addr_label.config(text=address)

    def _show_disclaimer(self, event=None):
        """点击显示完整注意事项"""
        show_disclaimer_dialog(self.winfo_toplevel())


class Dashboard(ttk.LabelFrame):
    """实时数据面板 — 显示当前过载/损伤数值、电击强度"""

    def __init__(self, parent):
        super().__init__(parent, text="实时数据")
        self._build()

    def _build(self):
        inner = ttk.Frame(self, style="Card.TFrame")
        inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        # 当前游戏数值（大字）
        self.value_label = tk.Label(inner, text="--.-", font=FONTS["value"],
                                    fg=COLORS["primary"], bg=COLORS["bg_card"])
        self.value_label.pack()

        # 单位
        self.unit_label = tk.Label(inner, text="G", font=FONTS["unit"],
                                   fg=COLORS["text_secondary"], bg=COLORS["bg_card"])
        self.unit_label.pack(pady=(0, 24))

        # A 通道（大字突出）
        self.ch_a_label = tk.Label(inner, text="A通道: 0",
                                   fg=COLORS["text_primary"], bg=COLORS["bg_card"],
                                   font=("Microsoft YaHei", 18, "bold"))
        self.ch_a_label.pack(pady=4)

        # B 通道（大字突出）
        self.ch_b_label = tk.Label(inner, text="B通道: 0",
                                   fg=COLORS["text_primary"], bg=COLORS["bg_card"],
                                   font=("Microsoft YaHei", 18, "bold"))
        self.ch_b_label.pack(pady=4)

        # 事件提示
        self.event_label = tk.Label(inner, text="",
                                    fg=COLORS["accent"], bg=COLORS["bg_card"],
                                    font=("Microsoft YaHei", 11, "bold"))
        self.event_label.pack(pady=(12, 0))

        # 悬浮窗开关
        self._overlay_var = tk.BooleanVar(value=False)
        overlay_row = ttk.Frame(inner, style="Card.TFrame")
        overlay_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Checkbutton(overlay_row, text="悬浮窗", variable=self._overlay_var).pack(
            side=tk.LEFT)
        self._overlay_size_var = tk.StringVar(value="中")
        size_row = ttk.Frame(inner, style="Card.TFrame")
        size_row.pack(fill=tk.X, pady=(2, 0))
        tk.Label(size_row, text="  大小:", fg=COLORS["text_secondary"],
                 bg=COLORS["bg_card"], font=FONTS["small"]).pack(side=tk.LEFT)
        for s in ["大", "中", "小"]:
            ttk.Radiobutton(size_row, text=s, variable=self._overlay_size_var,
                            value=s).pack(side=tk.LEFT, padx=2)

    def update_aircraft(self, gforce: float, intensity_a: int, intensity_b: int):
        self.value_label.config(text=f"{gforce:.1f}")
        self.unit_label.config(text="G")
        self.ch_a_label.config(text=f"A通道: {intensity_a}")
        self.ch_b_label.config(text=f"B通道: {intensity_b}")

    def update_tank(self, speed: float, intensity_a: int, intensity_b: int):
        self.value_label.config(text=f"{speed:.0f}")
        self.unit_label.config(text="km/h")
        self.ch_a_label.config(text=f"A通道: {intensity_a}")
        self.ch_b_label.config(text=f"B通道: {intensity_b}")

    def show_event(self, text: str):
        """显示事件提示"""
        self.event_label.config(text=text)

    @property
    def overlay_var(self):
        return self._overlay_var

    def clear(self, mode: str = "aircraft"):
        if mode == "tank":
            self.value_label.config(text="--")
            self.unit_label.config(text="km/h")
        else:
            self.value_label.config(text="--.-")
            self.unit_label.config(text="G")
        self.ch_a_label.config(text="A通道: 0")
        self.ch_b_label.config(text="B通道: 0")
        self.event_label.config(text="")


class SettingsPanel(ttk.LabelFrame):
    """设置面板 — 所有用户可调参数"""

    def __init__(self, parent, config_mgr: ConfigManager, on_save=None,
                 on_mode_changed=None, overlay_var=None):
        super().__init__(parent, text="参数设置")
        self._config_mgr = config_mgr
        self._on_save_callback = on_save
        self._on_mode_changed_callback = on_mode_changed
        self._overlay_var = overlay_var

        # tkinter 变量
        self._mode_var = tk.StringVar(value="aircraft")

        self._ac_enabled = tk.BooleanVar(value=True)
        self._gforce_min = tk.DoubleVar(value=1.0)
        self._gforce_max = tk.DoubleVar(value=10.0)
        self._ac_ch_a = tk.IntVar(value=0)
        self._ac_ch_b = tk.IntVar(value=0)

        self._tk_enabled = tk.BooleanVar(value=True)
        self._speed_min = tk.DoubleVar(value=0.0)
        self._speed_max = tk.DoubleVar(value=60.0)
        self._tk_ch_a = tk.IntVar(value=0)
        self._tk_ch_b = tk.IntVar(value=0)

        self._cas_gforce_min = tk.DoubleVar(value=1.0)
        self._cas_gforce_max = tk.DoubleVar(value=10.0)
        self._cas_ch_a = tk.IntVar(value=0)
        self._cas_ch_b = tk.IntVar(value=0)

        # 空战波形
        # 陆战波形
        self._tk_wf_a = tk.StringVar(value="恒定")
        self._tk_wf_b = tk.StringVar(value="恒定")
        self._tk_wf_interval = tk.IntVar(value=30)
        # CAS波形
        self._cas_wf_a = tk.StringVar(value="恒定")
        self._cas_wf_b = tk.StringVar(value="恒定")
        self._cas_wf_interval = tk.IntVar(value=30)

        # 陆战事件变量
        self._tk_ev_name = tk.StringVar(value="")
        self._tk_ev_kill_on = tk.BooleanVar(value=False)
        self._tk_ev_kill_a = tk.IntVar(value=0)
        self._tk_ev_kill_b = tk.IntVar(value=0)
        self._tk_ev_kill_dur = tk.DoubleVar(value=5.0)
        self._tk_ev_kill_wf_a = tk.StringVar(value="恒定")
        self._tk_ev_kill_wf_b = tk.StringVar(value="恒定")
        self._tk_ev_death_on = tk.BooleanVar(value=False)
        self._tk_ev_death_a = tk.IntVar(value=0)
        self._tk_ev_death_b = tk.IntVar(value=0)
        self._tk_ev_death_dur = tk.DoubleVar(value=5.0)
        self._tk_ev_death_wf_a = tk.StringVar(value="恒定")
        self._tk_ev_death_wf_b = tk.StringVar(value="恒定")
        self._tk_ev_repair_on = tk.BooleanVar(value=False)
        self._tk_ev_repair_a = tk.IntVar(value=0)
        self._tk_ev_repair_b = tk.IntVar(value=0)
        self._tk_ev_repair_wf_a = tk.StringVar(value="恒定")
        self._tk_ev_repair_wf_b = tk.StringVar(value="恒定")

        self._ws_port = tk.IntVar(value=8765)
        self._refresh_ms = tk.IntVar(value=200)

        self._build()
        self._load_config()

    @property
    def is_aircraft_mode(self) -> bool:
        return self._mode_var.get() == "aircraft"

    def get_mode(self) -> str:
        return self._mode_var.get()

    def _build(self):
        # === 可滚动区域 ===
        canvas = tk.Canvas(self, bg=COLORS["bg_card"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)

        inner = ttk.Frame(canvas, style="Card.TFrame")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        self._canvas_win = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        # inner 宽度跟随 canvas
        def _on_canvas_resize(event):
            canvas.itemconfig(self._canvas_win, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        # 鼠标滚轮
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120) * 3), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # === 模式选择 ===
        mode_frame = ttk.Frame(inner, style="Card.TFrame")
        mode_frame.pack(fill=tk.X, pady=(0, 12), padx=12)

        tk.Label(mode_frame, text="模式选择", font=FONTS["heading"],
                 fg=COLORS["text_primary"], bg=COLORS["bg_card"]).pack(anchor=tk.W)

        radio_frame = ttk.Frame(mode_frame, style="Card.TFrame")
        radio_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Radiobutton(radio_frame, text="🛩 空战", variable=self._mode_var,
                        value="aircraft").pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(radio_frame, text="🚧 陆战", variable=self._mode_var,
                        value="tank").pack(side=tk.LEFT)

        # === 空战设置 ===
        from ..waveforms import ALL_WAVEFORMS
        WF_OPTIONS = ALL_WAVEFORMS + ["随机"]

        # 事件变量（UI 前初始化）
        self._ev_name_var = tk.StringVar(value="")
        self._ev_kill_on_var = tk.BooleanVar(value=False)
        self._ev_kill_a_var = tk.IntVar(value=0)
        self._ev_kill_b_var = tk.IntVar(value=0)
        self._ev_kill_dur_var = tk.DoubleVar(value=5.0)
        self._ev_kill_wf_a_var = tk.StringVar(value="恒定")
        self._ev_kill_wf_b_var = tk.StringVar(value="恒定")
        self._ev_death_on_var = tk.BooleanVar(value=False)
        self._ev_death_a_var = tk.IntVar(value=0)
        self._ev_death_b_var = tk.IntVar(value=0)
        self._ev_death_dur_var = tk.DoubleVar(value=5.0)
        self._ev_death_wf_a_var = tk.StringVar(value="恒定")
        self._ev_death_wf_b_var = tk.StringVar(value="恒定")

        self.aircraft_frame = ttk.LabelFrame(inner, text="空战设置")
        self.aircraft_frame.pack(fill=tk.X, pady=(0, 8))
        self._make_check_row(self.aircraft_frame, "启用过载电击", self._ac_enabled, 0)
        self._make_double_row(self.aircraft_frame, "过载下限:", self._gforce_min, 0, 20, 0.5, " G", 1)
        self._make_double_row(self.aircraft_frame, "过载上限:", self._gforce_max, 0, 20, 0.5, " G", 1)
        self._make_int_row(self.aircraft_frame, "A通道最大强度:", self._ac_ch_a, 0, 200, 2)
        self._make_int_row(self.aircraft_frame, "B通道最大强度:", self._ac_ch_b, 0, 200, 3)
        # 事件子组（可折叠）
        self._ev_toggle_btn = ttk.Button(self.aircraft_frame, text="▶ 事件设置",
                                         command=lambda: self._toggle_ev(),
                                         style="Secondary.TButton")
        self._ev_toggle_btn.pack(fill=tk.X, padx=12, pady=(8, 0))
        self._ev_content = ttk.Frame(self.aircraft_frame, style="Card.TFrame")
        self._make_entry_row(self._ev_content, "游戏昵称:", self._ev_name_var, 0)
        self._make_check_row(self._ev_content, "击杀提醒", self._ev_kill_on_var, 1)
        self._make_int_row(self._ev_content, "  A通道:", self._ev_kill_a_var, 0, 200, 2)
        self._make_int_row(self._ev_content, "  B通道:", self._ev_kill_b_var, 0, 200, 3)
        self._make_combo_row(self._ev_content, "  A波形:", self._ev_kill_wf_a_var, ALL_WAVEFORMS, 4)
        self._make_combo_row(self._ev_content, "  B波形:", self._ev_kill_wf_b_var, ALL_WAVEFORMS, 5)
        self._make_double_row(self._ev_content, "  持续:", self._ev_kill_dur_var, 0.1, 30, 0.5, " 秒", 6)
        self._make_check_row(self._ev_content, "被击落/坠毁惩罚", self._ev_death_on_var, 7)
        self._make_int_row(self._ev_content, "  A通道:", self._ev_death_a_var, 0, 200, 8)
        self._make_int_row(self._ev_content, "  B通道:", self._ev_death_b_var, 0, 200, 9)
        self._make_combo_row(self._ev_content, "  A波形:", self._ev_death_wf_a_var, ALL_WAVEFORMS, 10)
        self._make_combo_row(self._ev_content, "  B波形:", self._ev_death_wf_b_var, ALL_WAVEFORMS, 11)
        self._make_double_row(self._ev_content, "  持续:", self._ev_death_dur_var, 0.1, 30, 0.5, " 秒", 12)
        # === 陆战设置 ===
        self.tank_frame = ttk.LabelFrame(inner, text="陆战设置")
        self.tank_frame.pack(fill=tk.X, pady=(0, 8))
        self._make_check_row(self.tank_frame, "启用速度电击", self._tk_enabled, 0)
        self._make_double_row(self.tank_frame, "速度下限:", self._speed_min, 0, 200, 1, " km/h", 1)
        self._make_double_row(self.tank_frame, "速度上限:", self._speed_max, 0, 200, 1, " km/h", 1)
        self._make_int_row(self.tank_frame, "A通道最大强度:", self._tk_ch_a, 0, 200, 2)
        self._make_int_row(self.tank_frame, "B通道最大强度:", self._tk_ch_b, 0, 200, 3)
        self._make_combo_row(self.tank_frame, "A通道波形:", self._tk_wf_a, WF_OPTIONS, 4)
        self._make_combo_row(self.tank_frame, "B通道波形:", self._tk_wf_b, WF_OPTIONS, 5)
        self._make_int_row(self.tank_frame, "随机间隔:", self._tk_wf_interval, 5, 300, 6, " 秒")
        # 陆战事件子组（可折叠）
        self._tk_ev_toggle_btn = ttk.Button(self.tank_frame, text="▶ 事件设置",
                                            command=lambda: self._toggle_tk_ev(),
                                            style="Secondary.TButton")
        self._tk_ev_toggle_btn.pack(fill=tk.X, padx=12, pady=(8, 0))
        self._tk_ev_content = ttk.Frame(self.tank_frame, style="Card.TFrame")
        self._make_entry_row(self._tk_ev_content, "游戏昵称:", self._tk_ev_name, 0)
        self._make_check_row(self._tk_ev_content, "击杀提醒", self._tk_ev_kill_on, 1)
        self._make_int_row(self._tk_ev_content, "  A通道:", self._tk_ev_kill_a, 0, 200, 2)
        self._make_int_row(self._tk_ev_content, "  B通道:", self._tk_ev_kill_b, 0, 200, 3)
        self._make_combo_row(self._tk_ev_content, "  A波形:", self._tk_ev_kill_wf_a, ALL_WAVEFORMS, 4)
        self._make_combo_row(self._tk_ev_content, "  B波形:", self._tk_ev_kill_wf_b, ALL_WAVEFORMS, 5)
        self._make_double_row(self._tk_ev_content, "  持续:", self._tk_ev_kill_dur, 0.1, 30, 0.5, " 秒", 6)
        self._make_check_row(self._tk_ev_content, "被击毁惩罚", self._tk_ev_death_on, 7)
        self._make_int_row(self._tk_ev_content, "  A通道:", self._tk_ev_death_a, 0, 200, 8)
        self._make_int_row(self._tk_ev_content, "  B通道:", self._tk_ev_death_b, 0, 200, 9)
        self._make_combo_row(self._tk_ev_content, "  A波形:", self._tk_ev_death_wf_a, ALL_WAVEFORMS, 10)
        self._make_combo_row(self._tk_ev_content, "  B波形:", self._tk_ev_death_wf_b, ALL_WAVEFORMS, 11)
        self._make_double_row(self._tk_ev_content, "  持续:", self._tk_ev_death_dur, 0.1, 30, 0.5, " 秒", 12)
        self._make_check_row(self._tk_ev_content, "维修惩罚", self._tk_ev_repair_on, 13)
        self._make_int_row(self._tk_ev_content, "  A通道:", self._tk_ev_repair_a, 0, 200, 14)
        self._make_int_row(self._tk_ev_content, "  B通道:", self._tk_ev_repair_b, 0, 200, 15)
        self._make_combo_row(self._tk_ev_content, "  A波形:", self._tk_ev_repair_wf_a, ALL_WAVEFORMS, 16)
        self._make_combo_row(self._tk_ev_content, "  B波形:", self._tk_ev_repair_wf_b, ALL_WAVEFORMS, 17)

        # === CAS设置（陆战空中支援） ===
        self.cas_frame = ttk.LabelFrame(inner, text="CAS设置（陆战上飞机时）")
        self.cas_frame.pack(fill=tk.X, pady=(0, 8))
        self._make_double_row(self.cas_frame, "过载下限:", self._cas_gforce_min, 0, 20, 0.5, " G", 0)
        self._make_double_row(self.cas_frame, "过载上限:", self._cas_gforce_max, 0, 20, 0.5, " G", 1)
        self._make_int_row(self.cas_frame, "A通道最大强度:", self._cas_ch_a, 0, 200, 2)
        self._make_int_row(self.cas_frame, "B通道最大强度:", self._cas_ch_b, 0, 200, 3)
        self._make_combo_row(self.cas_frame, "A通道波形:", self._cas_wf_a, WF_OPTIONS, 4)
        self._make_combo_row(self.cas_frame, "B通道波形:", self._cas_wf_b, WF_OPTIONS, 5)
        self._make_int_row(self.cas_frame, "随机间隔:", self._cas_wf_interval, 5, 300, 6, " 秒")

        # === 连接设置 ===
        conn_frame = ttk.LabelFrame(inner, text="连接设置")
        conn_frame.pack(fill=tk.X, pady=(0, 8))
        self._make_int_row(conn_frame, "WebSocket 端口:", self._ws_port, 1024, 65535, 0)
        self._make_int_row(conn_frame, "刷新间隔:", self._refresh_ms, 50, 1000, 1, " ms")

        # === 按钮 ===
        btn_frame = ttk.Frame(inner, style="Card.TFrame")
        btn_frame.pack(fill=tk.X)

        self.save_btn = ttk.Button(btn_frame, text="保存设置",
                                   command=self._on_save, style="TButton")
        self.save_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.reset_btn = ttk.Button(btn_frame, text="恢复默认",
                                    command=self._on_reset, style="Secondary.TButton")
        self.reset_btn.pack(side=tk.LEFT)

        # 保存反馈标签
        self.save_feedback = tk.Label(btn_frame, text="",
                                      fg=COLORS["success"], bg=COLORS["bg_card"],
                                      font=("Microsoft YaHei", 9, "bold"))
        self.save_feedback.pack(side=tk.LEFT, padx=12)

        # 模式切换时显示/隐藏设置组
        self._mode_var.trace_add("write", lambda *a: self._on_mode_changed())

    def _make_int_row(self, parent, label, var, min_v, max_v, row, suffix="",
                      return_row=False):
        """创建 标签 + 数字输入 + 单位 的行"""
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, padx=12, pady=3)

        tk.Label(row_frame, text=label, fg=COLORS["text_primary"],
                 bg=COLORS["bg_card"], font=FONTS["default"]).pack(side=tk.LEFT)

        spin = ttk.Spinbox(row_frame, from_=min_v, to=max_v,
                           textvariable=var, width=8,
                           font=FONTS["default"])
        spin.bind("<MouseWheel>", lambda e: "break")
        spin.pack(side=tk.LEFT, padx=(8, 4))

        if suffix:
            tk.Label(row_frame, text=suffix, fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"], font=FONTS["small"]).pack(side=tk.LEFT)

        if return_row:
            return row_frame

    def _make_combo_row(self, parent, label, var, values, row):
        """创建 标签 + 下拉框 的行"""
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row_frame, text=label, fg=COLORS["text_primary"],
                 bg=COLORS["bg_card"], font=FONTS["default"]).pack(side=tk.LEFT)
        combo = ttk.Combobox(row_frame, textvariable=var, values=values,
                             state="readonly", width=10, font=FONTS["default"])
        combo.bind("<MouseWheel>", lambda e: "break")
        combo.pack(side=tk.LEFT, padx=(8, 4))

    def _make_entry_row(self, parent, label, var, row):
        """创建 标签 + 文本输入框 的行"""
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row_frame, text=label, fg=COLORS["text_primary"],
                 bg=COLORS["bg_card"], font=FONTS["default"]).pack(side=tk.LEFT)
        entry = ttk.Entry(row_frame, textvariable=var, width=15,
                          font=FONTS["default"])
        entry.pack(side=tk.LEFT, padx=(8, 4))

    def _make_check_row(self, parent, label, var, row):
        """创建 勾选框 的行"""
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, padx=12, pady=3)
        ttk.Checkbutton(row_frame, text=label, variable=var).pack(side=tk.LEFT)

    def _make_double_row(self, parent, label, var, min_v, max_v, step, suffix, row):
        """创建 标签 + 浮点数输入 + 单位 的行"""
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, padx=12, pady=3)

        tk.Label(row_frame, text=label, fg=COLORS["text_primary"],
                 bg=COLORS["bg_card"], font=FONTS["default"]).pack(side=tk.LEFT)

        spin = ttk.Spinbox(row_frame, from_=min_v, to=max_v,
                           textvariable=var, width=8,
                           font=FONTS["default"],
                           increment=step)
        spin.pack(side=tk.LEFT, padx=(8, 4))

        if suffix:
            tk.Label(row_frame, text=suffix, fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"], font=FONTS["small"]).pack(side=tk.LEFT)

    def _toggle_ev(self):
        """折叠/展开空战事件设置"""
        if self._ev_content.winfo_ismapped():
            self._ev_content.pack_forget()
            self._ev_toggle_btn.config(text="▶ 事件设置")
        else:
            self._ev_content.pack(fill=tk.X, padx=12, pady=(0, 3))
            self._ev_toggle_btn.config(text="▼ 事件设置")

    def _toggle_tk_ev(self):
        """折叠/展开陆战事件设置"""
        if self._tk_ev_content.winfo_ismapped():
            self._tk_ev_content.pack_forget()
            self._tk_ev_toggle_btn.config(text="▶ 事件设置")
        else:
            self._tk_ev_content.pack(fill=tk.X, padx=12, pady=(0, 3))
            self._tk_ev_toggle_btn.config(text="▼ 事件设置")

    def _on_mode_changed(self):
        """切换空战/陆战设置组的显示"""
        # 先全部隐藏
        self.aircraft_frame.pack_forget()
        self.tank_frame.pack_forget()
        self.cas_frame.pack_forget()

        is_air = self._mode_var.get() == "aircraft"
        if is_air:
            self.aircraft_frame.pack(fill=tk.X, pady=(0, 8))
        else:
            self.tank_frame.pack(fill=tk.X, pady=(0, 8))
            self.cas_frame.pack(fill=tk.X, pady=(0, 8))

        # 通知外部（即时刷新仪表盘）
        if self._on_mode_changed_callback:
            self._on_mode_changed_callback()

    def _load_config(self):
        """从配置管理器加载到 UI"""
        cfg = self._config_mgr.config

        self._ac_enabled.set(cfg.aircraft.enabled)
        self._gforce_min.set(cfg.aircraft.gforce_min)
        self._gforce_max.set(cfg.aircraft.gforce_max)
        self._ac_ch_a.set(cfg.aircraft.channel_a_max)
        self._ac_ch_b.set(cfg.aircraft.channel_b_max)

        self._tk_enabled.set(cfg.tank.enabled)
        self._speed_min.set(cfg.tank.speed_min)
        self._speed_max.set(cfg.tank.speed_max)
        self._tk_ch_a.set(cfg.tank.channel_a_max)
        self._tk_ch_b.set(cfg.tank.channel_b_max)

        self._cas_gforce_min.set(cfg.cas.gforce_min)
        self._cas_gforce_max.set(cfg.cas.gforce_max)
        self._cas_ch_a.set(cfg.cas.channel_a_max)
        self._cas_ch_b.set(cfg.cas.channel_b_max)

        self._ws_port.set(cfg.app.ws_port)
        self._refresh_ms.set(cfg.app.refresh_interval_ms)
        self._mode_var.set(cfg.app.mode)

        self._tk_wf_a.set(cfg.tank.waveform_a)
        self._tk_wf_b.set(cfg.tank.waveform_b)
        self._tk_wf_interval.set(cfg.tank.random_interval)
        self._cas_wf_a.set(cfg.cas.waveform_a)
        self._cas_wf_b.set(cfg.cas.waveform_b)
        self._cas_wf_interval.set(cfg.cas.random_interval)

        self._ev_name_var.set(cfg.events.player_name)
        self._ev_kill_on_var.set(cfg.events.kill_enabled)
        self._ev_kill_a_var.set(cfg.events.kill_ch_a)
        self._ev_kill_b_var.set(cfg.events.kill_ch_b)
        self._ev_kill_dur_var.set(cfg.events.kill_duration)
        self._ev_kill_wf_a_var.set(cfg.events.kill_wf_a)
        self._ev_kill_wf_b_var.set(cfg.events.kill_wf_b)
        self._ev_death_on_var.set(cfg.events.death_enabled)
        self._ev_death_a_var.set(cfg.events.death_ch_a)
        self._ev_death_b_var.set(cfg.events.death_ch_b)
        self._ev_death_dur_var.set(cfg.events.death_duration)
        self._ev_death_wf_a_var.set(cfg.events.death_wf_a)
        self._ev_death_wf_b_var.set(cfg.events.death_wf_b)

        te = cfg.tank_events
        self._tk_ev_name.set(te.player_name)
        self._tk_ev_kill_on.set(te.kill_enabled)
        self._tk_ev_kill_a.set(te.kill_ch_a)
        self._tk_ev_kill_b.set(te.kill_ch_b)
        self._tk_ev_kill_dur.set(te.kill_duration)
        self._tk_ev_kill_wf_a.set(te.kill_wf_a)
        self._tk_ev_kill_wf_b.set(te.kill_wf_b)
        self._tk_ev_death_on.set(te.death_enabled)
        self._tk_ev_death_a.set(te.death_ch_a)
        self._tk_ev_death_b.set(te.death_ch_b)
        self._tk_ev_death_dur.set(te.death_duration)
        self._tk_ev_death_wf_a.set(te.death_wf_a)
        self._tk_ev_death_wf_b.set(te.death_wf_b)
        self._tk_ev_repair_on.set(te.repair_enabled)
        self._tk_ev_repair_a.set(te.repair_ch_a)
        self._tk_ev_repair_b.set(te.repair_ch_b)
        self._tk_ev_repair_wf_a.set(te.repair_wf_a)
        self._tk_ev_repair_wf_b.set(te.repair_wf_b)

        self._on_mode_changed()

    def _on_save(self):
        """保存设置"""
        cfg = self._config_mgr.config

        cfg.aircraft.enabled = self._ac_enabled.get()
        cfg.aircraft.gforce_min = self._gforce_min.get()
        cfg.aircraft.gforce_max = self._gforce_max.get()
        cfg.aircraft.channel_a_max = self._ac_ch_a.get()
        cfg.aircraft.channel_b_max = self._ac_ch_b.get()

        cfg.tank.enabled = self._tk_enabled.get()
        cfg.tank.speed_min = self._speed_min.get()
        cfg.tank.speed_max = self._speed_max.get()
        cfg.tank.channel_a_max = self._tk_ch_a.get()
        cfg.tank.channel_b_max = self._tk_ch_b.get()

        cfg.cas.gforce_min = self._cas_gforce_min.get()
        cfg.cas.gforce_max = self._cas_gforce_max.get()
        cfg.cas.channel_a_max = self._cas_ch_a.get()
        cfg.cas.channel_b_max = self._cas_ch_b.get()

        cfg.app.ws_port = self._ws_port.get()
        cfg.app.refresh_interval_ms = self._refresh_ms.get()
        cfg.app.mode = self._mode_var.get()
        cfg.app.overlay_enabled = self._overlay_var.get() if self._overlay_var else False
        cfg.app.overlay_size = "中"  # 由 Dashboard 控制，不在此保存
        cfg.tank.waveform_a = self._tk_wf_a.get()
        cfg.tank.waveform_b = self._tk_wf_b.get()
        cfg.tank.random_interval = self._tk_wf_interval.get()
        cfg.cas.waveform_a = self._cas_wf_a.get()
        cfg.cas.waveform_b = self._cas_wf_b.get()
        cfg.cas.random_interval = self._cas_wf_interval.get()

        cfg.events.player_name = self._ev_name_var.get()
        cfg.events.kill_enabled = self._ev_kill_on_var.get()
        cfg.events.kill_ch_a = self._ev_kill_a_var.get()
        cfg.events.kill_ch_b = self._ev_kill_b_var.get()
        cfg.events.kill_duration = self._ev_kill_dur_var.get()
        cfg.events.kill_wf_a = self._ev_kill_wf_a_var.get()
        cfg.events.kill_wf_b = self._ev_kill_wf_b_var.get()
        cfg.events.death_enabled = self._ev_death_on_var.get()
        cfg.events.death_ch_a = self._ev_death_a_var.get()
        cfg.events.death_ch_b = self._ev_death_b_var.get()
        cfg.events.death_duration = self._ev_death_dur_var.get()
        cfg.events.death_wf_a = self._ev_death_wf_a_var.get()
        cfg.events.death_wf_b = self._ev_death_wf_b_var.get()

        te = cfg.tank_events
        te.player_name = self._tk_ev_name.get()
        te.kill_enabled = self._tk_ev_kill_on.get()
        te.kill_ch_a = self._tk_ev_kill_a.get()
        te.kill_ch_b = self._tk_ev_kill_b.get()
        te.kill_duration = self._tk_ev_kill_dur.get()
        te.kill_wf_a = self._tk_ev_kill_wf_a.get()
        te.kill_wf_b = self._tk_ev_kill_wf_b.get()
        te.death_enabled = self._tk_ev_death_on.get()
        te.death_ch_a = self._tk_ev_death_a.get()
        te.death_ch_b = self._tk_ev_death_b.get()
        te.death_duration = self._tk_ev_death_dur.get()
        te.death_wf_a = self._tk_ev_death_wf_a.get()
        te.death_wf_b = self._tk_ev_death_wf_b.get()
        te.repair_enabled = self._tk_ev_repair_on.get()
        te.repair_ch_a = self._tk_ev_repair_a.get()
        te.repair_ch_b = self._tk_ev_repair_b.get()
        te.repair_wf_a = self._tk_ev_repair_wf_a.get()
        te.repair_wf_b = self._tk_ev_repair_wf_b.get()

        self._config_mgr.save()

        # 反馈
        self.save_feedback.config(text="✓ 已保存")
        self.after(2000, lambda: self.save_feedback.config(text=""))

        if self._on_save_callback:
            self._on_save_callback()

    def _on_reset(self):
        """恢复默认"""
        self._config_mgr.reset_defaults()
        self._load_config()
        self._config_mgr.save()
        self.save_feedback.config(text="✓ 已恢复默认")
        self.after(2000, lambda: self.save_feedback.config(text=""))


class QRWidget(ttk.LabelFrame):
    """QR 码区域 — 生成并显示连接二维码"""

    def __init__(self, parent):
        super().__init__(parent, text="设备连接")
        self._build()

    def _build(self):
        inner = ttk.Frame(self, style="Card.TFrame")
        inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # 左侧：QR 码占位
        self.qr_canvas = tk.Canvas(inner, width=120, height=120,
                                   bg="white", highlightthickness=2,
                                   highlightbackground=COLORS["border"])
        self.qr_canvas.pack(side=tk.LEFT, padx=(0, 16))
        self.qr_canvas.create_text(60, 60, text="等待\n启动...",
                                   fill=COLORS["text_secondary"],
                                   font=FONTS["small"])

        # 右侧：连接信息
        info_frame = ttk.Frame(inner, style="Card.TFrame")
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_text = tk.Label(info_frame, text="等待启动 WebSocket 服务...",
                                    fg=COLORS["text_primary"], bg=COLORS["bg_card"],
                                    font=FONTS["default"])
        self.status_text.pack(anchor=tk.W)

        self.url_label = tk.Label(info_frame, text="",
                                  fg=COLORS["primary"], bg=COLORS["bg_main"],
                                  font=("Consolas", 10, "bold"),
                                  padx=8, pady=4, anchor=tk.W)
        self.url_label.pack(anchor=tk.W, pady=4)

        hint = tk.Label(info_frame,
                        text="① 确保手机和电脑在同一局域网\n"
                             "② 打开 DG-LAB App → Socket被控 → 扫码连接\n"
                             "③ 连接成功后保持App在前台，勿锁屏\n"
                             "④ 断开后可点「刷新二维码」重新连接",
                        fg=COLORS["text_secondary"], bg=COLORS["bg_card"],
                        font=FONTS["small"], justify=tk.LEFT)
        hint.pack(anchor=tk.W, pady=(8, 0))

    def set_status(self, text: str, url: str = ""):
        self.status_text.config(text=text)
        if url:
            self.url_label.config(text=f"📡 {url}")
        else:
            self.url_label.config(text="")


class MainWindow:
    """主窗口控制器 — 组装所有面板"""

    def __init__(self, config_manager: ConfigManager, on_mode_changed=None):
        self._config_mgr = config_manager
        self._on_mode_changed = on_mode_changed

        self.root = tk.Tk()
        self.root.title("郊狼雷霆 v0.1")
        self.root.geometry("1000x700")
        self.root.minsize(940, 650)
        self.root.configure(bg=COLORS["bg_main"])

        # 设置 ttk 样式
        setup_styles()

        self._build()
        self._center_window()

    def _build(self):
        # === 顶部状态栏 ===
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, padx=8, pady=(8, 0))

        # === 分隔线 ===
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=4)

        # === 主体（左右两栏） ===
        body = ttk.Frame(self.root, style="Panel.TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 左侧：仪表盘
        self.dashboard = Dashboard(body)
        self.dashboard.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 6))
        # 确保宽度足够容纳三位数强度值
        self.dashboard.configure(width=180)
        self.dashboard.overlay_var.set(
            self._config_mgr.config.app.overlay_enabled)
        self.dashboard._overlay_size_var.set(
            self._config_mgr.config.app.overlay_size)

        # 右侧：设置面板
        self.settings_panel = SettingsPanel(body, self._config_mgr,
                                            on_save=self._on_settings_saved,
                                            on_mode_changed=self._on_mode_changed,
                                            overlay_var=self.dashboard.overlay_var)
        self.settings_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # === 底部 QR 码区域 ===
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=2)
        self.qr_widget = QRWidget(self.root)
        self.qr_widget.pack(fill=tk.X, padx=8, pady=(2, 8))

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def _on_settings_saved(self):
        """设置变更回调 — 通知 App 同步波形等配置"""
        if self._on_mode_changed:
            self._on_mode_changed()

    def get_mode(self) -> str:
        return self.settings_panel.get_mode()

    @property
    def overlay_enabled(self) -> bool:
        return self._overlay_var.get()

    @property
    def overlay_size(self) -> str:
        return self.dashboard._overlay_size_var.get()

    def get_config(self):
        return self._config_mgr.config

    def run(self):
        """启动主循环"""
        self.root.mainloop()

    def after(self, ms, callback):
        """定时器"""
        self.root.after(ms, callback)

    def quit(self):
        self.root.quit()
