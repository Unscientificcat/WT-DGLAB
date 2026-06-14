"""注意事项对话框 — 可滚动的 Toplevel 窗口，启动时和状态栏按钮共用"""

import os
import re
import sys
import tkinter as tk
from tkinter import ttk


def _get_project_root() -> str:
    """返回项目根目录，兼容 python 开发和 PyInstaller 打包"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    else:
        # 本文件位于 src/gui/，项目根是 ../../
        return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read_notice_text() -> str:
    """读取 注意事项.txt 全文"""
    path = os.path.join(_get_project_root(), "注意事项.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "注意事项 — 郊狼雷霆 v0.1\n\n"
            "本软件通过郊狼 3.0 设备输出电击脉冲，\n"
            "可能对身体造成不适。请务必阅读程序目录下的《注意事项.txt》\n"
        )


def _insert_with_emphasis(text_widget: tk.Text, content: str):
    """插入文本并高亮 **关键字**：去掉星号，关键字改为红色加粗"""
    # 配置高亮标签
    text_widget.tag_configure("em", foreground="#E74C3C", font=("Microsoft YaHei", 10, "bold"))

    segments = re.split(r"(\*\*.*?\*\*)", content)

    for seg in segments:
        if seg.startswith("**") and seg.endswith("**"):
            keyword = seg[2:-2]  # 去掉首尾 **
            text_widget.insert(tk.END, keyword, "em")
        else:
            text_widget.insert(tk.END, seg)


def show_disclaimer_dialog(parent) -> bool:
    """显示可滚动的注意事项对话框。

    每次启动时调用，用户必须点击"确认"才能继续。
    返回 True 表示确认，False 表示关闭窗口（退出程序）。
    """
    content = _read_notice_text()

    # === 创建 Toplevel ===
    dialog = tk.Toplevel(parent)
    dialog.title("注意事项 — 郊狼雷霆 v0.1")
    dialog.geometry("600x500")
    dialog.minsize(400, 350)
    dialog.resizable(True, True)
    dialog.configure(bg="#FFFFFF")

    # 居中于父窗口
    dialog.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    dw, dh = 600, 500
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    dialog.geometry(f"{dw}x{dh}+{x}+{y}")

    # 模态
    dialog.transient(parent)
    dialog.grab_set()
    dialog.focus_force()

    result = [False]

    def on_confirm():
        result[0] = True
        dialog.destroy()

    def on_close():
        result[0] = False
        dialog.destroy()

    # ═══════════════════════════════════════════
    # 从底部开始 pack：底部 → 中部 → 顶部
    # 这样底部按钮区域先占位，text_frame 只填充剩余空间
    # ═══════════════════════════════════════════

    # === 底部按钮区域（side=BOTTOM 先占位） ===
    bottom = tk.Frame(dialog, bg="#F0F6FC")
    bottom.pack(side=tk.BOTTOM, fill=tk.X)

    tk.Frame(dialog, bg="#D6E4F0", height=1).pack(side=tk.BOTTOM, fill=tk.X, padx=24, pady=(0, 4))

    hint = tk.Label(
        bottom,
        text="请仔细阅读以上内容。点击下方按钮表示您已阅读并理解。",
        font=("Microsoft YaHei", 9),
        fg="#7F8C8D",
        bg="#F0F6FC",
    )
    hint.pack(padx=24, pady=(8, 8))

    btn = ttk.Button(
        bottom,
        text="我 已 阅 读 并 确 认",
        command=on_confirm,
        style="Success.TButton",
    )
    btn.pack(fill=tk.X, padx=24, pady=(0, 12))
    btn.focus_set()

    # === 可滚动文本区域（填充剩余空间） ===
    text_frame = tk.Frame(dialog, bg="#FFFFFF")
    text_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=(0, 0))

    text_widget = tk.Text(
        text_frame,
        wrap=tk.WORD,
        font=("Microsoft YaHei", 10),
        fg="#2C3E50",
        bg="#F7FAFD",
        borderwidth=0,
        padx=12,
        pady=8,
        state=tk.NORMAL,
    )
    scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # 插入内容（**关键字** 自动高亮）
    _insert_with_emphasis(text_widget, content)
    text_widget.configure(state=tk.DISABLED)  # 只读

    # === 顶部分隔线 + 标题 ===
    tk.Frame(dialog, bg="#D6E4F0", height=1).pack(side=tk.TOP, fill=tk.X, padx=24, pady=(8, 0))

    header = tk.Label(
        dialog,
        text="注意事项 — 郊狼雷霆 v0.1",
        font=("Microsoft YaHei", 14, "bold"),
        fg="#4A90D9",
        bg="#FFFFFF",
    )
    header.pack(side=tk.TOP, pady=(16, 0))

    # 绑定 Enter 键确认
    dialog.bind("<Return>", lambda e: on_confirm())
    # 关闭窗口
    dialog.protocol("WM_DELETE_WINDOW", on_close)

    dialog.wait_window()
    return result[0]
