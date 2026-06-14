"""郊狼雷霆 v0.1 — 战争雷霆 × 郊狼 3.0 电击联动

启动方式：
    python main.py

架构：
    战争雷霆 :8111 ──HTTP──► GameReader ──► MappingEngine ──► CoyoteController ──WS──► 手机App ──BLE──► 郊狼3.0
                                                        │
                                                    MainWindow (tkinter GUI)
"""

import sys
import os
import io
import logging
import threading
import queue

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qrcode
from PIL import Image, ImageTk

from src.config_manager import ConfigManager
from src.game_reader import GameReader, GameState
from src.coyote_controller import CoyoteController
from src.mapping_engine import MappingEngine
from src.gui.disclaimer_dialog import show_disclaimer_dialog
from src.gui.main_window import MainWindow
from src.gui.overlay import OverlayWindow
from src.gui.styles import COLORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("WT-DGLAB")


class App:
    """应用主控制器 — 后台线程读取游戏数据，主线程只负责更新 GUI"""

    def __init__(self):
        # ===== 配置 =====
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.json")
        self.config_mgr = ConfigManager(config_path)
        self.config_mgr.load()

        # ===== 状态缓存（必须在 GUI 之前初始化，因为 GUI 初始化会触发回调）=====
        self._last_state = GameState()
        self._coyote_started = False

        # 事件检测状态
        self._last_dmg_id = 0
        self._event_kind = ""       # "" / "kill" / "death"
        self._event_mode = ""       # "aircraft" / "tank"
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0  # 剩余秒数
        self._current_mode = self._cfg.app.mode
        self._repair_active = False
        self._wt_fail_count = 0
        self._wt_connected = False
        self._overlay_tick = 0                      # 悬浮窗节流计数
        self._overlay_last_value = ""               # 悬浮窗缓存：上次有效数值
        self._overlay_last_unit = ""                # 悬浮窗缓存：上次有效单位
        self._window_ready = False

        # ===== GUI =====
        self.window = MainWindow(self.config_mgr,
                                 on_mode_changed=self._on_mode_switched)
        self._window_ready = True

        # ===== 悬浮窗 =====
        self.overlay = OverlayWindow()
        if self._cfg.app.overlay_enabled:
            self.overlay.show()
            self.overlay.set_size(self._cfg.app.overlay_size)
            self.window.dashboard.overlay_var.set(True)
            self.window.dashboard._overlay_size_var.set(
                self._cfg.app.overlay_size)

        # ===== 游戏数据读取器 =====
        self.game_reader = GameReader()

        # ===== 郊狼控制器 =====
        self.coyote = CoyoteController(port=self._cfg.app.ws_port)

        # ===== 线程间通信 =====
        self._data_queue = queue.Queue(maxsize=2)  # 只保留最新游戏数据
        self._event_queue = queue.Queue(maxsize=2)  # 最新事件数据
        self._running = True

    @property
    def _cfg(self):
        """始终返回当前 Config 对象引用（防止 reset_defaults 后引用失效）"""
        return self.config_mgr.config

    # ============================================================
    # 生命周期
    # ============================================================

    def run(self):
        """启动应用"""
        # 每次启动显示注意事项
        if not self._show_disclaimer_dialog():
            return  # 用户关闭对话框则退出

        # 启动游戏数据后台线程
        self._poller_thread = threading.Thread(
            target=self._poller_loop, daemon=True
        )
        self._poller_thread.start()

        # 启动郊狼服务端（延迟到 GUI 就绪后）
        self.window.after(500, self._start_coyote)

        # 启动 UI 刷新定时器
        self._schedule_ui_refresh()

        # 窗口关闭时清理
        self.window.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 进入 tkinter 主循环
        self.window.run()

    def _on_close(self):
        """窗口关闭回调 — 立即关闭，不等待后台资源释放"""
        self._running = False
        self.overlay.destroy()
        self.window.root.destroy()

    def _show_disclaimer_dialog(self) -> bool:
        """每次启动显示注意事项对话框。返回 True 表示确认，False 表示关闭。"""
        confirmed = show_disclaimer_dialog(self.window.root)
        if not confirmed:
            self.window.root.destroy()
        return confirmed

    # ============================================================
    # 后台线程：轮询游戏数据（不阻塞 GUI）
    # ============================================================

    def _poller_loop(self):
        """后台线程 — 持续轮询 WT 数据和事件"""
        while self._running:
            try:
                state = self.game_reader.fetch()
            except Exception:
                state = GameState()

            # 游戏数据入队
            try:
                self._data_queue.put(state, block=False)
            except queue.Full:
                try:
                    self._data_queue.get_nowait()
                    self._data_queue.put(state, block=False)
                except queue.Empty:
                    pass

            # 事件检测（后台执行，不阻塞主线程）
            try:
                events = self._detect_events()
                if events:
                    logger.info(f"检测到事件: {events['kind']} mode={events.get('mode','')}")
                    try:
                        self._event_queue.put(events, block=False)
                    except queue.Full:
                        try:
                            self._event_queue.get_nowait()
                            self._event_queue.put(events, block=False)
                        except queue.Empty:
                            pass
            except Exception as e:
                logger.warning(f"事件检测异常: {e}", exc_info=True)

            # 等待下一次轮询
            self._running_event = threading.Event()
            self._running_event.wait(
                max(self._cfg.app.refresh_interval_ms / 1000.0, 0.05)
            )

    def _detect_events(self) -> dict:
        """后台线程中检测事件（不阻塞主线程）

        根据游戏内实际载具类型选择事件配置，而非 GUI 模式。
        这样陆战上飞机时用空战事件，在地面时用陆战事件。
        """
        # 优先用游戏实际载具类型，未知时回退到 GUI 模式
        vt = self._last_state.vehicle_type or self._current_mode
        if vt == "aircraft":
            ev_cfg = self._cfg.events
        elif vt == "tank":
            ev_cfg = self._cfg.tank_events
        else:
            return {}

        result = {}

        # 维修检测（不需要昵称，基于游戏状态）
        if vt == "tank" and ev_cfg.repair_enabled:
            tank = self._last_state.tank
            if tank and tank.is_repairing and not self._repair_active:
                self._repair_active = True
                result = {
                    "kind": "repair", "mode": vt,
                    "ch_a": ev_cfg.repair_ch_a, "ch_b": ev_cfg.repair_ch_b,
                    "duration": 60,
                    "wf_a": ev_cfg.repair_wf_a, "wf_b": ev_cfg.repair_wf_b,
                }

        # 击杀/死亡检测（需要昵称匹配 hudmsg）
        if ev_cfg.player_name:
            result = self._detect_kill_death(ev_cfg, vt) or result

        return result

    def _detect_kill_death(self, ev_cfg, mode: str) -> dict:
        """检测 hudmsg 击杀/死亡事件"""
        name = ev_cfg.player_name
        records = self.game_reader.fetch_hudmsg(self._last_dmg_id)
        if records:
            logger.debug(f"hudmsg: 获取 {len(records)} 条新记录, last_id={self._last_dmg_id}, name={name}")
        result = {}
        ZERO_WIDTH = set("​‌‍‎‏⁠﻿")
        for r in records:
            rid = int(r.get("id", 0))
            if rid > self._last_dmg_id:
                self._last_dmg_id = rid

            msg = r.get("msg", "")
            msg = "".join(c for c in msg if c not in ZERO_WIDTH)
            if name not in msg:
                continue

            is_kill = False
            for kw in ["击落了", "击毁了"]:
                if kw in msg and name in msg.split(kw, 1)[0]:
                    is_kill = True
                    break

            is_killed = False
            for kw in ["击落了", "击毁了"]:
                if kw in msg:
                    if name in msg.split(kw, 1)[1]:
                        is_killed = True
                        break
            if not is_killed and name in msg and "已坠毁" in msg:
                is_killed = True

            if is_kill and ev_cfg.kill_enabled:
                result = {
                    "kind": "kill", "mode": mode,
                    "ch_a": ev_cfg.kill_ch_a, "ch_b": ev_cfg.kill_ch_b,
                    "duration": ev_cfg.kill_duration,
                    "wf_a": ev_cfg.kill_wf_a, "wf_b": ev_cfg.kill_wf_b,
                }
            elif is_killed and ev_cfg.death_enabled:
                result = {
                    "kind": "death", "mode": mode,
                    "ch_a": ev_cfg.death_ch_a, "ch_b": ev_cfg.death_ch_b,
                    "duration": ev_cfg.death_duration,
                    "wf_a": ev_cfg.death_wf_a, "wf_b": ev_cfg.death_wf_b,
                }

        return result

    # ============================================================
    # 主线程：UI 刷新（流畅，不阻塞）
    # ============================================================

    def _schedule_ui_refresh(self):
        """安排下一次 UI 刷新"""
        self.window.after(100, self._ui_tick)

    def _ui_tick(self):
        """主线程定时器 — 检查数据队列并更新 UI"""
        # 1. 取后台检测的事件
        try:
            while True:
                ev = self._event_queue.get_nowait()
                if ev:
                    self._apply_event(ev)
        except queue.Empty:
            pass

        # 2. 取最新游戏数据
        state = None
        try:
            while True:
                state = self._data_queue.get_nowait()
        except queue.Empty:
            pass

        # 3. 应用强度（事件或正常映射）
        if state is not None or self._event_remaining > 0:
            self._apply_game_state(state or GameState())

        # 4. 事件倒计时
        if self._event_remaining > 0:
            self._event_remaining -= 0.1
            # 维修事件：检查是否还在维修中
            if self._event_kind == "repair" and self._last_state.tank and not self._last_state.tank.is_repairing:
                self._event_remaining = 0
                self._repair_active = False
            if self._event_remaining <= 0:
                self._event_remaining = 0
                self._event_kind = ""
                self._repair_active = False
                self.window.dashboard.show_event("")
                self._apply_waveform()
                logger.info("事件结束，恢复正常映射")
            else:
                if self._event_kind == "repair":
                    self.window.dashboard.show_event("🔧 维修中")
                elif self._event_kind == "kill":
                    self.window.dashboard.show_event(f"⚔ 击杀! ({self._event_remaining:.1f}s)")
                else:
                    self.window.dashboard.show_event(f"💀 坠毁!" if self._event_mode == "aircraft" else f"💀 被摧毁! ({self._event_remaining:.1f}s)")

        # 5. 更新郊狼状态
        self._update_coyote_status()

        # 6. 继续
        self._schedule_ui_refresh()

    def _check_events(self):
        """检查 /hudmsg 新记录，检测击杀/死亡事件"""
        mode = self.window.get_mode()
        if mode == "aircraft":
            ev_cfg = self._cfg.events
        elif mode == "tank":
            ev_cfg = self._cfg.tank_events
        else:
            return
        if not ev_cfg.player_name:
            return

        name = ev_cfg.player_name
        records = self.game_reader.fetch_hudmsg(self._last_dmg_id)

        for r in records:
            rid = int(r.get("id", 0))
            if rid > self._last_dmg_id:
                self._last_dmg_id = rid

            msg = r.get("msg", "")
            # 清理 Unicode 零宽字符（战争雷霆消息中夹杂 ​ 导致匹配失败）
            ZERO_WIDTH = set("​‌‍‎‏⁠﻿")
            msg = "".join(c for c in msg if c not in ZERO_WIDTH)

            # 检测击杀：名字在"击落"/"击毁"前面（中间可能有载具名）
            is_kill = False
            for kw in ["击落了", "击毁了"]:
                if kw in msg and name in msg.split(kw, 1)[0]:
                    is_kill = True
                    break

            # 检测被击落：玩家名出现在"击落"/"击毁"后面
            is_killed = False
            for kw in ["击落了", "击毁了"]:
                if kw in msg:
                    if name in msg.split(kw, 1)[1]:
                        is_killed = True
                        break
            # 检测坠毁：玩家名 + 可能有载具名 + "已坠毁"
            if not is_killed and name in msg and "已坠毁" in msg:
                is_killed = True

            if is_kill and ev_cfg.kill_enabled:
                self._event_kind = "kill"
                self._event_mode = mode
                self._event_ch_a = ev_cfg.kill_ch_a
                self._event_ch_b = ev_cfg.kill_ch_b
                self._event_remaining = ev_cfg.kill_duration
                self.coyote.set_waveform_a(ev_cfg.kill_wf_a)
                self.coyote.set_waveform_b(ev_cfg.kill_wf_b)
                logger.info(f"击杀检测! A={self._event_ch_a} B={self._event_ch_b} 持续={self._event_remaining}s")
                self.window.dashboard.show_event(
                    f"⚔ 击杀! ({self._event_remaining:.1f}s)")

            elif is_killed and ev_cfg.death_enabled:
                self._event_kind = "death"
                self._event_mode = mode
                self._event_ch_a = ev_cfg.death_ch_a
                self._event_ch_b = ev_cfg.death_ch_b
                self._event_remaining = ev_cfg.death_duration
                self.coyote.set_waveform_a(ev_cfg.death_wf_a)
                self.coyote.set_waveform_b(ev_cfg.death_wf_b)
                logger.info(f"被击落检测! A={self._event_ch_a} B={self._event_ch_b} 持续={self._event_remaining}s")
                self.window.dashboard.show_event(
                    f"💀 被击落! ({self._event_remaining:.1f}s)")

    def _apply_game_state(self, state: GameState):
        """将游戏状态应用到 UI 和郊狼设备"""
        self._last_state = state  # 缓存，供模式切换时即时刷新
        mode = self.window.get_mode()
        cfg = self._cfg

        # 防抖：连续 3 次失败才认为断开
        if state.connected:
            self._wt_fail_count = 0
            if not self._wt_connected:
                self._wt_connected = True
                self.window.status_bar.set_wt_status(True)
        else:
            self._wt_fail_count += 1
            if self._wt_fail_count >= 3 and self._wt_connected:
                self._wt_connected = False
                self.window.status_bar.set_wt_status(False)

        if not state.connected and self._event_remaining <= 0:
            self.window.dashboard.clear(mode)
            if self.coyote.status.bound:
                self._send_strength(0, 0)
            return

        intensity_a = 0
        intensity_b = 0

        # 事件覆盖：击杀/被击落期间用事件强度替代 G 值映射
        if self._event_remaining > 0:
            intensity_a = self._event_ch_a
            intensity_b = self._event_ch_b
            if self._event_kind == "kill":
                label = "⚔ 击杀!"
            elif self._event_kind == "death":
                label = "💀 坠毁!" if self._event_mode == "aircraft" else "💀 被摧毁!"
            else:
                label = "🔧 维修中"
            self.window.dashboard.value_label.config(text=label)
            self.window.dashboard.unit_label.config(text="")
            self.window.dashboard.ch_a_label.config(
                text=f"A通道: {intensity_a}")
            self.window.dashboard.ch_b_label.config(
                text=f"B通道: {intensity_b}")

        elif mode == "aircraft" and state.aircraft and state.aircraft.valid:
            ac = state.aircraft
            ac_cfg = cfg.aircraft
            if ac_cfg.enabled:
                intensity_a, intensity_b = MappingEngine.map_aircraft(
                    ac.gforce, ac_cfg.gforce_min, ac_cfg.gforce_max,
                    ac_cfg.channel_a_max, ac_cfg.channel_b_max)
            self.window.dashboard.update_aircraft(
                ac.gforce, intensity_a, intensity_b)

        elif mode == "tank":
            # 陆战模式：根据实际载具类型选择触发方式
            if state.vehicle_type == "aircraft" and state.aircraft and state.aircraft.valid:
                # 上了飞机 → CAS 设置 + G值触发
                ac = state.aircraft
                cas_cfg = cfg.cas
                self.coyote.set_waveform_a(cas_cfg.waveform_a, cas_cfg.random_interval)
                self.coyote.set_waveform_b(cas_cfg.waveform_b, cas_cfg.random_interval)
                intensity_a, intensity_b = MappingEngine.map_aircraft(
                    ac.gforce, cas_cfg.gforce_min, cas_cfg.gforce_max,
                    cas_cfg.channel_a_max, cas_cfg.channel_b_max)
                self.window.dashboard.update_aircraft(
                    ac.gforce, intensity_a, intensity_b)
            elif state.vehicle_type == "tank" and state.tank and state.tank.valid:
                # 在地面 → 速度触发
                tk_data = state.tank
                tk_cfg = cfg.tank
                self.coyote.set_waveform_a(tk_cfg.waveform_a, tk_cfg.random_interval)
                self.coyote.set_waveform_b(tk_cfg.waveform_b, tk_cfg.random_interval)
                if tk_cfg.enabled:
                    intensity_a, intensity_b = MappingEngine.map_tank(
                        tk_data.speed_kmh,
                        tk_cfg.speed_min, tk_cfg.speed_max,
                        tk_cfg.channel_a_max, tk_cfg.channel_b_max)
                else:
                    intensity_a, intensity_b = 0, 0
                self.window.dashboard.update_tank(
                    tk_data.speed_kmh, intensity_a, intensity_b)
            else:
                self.window.dashboard.clear(mode)

        else:
            self.window.dashboard.clear(mode)

        # 发送到郊狼
        if self.coyote.status.bound:
            self._send_strength(intensity_a, intensity_b)

        # 同步悬浮窗（事件期间降低刷新率，避免倒计时变化导致频繁重绘闪烁）
        self._overlay_tick += 1
        if self._overlay_tick >= 2:
            self._overlay_tick = 0
            self._sync_overlay(mode, intensity_a, intensity_b)

    def _apply_event(self, ev: dict):
        """应用后台检测到的事件"""
        self._event_kind = ev["kind"]
        self._event_mode = ev["mode"]
        self._event_ch_a = ev["ch_a"]
        self._event_ch_b = ev["ch_b"]
        self._event_remaining = ev["duration"]
        self.coyote.set_waveform_a(ev["wf_a"])
        self.coyote.set_waveform_b(ev["wf_b"])
        if ev["kind"] == "kill":
            label = "⚔ 击杀!"
        elif ev["kind"] == "death":
            label = "💀 坠毁!" if ev["mode"] == "aircraft" else "💀 被摧毁!"
        else:
            label = "🔧 维修中"
        if ev["kind"] == "repair":
            self.window.dashboard.show_event("🔧 维修中")
        else:
            self.window.dashboard.show_event(f"{label} ({ev['duration']:.1f}s)")
        logger.info(f"事件触发: {label} A={ev['ch_a']} B={ev['ch_b']}")

    def _on_mode_switched(self):
        """模式切换/设置保存回调 — 刷新仪表盘 + 同步波形"""
        if self._window_ready:
            self._current_mode = self.window.get_mode()
        else:
            self._current_mode = self._cfg.app.mode
        # 清空悬浮窗缓存，避免旧模式数据残留
        self._overlay_last_value = ""
        self._overlay_last_unit = ""
        logger.info(f"模式变更: current_mode={self._current_mode} cfg.mode={self._cfg.app.mode}")
        if hasattr(self, "window") and self.window is not None:
            self._apply_game_state(self._last_state)
            self._apply_waveform()

    def _update_coyote_status(self):
        """同步郊狼状态到 UI"""
        status = self.coyote.status
        self.window.status_bar.set_coyote_status(
            status.bound,
            status.address if status.bound else ""
        )
        if status.bound:
            self.window.qr_widget.set_status("✓ 已连接，电击输出中")
        elif status.server_running:
            self.window.qr_widget.set_status("等待手机扫码连接...",
                                             status.address)
        else:
            self.window.qr_widget.set_status("WebSocket 服务启动中...")

    # ============================================================
    # 郊狼控制
    # ============================================================

    def _sync_overlay(self, mode: str, intensity_a: int, intensity_b: int):
        """同步数据到悬浮窗"""
        ov = self.overlay
        want = self.window.dashboard.overlay_var.get()
        if want != ov.visible:
            if want:
                ov.show()
            else:
                ov.hide()
            self._cfg.app.overlay_enabled = want
            self._cfg.app.overlay_size = self.window.overlay_size
            self.config_mgr.save()
        if ov.visible:
            size = self.window.overlay_size
            if size != ov.get_size():
                ov.set_size(size)
                self._cfg.app.overlay_size = size
                self.config_mgr.save()

        if not ov.visible:
            return

        # 构建数据显示
        last = self._last_state
        event_text = ""
        if self._event_remaining > 0:
            if self._event_kind == "repair":
                event_text = "🔧 维修中"
            elif self._event_kind == "kill":
                event_text = f"⚔ 击杀! ({self._event_remaining:.1f}s)"
            elif self._event_kind == "death":
                event_text = f"💀 坠毁! ({self._event_remaining:.1f}s)" if self._event_mode == "aircraft" else f"💀 被摧毁! ({self._event_remaining:.1f}s)"

        value = "--"
        unit = "G"
        if mode == "aircraft":
            if last.aircraft and last.aircraft.valid:
                value = f"{last.aircraft.gforce:.1f}"
        else:
            if last.vehicle_type == "aircraft" and last.aircraft and last.aircraft.valid:
                # CAS: 陆战上飞机，显示过载
                value = f"{last.aircraft.gforce:.1f}"
            else:
                unit = "km/h"
                if last.tank and last.tank.valid:
                    value = f"{last.tank.speed_kmh:.0f}"

        # 数据短暂无效时沿用上次有效值，避免数值与 -- 之间来回跳动
        if value == "--" and self._overlay_last_value:
            value = self._overlay_last_value
            unit = self._overlay_last_unit
        elif value != "--":
            self._overlay_last_value = value
            self._overlay_last_unit = unit

        # 仅在值变化时更新（减少闪烁）
        ov.update(mode, value, unit, intensity_a, intensity_b, event_text)

    def _apply_waveform(self):
        """根据当前模式同步波形设置到郊狼"""
        mode = self.window.get_mode()
        if mode == "aircraft":
            cfg = self._cfg.aircraft
        else:
            # 陆战模式先用坦克波形（后续会根据实际载具切 CAS）
            cfg = self._cfg.tank
        logger.info(f"同步波形: mode={mode} A={cfg.waveform_a} B={cfg.waveform_b}")
        self.coyote.set_waveform_a(cfg.waveform_a, cfg.random_interval)
        self.coyote.set_waveform_b(cfg.waveform_b, cfg.random_interval)

    def _start_coyote(self):
        """启动郊狼 WebSocket 服务端并生成 QR 码"""
        if self._coyote_started:
            return

        logger.info("正在启动郊狼 WebSocket 服务端...")
        success = self.coyote.start()

        if success:
            self._coyote_started = True
            url = self.coyote.get_qrcode_url()
            logger.info(f"服务端已启动: {url}")
            self._generate_qr_image(url)
            self.window.qr_widget.set_status("等待手机扫码连接...", url)
            # 延迟同步波形设置（等绑定完成）
            self.window.after(3000, self._apply_waveform)
        else:
            logger.error("郊狼服务端启动失败")
            self.window.qr_widget.set_status("⚠ 服务启动失败，请检查端口")
            self.window.after(5000, self._start_coyote)

    def _generate_qr_image(self, url: str):
        """生成 QR 码并显示在 GUI 上"""
        try:
            qr = qrcode.QRCode(
                version=1, error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8, border=2,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#2C3E50", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            pil_img = Image.open(buf)
            tk_img = ImageTk.PhotoImage(pil_img.resize((120, 120)))
            self.window.qr_widget.qr_canvas.delete("all")
            self.window.qr_widget.qr_canvas.create_image(60, 60, image=tk_img)
            self.window.qr_widget._qr_image_ref = tk_img
        except Exception as e:
            logger.error(f"QR 码生成失败: {e}")

    def _send_strength(self, value_a: int, value_b: int):
        """向郊狼发送双通道强度"""
        status = self.coyote.status
        if value_a > 0 or value_b > 0:
            if not status.bound:
                logger.warning(f"强度 A={value_a} B={value_b} 但郊狼未绑定! 请手机扫码连接")
            elif not status.server_running:
                logger.warning(f"强度 A={value_a} B={value_b} 但服务端未运行!")
            else:
                logger.info(f"发送强度: A={value_a} B={value_b}")
        self.coyote.set_strength_a(value_a)
        self.coyote.set_strength_b(value_b)


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
