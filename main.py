"""郊狼雷霆 v1 beta_1 — 战争雷霆 × 郊狼 3.0 电击联动

启动方式：
    python main.py

架构：
    战争雷霆 :8111 ──HTTP──► GameReader ──► MappingEngine ──► V3/V4 Controller ──WS──► 手机App ──BLE──► 郊狼
                                                        │
                                                    MainWindow (PySide6 GUI)
"""

import sys
import os
import io
import logging
import threading
import queue

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qrcode
from PIL import Image
from PySide6.QtWidgets import QApplication

from src.config_manager import ConfigManager
from src.event_detector import EventDetector
from src.game_reader import GameReader, GameState
from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import CoyoteV4Controller
from src.mapping_engine import MappingEngine
from src.gui.disclaimer_dialog import show_disclaimer_dialog
from src.gui.main_window import MainWindow
from src.gui.overlay import OverlayWindow
from src.single_instance import SingleInstance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("WT-DGLAB")


def _application_directory() -> str:
    """返回源码项目目录或打包后 EXE 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _config_file_path() -> str:
    """返回与 EXE 同目录的配置文件路径。"""
    return os.path.join(_application_directory(), "config.json")


def _load_config_manager() -> ConfigManager:
    """加载同目录配置，并在首次启动时创建默认配置文件。"""
    config_path = _config_file_path()
    config_exists = os.path.isfile(config_path)
    manager = ConfigManager(config_path)
    manager.load()
    if not config_exists:
        manager.save()
        logger.info(f"已生成默认配置: {config_path}")
    return manager


class App:
    """应用主控制器 — 后台线程读取游戏数据，主线程只负责更新 GUI"""

    def __init__(self):
        # ===== 配置 =====
        self.config_mgr = _load_config_manager()

        # ===== 状态缓存（必须在 GUI 之前初始化，因为 GUI 初始化会触发回调）=====
        self._last_state = GameState()
        self._coyote_started = False

        # 事件输出状态
        self._event_kind = ""       # "" / "kill" / "death"
        self._event_mode = ""       # "aircraft" / "tank"
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0  # 剩余秒数
        self._current_mode = self._cfg.app.mode
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
        self.window.dashboard.set_overlay_callback(
            self._apply_overlay_settings
        )
        if self._cfg.app.overlay_enabled:
            self.overlay.show()
            self.overlay.set_size(self._cfg.app.overlay_size)
            self.window.dashboard.overlay_var.set(True)
            self.window.dashboard._overlay_size_var.set(
                self._cfg.app.overlay_size)

        # ===== 游戏数据读取器 =====
        self.game_reader = GameReader()
        self.event_detector = EventDetector(self.game_reader)

        # ===== 郊狼控制器 =====
        self._coyote_protocol = self._cfg.app.dglab_protocol
        self.coyote = self._create_coyote_controller()

        # ===== 线程间通信 =====
        self._data_queue = queue.Queue(maxsize=2)  # 只保留最新游戏数据
        self._event_queue = queue.Queue(maxsize=2)  # 最新事件数据
        self._coyote_start_queue = queue.Queue(maxsize=2)
        self._coyote_starting = False
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
        # 先将主窗口带到前台，避免模态注意事项附着在隐藏父窗口上。
        self.window.show_startup()

        # 首次启动显示注意事项
        if not self._cfg.app.notice_accepted:
            if not self._show_disclaimer_dialog():
                return  # 用户关闭对话框则退出
            self._cfg.app.notice_accepted = True
            self.config_mgr.save()

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
        self.window.set_close_callback(self._on_close)

        # 进入 Qt 主循环
        self.window.run()

    def _on_close(self):
        """托盘退出回调 — 保存配置并清理后台资源。"""
        self.window.save_current_settings()
        self.config_mgr.save()
        self._running = False
        self.coyote.clear_all()
        self.coyote.stop()
        self.overlay.destroy()
        self.window.quit()

    def _show_disclaimer_dialog(self) -> bool:
        """每次启动显示注意事项对话框。返回 True 表示确认，False 表示关闭。"""
        confirmed = show_disclaimer_dialog(self.window)
        if not confirmed:
            self.window.quit()
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

            self._poll_events(state)

            # 等待下一次轮询
            self._running_event = threading.Event()
            self._running_event.wait(
                max(self._cfg.app.refresh_interval_ms / 1000.0, 0.05)
            )

    def _poll_events(self, state: GameState) -> None:
        """调用独立检测器，并将新事件放入主线程队列。"""
        try:
            event = self.event_detector.poll(
                state,
                self._current_mode,
                self._cfg.events,
                self._cfg.tank_events,
                self._cfg.cas.enabled,
            )
            if not event:
                return

            logger.info(
                f"检测到事件: {event['kind']} mode={event.get('mode', '')}"
            )
            try:
                self._event_queue.put(event, block=False)
            except queue.Full:
                try:
                    self._event_queue.get_nowait()
                    self._event_queue.put(event, block=False)
                except queue.Empty:
                    pass
        except Exception as error:
            logger.warning(f"事件检测异常: {error}", exc_info=True)

    # ============================================================
    # 主线程：UI 刷新（流畅，不阻塞）
    # ============================================================

    def _schedule_ui_refresh(self):
        """安排下一次 UI 刷新"""
        self.window.after(100, self._ui_tick)

    def _ui_tick(self):
        """主线程定时器 — 检查数据队列并更新 UI"""
        try:
            # 1. 取后台检测的事件
            try:
                while True:
                    event = self._event_queue.get_nowait()
                    if event:
                        self._apply_event(event)
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
            if state is not None:
                self._apply_game_state(state)
            elif self._event_remaining > 0:
                # 事件可能先于下一帧遥测入队。此时复用最后一份已验证状态，
                # 不能构造空状态，否则会被安全归零分支误判为离开对局。
                self._apply_game_state(self._last_state)

            # 4. 事件倒计时
            if self._event_remaining > 0:
                self._event_remaining -= 0.1
                # 维修事件：检查是否还在维修中
                if (self._event_kind == "repair" and self._last_state.tank
                        and not self._last_state.tank.is_repairing):
                    self._event_remaining = 0
                if self._event_remaining <= 0:
                    self._finish_active_event()
                elif self._event_kind == "repair":
                    self.window.dashboard.show_event("🔧 维修中")
                elif self._event_kind == "kill":
                    self.window.dashboard.show_event(
                        f"⚔ 击杀! ({self._event_remaining:.1f}s)"
                    )
                else:
                    text = (
                        "💀 坠毁!"
                        if self._event_mode == "aircraft"
                        else f"💀 被摧毁! ({self._event_remaining:.1f}s)"
                    )
                    self.window.dashboard.show_event(text)

            # 5. 更新郊狼状态
            self._process_coyote_start_result()
            self._update_coyote_status()
        except Exception as error:
            logger.error(f"UI 刷新异常: {error}", exc_info=True)
        finally:
            # 即使显示分支异常，仍保持 UI 定时器存活。
            if self._running:
                self._schedule_ui_refresh()

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

        # 未确认仍在有效对局时，所有可能残留的 8111 指标都不可信。
        # 此处不使用连接状态防抖，避免退出对局后仍持续数个轮询周期的输出。
        if not state.connected:
            if self.coyote.status.bound:
                self._send_strength(0, 0)
            self._cancel_active_event()
            self.window.dashboard.clear(mode)
            self._overlay_last_value = ""
            self._overlay_last_unit = ""
            self._sync_overlay(mode, 0, 0)
            return

        cas_active = mode == "tank" and state.vehicle_type == "aircraft"
        if (cas_active and not cfg.cas.enabled
                and self._event_mode == "aircraft"
                and self._event_remaining > 0):
            self._cancel_active_event("CAS 触发已关闭，取消 CAS 事件输出")

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
            self.window.dashboard.update_event(
                label, intensity_a, intensity_b
            )

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
                if cas_cfg.enabled:
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

    def _cancel_active_event(self, reason: str =
                             "已离开有效对局，取消事件输出并恢复常规波形"):
        """取消事件覆盖并记录原因，避免事件强度继续输出。"""
        had_event = self._event_remaining > 0 or bool(self._event_kind)
        self._event_kind = ""
        self._event_mode = ""
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0
        self.window.dashboard.show_event("")

        if had_event:
            self._apply_waveform()
            logger.info(reason)

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

    def _finish_active_event(self) -> None:
        """结束当前事件，并在仍维修时从击杀/死亡切回维修输出。"""
        finished_kind = self._event_kind
        self._event_kind = ""
        self._event_mode = ""
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0

        if (finished_kind in {"kill", "death"}
                and self._resume_repair_if_active()):
            logger.info("击杀/死亡事件结束，检测到仍在维修，恢复维修输出")
            return

        self.window.dashboard.show_event("")
        self._apply_waveform()
        logger.info("事件结束，恢复正常映射")

    def _resume_repair_if_active(self) -> bool:
        """当前坦克仍在维修且功能启用时，立即应用维修事件。"""
        state = self._last_state
        tank = state.tank if state.vehicle_type == "tank" else None
        config = self._cfg.tank_events
        if (not state.connected or not tank or not tank.valid
                or not tank.is_repairing or not config.repair_enabled):
            return False

        self._apply_event({
            "kind": "repair",
            "mode": "tank",
            "ch_a": config.repair_ch_a,
            "ch_b": config.repair_ch_b,
            "duration": 60.0,
            "wf_a": config.repair_wf_a,
            "wf_b": config.repair_wf_b,
        })
        return True

    def _on_mode_switched(self):
        """模式切换/设置保存回调 — 刷新仪表盘 + 同步波形"""
        if hasattr(self, "coyote"):
            self._switch_coyote_protocol_if_needed()
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
        if (self._coyote_protocol == "v4" and self._coyote_started
                and not self._coyote_starting
                and not status.server_running):
            self._coyote_started = False
            self.window.after(5000, self._start_coyote)
        self.window.status_bar.set_coyote_status(
            status.bound,
            status.address if status.bound else ""
        )
        if status.bound:
            self.window.qr_widget.set_status("✓ 已连接")
        elif status.server_running:
            if self._coyote_protocol == "v4" and status.client_connected:
                text = "App 已接入，等待郊狼设备..."
            else:
                text = "等待手机扫码连接..."
            self.window.qr_widget.set_status(text, status.address)
        else:
            text = (
                "正在连接 V4 Relay..."
                if self._coyote_protocol == "v4"
                else "WebSocket 服务启动中..."
            )
            if status.error:
                text = f"⚠ {status.error}"
            self.window.qr_widget.set_status(text)

    # ============================================================
    # 郊狼控制
    # ============================================================

    def _create_coyote_controller(self):
        """按当前配置创建 V3 或 V4 控制器。"""
        if self._cfg.app.dglab_protocol == "v4":
            return CoyoteV4Controller(self._cfg.app.v4_relay_url)
        return CoyoteController(port=self._cfg.app.ws_port)

    def _switch_coyote_protocol_if_needed(self) -> None:
        """设置保存后按需重建郊狼连接控制器。"""
        desired = self._cfg.app.dglab_protocol
        connection_changed = desired != self._coyote_protocol
        if desired == "v3" and isinstance(self.coyote, CoyoteController):
            connection_changed = connection_changed or (
                self.coyote.port != self._cfg.app.ws_port
            )
        elif desired == "v4" and isinstance(
                self.coyote, CoyoteV4Controller):
            connection_changed = connection_changed or (
                self.coyote.relay_url
                != CoyoteV4Controller.normalize_relay_url(
                    self._cfg.app.v4_relay_url
                )
            )

        if not connection_changed:
            return

        logger.info(f"切换 DG-LAB 连接协议: {self._coyote_protocol} -> {desired}")
        self.coyote.clear_all()
        self.coyote.stop()
        self._coyote_protocol = desired
        self._coyote_started = False
        self._coyote_starting = False
        self.coyote = self._create_coyote_controller()
        self.window.qr_widget.clear_qr_image()
        self.window.after(200, self._start_coyote)

    def _sync_overlay(self, mode: str, intensity_a: int, intensity_b: int):
        """同步数据到悬浮窗"""
        self._apply_overlay_settings()
        ov = self.overlay
        if not ov.visible:
            return

        # 构建数据显示
        last = self._last_state
        if not last.connected:
            self._overlay_last_value = ""
            self._overlay_last_unit = ""
            unit = "G" if mode == "aircraft" else "km/h"
            ov.update(mode, "--", unit, 0, 0, "")
            return

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

    def _apply_overlay_settings(self):
        """立即应用悬浮窗开关和大小，并在变更时保存配置。"""
        ov = self.overlay
        want = self.window.dashboard.overlay_var.get()
        size = self.window.overlay_size
        changed = False

        if want != ov.visible:
            if want:
                ov.show()
            else:
                ov.hide()
            changed = True

        if size != ov.get_size():
            ov.set_size(size)
            changed = True

        if self._cfg.app.overlay_enabled != want:
            self._cfg.app.overlay_enabled = want
            changed = True
        if self._cfg.app.overlay_size != size:
            self._cfg.app.overlay_size = size
            changed = True
        if changed:
            self.config_mgr.save()

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
        """启动当前协议控制器并生成对应 App 配对二维码。"""
        if self._coyote_started or self._coyote_starting:
            return

        label = "V4 Relay" if self._coyote_protocol == "v4" else "V3 服务端"
        logger.info(f"正在启动郊狼 {label}...")
        self._coyote_starting = True
        controller = self.coyote
        thread = threading.Thread(
            target=self._start_coyote_worker,
            args=(controller, label),
            daemon=True,
        )
        thread.start()

    def _start_coyote_worker(self, controller, label: str) -> None:
        """在后台等待连接控制器启动，避免阻塞 Qt 主线程。"""
        success = controller.start()
        url = controller.get_qrcode_url() if success else ""
        result = (controller, label, success, url, controller.status.error)
        try:
            self._coyote_start_queue.put(result, block=False)
        except queue.Full:
            pass

    def _process_coyote_start_result(self) -> None:
        """在 Qt 主线程应用后台连接结果。"""
        if not hasattr(self, "_coyote_start_queue"):
            return
        try:
            while True:
                controller, label, success, url, error = (
                    self._coyote_start_queue.get_nowait()
                )
                if controller is not self.coyote:
                    controller.stop()
                    continue
                self._coyote_starting = False
                self._finish_coyote_start(label, success, url, error)
        except queue.Empty:
            pass

    def _finish_coyote_start(self, label: str, success: bool,
                             url: str, error: str) -> None:
        """更新二维码、状态提示和失败重试。"""

        if success:
            self._coyote_started = True
            logger.info(f"{label}已启动: {url}")
            self._generate_qr_image(url)
            self.window.qr_widget.set_status("等待手机扫码连接...", url)
            # 延迟同步波形设置（等绑定完成）
            self.window.after(3000, self._apply_waveform)
        else:
            logger.error(f"郊狼{label}启动失败: {error}")
            message = error or "连接服务启动失败"
            self.window.qr_widget.set_status(f"⚠ {message}")
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
            self.window.qr_widget.set_qr_image(pil_img)
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
    # QApplication 先于单实例服务创建，保证本地 IPC 可以安全监听。
    qt_app = QApplication.instance() or QApplication(sys.argv)
    instance = SingleInstance()
    if not instance.acquire():
        return

    app = App()
    instance.set_activate_callback(app.window.restore_from_tray)
    try:
        app.run()
    finally:
        instance.close()


if __name__ == "__main__":
    main()
