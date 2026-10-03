"""郊狼雷霆 v1.1 — 战争雷霆 × 郊狼 3.0 电击联动

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
import random
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qrcode
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.config_manager import ConfigManager
from src.event_detector import EventDetector
from src.game_reader import GameReader, GameState
from src.connection_service import ConnectionService
from src.dglab_state import ChannelTarget, OutputIntent, WaveformConfig
from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import CoyoteV4Controller
from src.waveforms import WaveformCatalog
from src.mapping_engine import MappingEngine
from src.gui.disclaimer_dialog import show_disclaimer_dialog
from src.gui.main_window import MainWindow, OverlayContentDialog, SAVE_DEBOUNCE_MS
from src.gui.overlay import OverlayWindow, OVERLAY_CONTENT_FLAGS
from src.gui.waveform_scope import ChannelScopeDialog
from src.runtime_paths import application_directory, resource_path
from src.single_instance import SingleInstance
from src.runtime_logging import (
    start_session, mark_runtime_abnormal, StrengthLogSummary,
)
from src.version import APP_VERSION
from src.connection_diagnostics import ConnectionDiagnostics

logger = logging.getLogger("WT-DGLAB")


def _application_directory() -> str:
    """返回源码项目目录或打包后 EXE 所在目录。"""
    return application_directory()


def _config_file_path() -> str:
    """返回与 EXE 同目录的配置文件路径。"""
    return os.path.join(_application_directory(), "config.json")


def _load_config_manager() -> ConfigManager:
    """加载同目录配置，缺失时用安全模板生成配置文件。"""
    config_path = _config_file_path()
    config_exists = os.path.isfile(config_path)
    manager = ConfigManager(config_path)
    if config_exists:
        manager.load()
    else:
        manager.load_template(
            os.path.join(_application_directory(), "config.default.json")
        )
        logger.info("未找到用户配置，将使用安全默认模板")
    if not config_exists:
        try:
            manager.save()
            logger.info(f"已生成默认配置: {config_path}")
        except OSError as error:
            # 目录只读时继续以内存配置运行，窗口出现后再提示用户
            manager.save_error = f"程序目录不可写，设置将无法保存：{error}"
            logger.warning(manager.save_error)
    return manager


class App:
    """应用主控制器 — 后台线程读取游戏数据，主线程只负责更新 GUI"""

    # 旧接口兼容路径的保活间隔；主程序使用输出意图，波形由后台独立调度。
    STRENGTH_KEEPALIVE_S = 0.5
    # 退出时等待全部后台线程结束的总时长（秒）
    SHUTDOWN_WAIT_S = 5.0
    # UI 刷新节拍（秒），与 window.after(100, ...) 一致
    UI_TICK_S = 0.1

    # 死亡封锁解除所需持续移动帧数（约 1 秒）：
    # 坦克被击毁瞬间的残留速度帧只有一两帧，不足以确认玩家真的在开动。
    IDLE_UNBLOCK_FRAMES = 10

    def __init__(self):
        self._shutdown_complete = False
        self._shutdown_started = False
        self._stop_event = threading.Event()
        self._start_workers = []
        # 协议 / 端口切换后待停止的旧控制器，由下一次启动线程先行停止
        self._retiring_controllers = []
        self._controllers = []
        self._strength_summary = StrengthLogSummary()
        # ===== 配置 =====
        self.config_mgr = _load_config_manager()
        self.waveform_catalog = WaveformCatalog()
        reload_result = self.waveform_catalog.reload()
        if reload_result.errors:
            logger.warning("波形文件跳过: %s", "; ".join(f"{n}: {e}" for n, e in reload_result.errors))

        # ===== 状态缓存（必须在 GUI 之前初始化，因为 GUI 初始化会触发回调）=====
        self._last_state = GameState()
        self._coyote_started = False

        # 事件输出状态
        self._event_kind = ""       # "" / "kill" / "death" / "repair" / "hit"
        self._event_mode = ""       # "aircraft" / "tank"
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0  # 剩余秒数
        self._event_clock = None     # 上次倒计时的 time.monotonic()，按实际耗时扣减
        self._repair_blocked_until_idle = False
        self._repair_death_state = None
        # 静止惩罚状态（仅陆战驾驶坦克时生效）
        self._idle_active = False          # 静止惩罚输出中
        self._idle_start_time = None       # 静止计时起点 (time.monotonic 秒)
        self._idle_label_shown = False     # 仪表盘静止提示显示中
        self._idle_death_blocked = False   # 死亡封锁：复活后首次移动才解除
        self._idle_move_frames = 0         # 死亡封锁解除的持续移动帧计数
        # 部件损伤短脉冲状态
        # 上一帧已损毁部件集合；None 表示基线未知（启动 / 离开陆战地面后），
        # 下一有效坦克帧只建立基线不触发
        self._last_damaged_parts = None
        self._last_hit_time = 0.0          # 上次部件损伤触发时间（冷却用）
        self._current_mode = self._cfg.app.mode
        self._wt_fail_count = 0
        self._wt_connected = False
        self._overlay_tick = 0                      # 悬浮窗节流计数
        self._overlay_last_g = ""                   # 悬浮窗缓存：上次有效过载文本
        self._overlay_last_speed = ""               # 悬浮窗缓存：上次有效速度文本
        self._scope_dialogs: dict[str, ChannelScopeDialog] = {}  # 通道曲线窗口单例
        self._overlay_content_dialog = None         # 悬浮窗显示内容设置单例
        self._window_ready = False

        # ===== GUI =====
        self.window = MainWindow(self.config_mgr,
                                 waveform_catalog=self.waveform_catalog,
                                 on_mode_changed=self._on_mode_switched)
        self._window_ready = True

        # ===== 悬浮窗 =====
        self.overlay = OverlayWindow()
        self.window.dashboard.set_overlay_callback(
            self._apply_overlay_settings
        )
        self.window.dashboard.set_overlay_content_callback(
            self._open_overlay_content_dialog
        )
        self.window.dashboard.set_scope_callback(
            self._open_channel_scope
        )
        self.overlay.value_font_changed.connect(
            self._on_overlay_value_font_changed
        )
        self.overlay.content_settings_requested.connect(
            self._open_overlay_content_dialog
        )
        self.overlay.set_content_flags(self._overlay_content_flags())
        if self._cfg.app.overlay_enabled:
            self.overlay.show()
            self.overlay.set_value_font(self._cfg.app.overlay_size_px)

        # ===== 游戏数据读取器 =====
        self.game_reader = GameReader()
        self._connection_diagnostics = ConnectionDiagnostics()
        self.event_detector = EventDetector(self.game_reader)

        # ===== 郊狼控制器 =====
        self._coyote_protocol = self._cfg.app.dglab_protocol
        self.coyote = self._create_coyote_controller()
        self._controllers.append(self.coyote)
        self._connection_service = ConnectionService(self.coyote)
        self._desired_waveforms = {"A": WaveformConfig(), "B": WaveformConfig()}
        self._output_revision = 0
        self._last_connection_session = None
        self.window.qr_widget.on_device_selected = self._select_coyote_device

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

        # 配置文件有字段被修正时提示一次，说明原文件备份位置
        self._show_config_issues()

        # 首次启动显示注意事项
        if not self._cfg.app.notice_accepted:
            if not self._show_disclaimer_dialog():
                self._on_close()
                return  # 用户关闭对话框则退出
            self._cfg.app.notice_accepted = True
            try:
                self.config_mgr.save()
            except OSError as error:
                logger.warning("保存注意事项确认状态失败：%s", error)

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

    def _show_config_issues(self) -> None:
        """启动时若配置有字段被恢复默认，弹窗列出修正项与备份文件。"""
        save_error = getattr(self.config_mgr, "save_error", "")
        if save_error:
            QMessageBox.warning(self.window, "无法保存设置", save_error)
        issues = self.config_mgr.load_issues
        if not issues:
            return
        shown = issues[:10]
        lines = ["以下配置无效，已恢复默认值："]
        lines += [f"• {issue}" for issue in shown]
        if len(issues) > len(shown):
            lines.append(f"……另有 {len(issues) - len(shown)} 项，详见日志")
        backup = self.config_mgr.invalid_backup_path
        lines.append("")
        lines.append(f"原配置文件已备份到：\n{backup}" if backup
                     else "原配置文件备份失败，详见日志")
        QMessageBox.warning(self.window, "配置已修正", "\n".join(lines))

    def _on_close(self):
        """托盘退出回调 — 保存配置并清理后台资源。"""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._running = False
        self._stop_event.set()
        clean = True
        logger.info("正在退出程序并清理后台资源")

        def cleanup(action, label):
            nonlocal clean
            try:
                action()
            except Exception:
                clean = False
                logger.exception("退出清理失败：%s", label)

        save_timer = getattr(self, "_config_save_timer", None)
        if save_timer is not None:
            save_timer.stop()
        cleanup(self.window.save_current_settings, "保存界面设置")
        cleanup(self.config_mgr.save, "保存配置")
        # 优先归零当前设备，单项清理失败不能阻止其他资源停止。
        deadline = time.monotonic() + self.SHUTDOWN_WAIT_S
        service = getattr(self, "_connection_service", None)
        if service is not None:
            if not service.stop(max(0.0, deadline - time.monotonic())):
                clean = False
                logger.error("郊狼连接会话未能在退出期限内结束")
        else:
            cleanup(self.coyote.stop, "停止当前控制器")
        diagnostics = getattr(self, "_connection_diagnostics", None)
        if diagnostics is not None and not diagnostics.stop():
            clean = False
            logger.warning("后台连接诊断尚未结束，保留本次日志")
        cleanup(self.window.stop_runtime_log_view, "关闭日志窗口")
        workers = list(self._start_workers)
        poller = getattr(self, "_poller_thread", None)
        if poller is not None:
            workers.append(poller)
        # 所有后台线程共享一个总截止时间，避免逐个等待累计十几秒以上
        if service is None:
            deadline = time.monotonic() + self.SHUTDOWN_WAIT_S
        for worker in workers:
            remaining = max(0.0, deadline - time.monotonic())
            cleanup(lambda worker=worker, remaining=remaining:
                    worker.join(timeout=remaining), "等待后台线程")
            if worker.is_alive():
                clean = False
                logger.error("后台线程未能结束：%s", worker.name)
        # 启动线程可能在第一次停止后才创建控制循环，等待后再次清理。
        if service is None:
            for controller in self._controllers:
                cleanup(controller.stop, "停止控制器")
        cleanup(self._strength_summary.flush, "记录最后强度变化")
        for dialog in self._scope_dialogs.values():
            cleanup(dialog.close, "关闭波形窗口")
        cleanup(self.overlay.dispose, "关闭悬浮窗")
        if not clean:
            mark_runtime_abnormal("退出清理未完成")
        self._shutdown_complete = clean
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
                self._last_poll_error = ""
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                if reason != getattr(self, "_last_poll_error", ""):
                    logger.exception("读取游戏数据异常：%s", reason)
                self._last_poll_error = reason
                state = GameState()

            self._connection_diagnostics.observe(state.link_ok)

            # 游戏数据入队
            state.sampled_at = time.monotonic()
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
            self._stop_event.wait(
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

            if hasattr(self, "_connection_service"):
                event["_connection_session"] = (id(self.coyote), self.coyote.snapshot().session)
                event["_created_at"] = time.monotonic()
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
            if hasattr(self, "_connection_service"):
                self._update_coyote_status()
            # 1. 先取最新遥测，死亡事件以本轮状态为基线，不能用它解除限制。
            state = None
            try:
                while True:
                    state = self._data_queue.get_nowait()
            except queue.Empty:
                pass
            if state is not None:
                self._last_state = state
                self._last_telemetry_at = (
                    state.sampled_at if state.sampled_at is not None else time.monotonic())

            # 2. 取后台检测的事件
            try:
                while True:
                    event = self._event_queue.get_nowait()
                    if event:
                        self._apply_event(event)
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
                self._event_remaining -= self._event_elapsed()
                if self._event_remaining <= 0:
                    self._finish_active_event()
                    # 到期当轮即下发恢复后的强度，不能等下一帧遥测。
                    self._apply_game_state(self._last_state)
                elif self._event_kind == "repair":
                    self.window.dashboard.show_event("🔧 维修中")
                elif self._event_kind == "kill":
                    self.window.dashboard.show_event(
                        f"⚔ 击杀! ({self._event_remaining:.1f}s)"
                    )
                elif self._event_kind == "hit":
                    self.window.dashboard.show_event(
                        f"🎯 被命中! ({self._event_remaining:.1f}s)"
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
            if not hasattr(self, "_connection_service"):
                self._update_coyote_status()

            # 6. 同步当前输出波形名到仪表盘通道卡
            self._update_channel_wave_names()
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

        # 死亡当轮及重复使用的缓存不能证明新维修已准备就绪。
        # 仅后续有效坦克帧明确退出维修后，才允许下一次维修触发。
        if (getattr(self, "_repair_blocked_until_idle", False)
                and state is not self._repair_death_state
                and state.connected and state.vehicle_type == "tank"
                and state.tank and state.tank.valid
                and not state.tank.is_repairing):
            self._repair_blocked_until_idle = False
            self._repair_death_state = None
            logger.info("已观察到坦克退出维修，允许新的维修事件")

        # 状态灯反映"战争雷霆 8111 遥测服务是否可达"（主菜单同样为绿色）；
        # 对局判定 connected 只驱动业务，不在此处使用。
        if state.link_ok:
            self._wt_fail_count = 0
            if not self._wt_connected:
                self._wt_connected = True
                logger.info("战争雷霆 8111 已连接/恢复")
                self.window.status_bar.set_wt_status(True)
        else:
            self._wt_fail_count += 1
            if self._wt_fail_count >= 3 and self._wt_connected:
                self._wt_connected = False
                logger.warning("战争雷霆 8111 已断开")
                self.window.status_bar.set_wt_status(False)

        # 未确认仍在有效对局时，所有可能残留的 8111 指标都不可信。
        # 此处不使用连接状态防抖，避免退出对局后仍持续数个轮询周期的输出。
        if not state.connected:
            if self.coyote.status.bound:
                self._send_strength(0, 0)
            self._cancel_active_event()
            self._reset_idle_penalty()
            self._last_damaged_parts = None
            self._idle_death_blocked = False
            self.window.dashboard.clear(mode)
            self._overlay_last_g = ""
            self._overlay_last_speed = ""
            self._sync_overlay(mode, 0, 0)
            return

        cas_active = mode == "tank" and state.vehicle_type == "aircraft"
        if (cas_active and not cfg.cas.enabled
                and self._event_mode == "aircraft"
                and self._event_remaining > 0):
            self._cancel_active_event("CAS 触发已关闭，取消 CAS 事件输出")

        intensity_a = 0
        intensity_b = 0

        if self._event_kind == "repair" and not self._repair_is_active(state):
            self._cancel_active_event("维修已结束、失效或关闭，取消维修输出")

        # 陆战地面上下文：部件损伤边沿检测 + 静止惩罚状态机。
        # 事件覆盖期间计时继续，输出优先级低于事件；
        # 非陆战地面上下文（机库/空战/CAS/数据无效）一律重置。
        if (mode == "tank" and state.vehicle_type == "tank"
                and state.tank and state.tank.valid):
            self._update_part_damage(state.tank)
            self._update_idle_penalty(state.tank, cfg.tank)
        else:
            self._reset_idle_penalty()
            # 离开陆战地面（机库/空战/CAS/数据无效）后旧基线不可信
            self._last_damaged_parts = None

        # 事件覆盖：击杀/被击落期间用事件强度替代 G 值映射
        if self._event_remaining > 0:
            intensity_a = self._event_ch_a
            intensity_b = self._event_ch_b
            if self._event_kind == "kill":
                label = "⚔ 击杀!"
            elif self._event_kind == "death":
                label = "💀 坠毁!" if self._event_mode == "aircraft" else "💀 被摧毁!"
            elif self._event_kind == "hit":
                label = "🎯 被命中!"
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
                    ac_cfg.channel_a_max, ac_cfg.channel_b_max,
                    curve=ac_cfg.curve, steepness=ac_cfg.curve_steepness)
            self.window.dashboard.update_aircraft(
                ac.gforce, intensity_a, intensity_b)

        elif mode == "tank":
            # 陆战模式：根据实际载具类型选择触发方式
            if state.vehicle_type == "aircraft" and state.aircraft and state.aircraft.valid:
                # 上了飞机 → CAS 设置 + G值触发
                ac = state.aircraft
                cas_cfg = cfg.cas
                if cas_cfg.enabled:
                    self._set_normal_waveforms(cas_cfg)
                    intensity_a, intensity_b = MappingEngine.map_aircraft(
                        ac.gforce, cas_cfg.gforce_min, cas_cfg.gforce_max,
                        cas_cfg.channel_a_max, cas_cfg.channel_b_max,
                        curve=cas_cfg.curve,
                        steepness=cas_cfg.curve_steepness)
                self.window.dashboard.update_aircraft(
                    ac.gforce, intensity_a, intensity_b)
            elif state.vehicle_type == "tank" and state.tank and state.tank.valid:
                # 在地面 → 速度触发（静止惩罚生效时持续输出惩罚强度）
                tk_data = state.tank
                tk_cfg = cfg.tank
                idle_active = getattr(self, "_idle_active", False)
                label_shown = getattr(self, "_idle_label_shown", False)
                if idle_active:
                    self._set_idle_waveforms(tk_cfg)
                    intensity_a = tk_cfg.idle_ch_a
                    intensity_b = tk_cfg.idle_ch_b
                    if not label_shown:
                        self._idle_label_shown = True
                        self.window.dashboard.show_event("🛑 静止超时，请移动!")
                else:
                    if label_shown:
                        self._idle_label_shown = False
                        self.window.dashboard.show_event("")
                    self._set_normal_waveforms(tk_cfg)
                    if tk_cfg.enabled:
                        intensity_a, intensity_b = MappingEngine.map_tank(
                            tk_data.speed_kmh,
                            tk_cfg.speed_min, tk_cfg.speed_max,
                            tk_cfg.channel_a_max, tk_cfg.channel_b_max,
                            curve=tk_cfg.curve,
                            steepness=tk_cfg.curve_steepness)
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

    def _event_elapsed(self) -> float:
        """返回本轮倒计时应扣减的秒数：实际经过时间，至少一个 UI 节拍。

        GUI 被拖动窗口 / 模态对话框阻塞时节拍会远大于 100ms，按实际耗时扣减，
        避免事件输出比配置时长更久；正常节拍仍按 0.1 秒扣减。
        """
        now = time.monotonic()
        last = getattr(self, "_event_clock", None)
        self._event_clock = now
        if last is None:
            return self.UI_TICK_S
        return max(self.UI_TICK_S, now - last)

    def _cancel_active_event(self, reason: str =
                             "已离开有效对局，取消事件输出并恢复常规波形"):
        """取消事件覆盖并记录原因，避免事件强度继续输出。"""
        had_event = self._event_remaining > 0 or bool(self._event_kind)
        self._event_kind = ""
        self._event_mode = ""
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0
        self._event_clock = None
        self.window.dashboard.show_event("")

        if had_event:
            # 先停止旧事件输出，再提交恢复波形和强度。
            stop_output = getattr(self.coyote, "stop_output", None)
            if callable(stop_output):
                stop_output()
            self._strength_sent = None
            self._overlay_tick = 1
            self._apply_waveform()
            logger.info(reason)

    def _apply_event(self, ev: dict):
        """应用后台检测到的事件"""
        if ev["kind"] == "death" and ev["mode"] == "tank":
            self._repair_blocked_until_idle = True
            self._repair_death_state = self._last_state
            # 死亡后立即结束静止惩罚并封锁，防止选车界面残留的
            # 有效坦克帧（速度 0）继续触发惩罚；复活后首次移动解除。
            self._reset_idle_penalty()
            self._idle_death_blocked = True
            logger.info("坦克被击毁，作废旧维修并等待有效非维修状态")
        elif ev["kind"] == "repair":
            if (getattr(self, "_repair_blocked_until_idle", False)
                    or (self._event_kind in {"kill", "death"}
                        and self._event_remaining > 0)):
                return
        elif ev["kind"] == "hit":
            # 被命中短脉冲优先级最低：不打断进行中的击杀/坠毁/维修事件，
            # 也不在死亡等待重生期间输出。
            if (self._event_remaining > 0
                    or getattr(self, "_repair_blocked_until_idle", False)):
                logger.info("被命中短脉冲被更高优先级输出抑制")
                return
        if hasattr(self, "_connection_service"):
            snap = self.coyote.snapshot()
            origin = ev.get("_connection_session", (id(self.coyote), snap.session))
            if not snap.bound or origin != (id(self.coyote), snap.session):
                logger.info("丢弃未连接期间或旧会话的事件输出: %s", ev["kind"])
                return
            age = time.monotonic() - ev.get("_created_at", time.monotonic())
            if ev["kind"] != "repair" and age >= ev["duration"]:
                return
        # 接受新事件时先停旧输出，避免新波形短暂使用旧的较高强度。
        stop_output = getattr(self.coyote, "stop_output", None)
        if callable(stop_output):
            stop_output()
        self._strength_sent = None
        self._event_kind = ev["kind"]
        self._event_mode = ev["mode"]
        self._event_ch_a = ev["ch_a"]
        self._event_ch_b = ev["ch_b"]
        self._event_remaining = ev["duration"]
        self._event_deadline = ev.get("_created_at", time.monotonic()) + ev["duration"]
        self._output_revision = getattr(self, "_output_revision", 0) + 1
        self._event_clock = time.monotonic()
        cfg = self._cfg.events if ev["mode"] == "aircraft" else self._cfg.tank_events
        kind = ev["kind"]
        catalog = getattr(self, "waveform_catalog", None)
        choices = [name for name in catalog.choices() if name != "恒定"] if catalog else []
        wf_a = random.choice(choices) if getattr(cfg, f"{kind}_random_a", False) and choices else ev["wf_a"]
        wf_b = random.choice(choices) if getattr(cfg, f"{kind}_random_b", False) and choices else ev["wf_b"]
        self._set_output_waveform("A", wf_a)
        self._set_output_waveform("B", wf_b)
        if ev["kind"] == "kill":
            label = "⚔ 击杀!"
        elif ev["kind"] == "death":
            label = "💀 坠毁!" if ev["mode"] == "aircraft" else "💀 被摧毁!"
        elif ev["kind"] == "hit":
            label = "🎯 被命中!"
        else:
            label = "🔧 维修中"
        if ev["kind"] == "repair":
            self.window.dashboard.show_event("🔧 维修中")
        else:
            self.window.dashboard.show_event(f"{label} ({ev['duration']:.1f}s)")
        logger.info(f"事件触发: {label} A={ev['ch_a']} B={ev['ch_b']}")

    def _finish_active_event(self) -> None:
        """结束当前事件，仅允许击杀结束后恢复仍有效的维修。"""
        finished_kind = self._event_kind
        stop_output = getattr(self.coyote, "stop_output", None)
        if callable(stop_output):
            stop_output()
        self._strength_sent = None
        self._event_kind = ""
        self._event_mode = ""
        self._event_ch_a = 0
        self._event_ch_b = 0
        self._event_remaining = 0.0
        self._event_clock = None
        self._overlay_tick = 1

        if (finished_kind == "kill"
                and self._resume_repair_if_active()):
            logger.info("击杀事件结束，检测到仍在维修，恢复维修输出")
            return

        self.window.dashboard.show_event("")
        self._apply_waveform()
        logger.info("事件结束，恢复正常映射")

    def _repair_is_active(self, state: GameState) -> bool:
        """判断维修数据与开关是否有效，且旧维修未因死亡被作废。"""
        tank = state.tank if state.vehicle_type == "tank" else None
        return bool(
            not getattr(self, "_repair_blocked_until_idle", False)
            and state.connected and tank and tank.valid
            and tank.is_repairing and self._cfg.tank_events.repair_enabled
        )

    def _update_part_damage(self, tank_data) -> None:
        """检测坦克部件/乘员损伤边沿，触发部件损伤短脉冲。

        每帧无条件更新损毁部件基线（基线未知时本帧只建立基线）；出现新损毁部件（被打坏履带、引擎、
        乘员阵亡等）且通过开关与冷却检查时，构造 hit 事件交由
        `_apply_event` 应用（其内部守卫保证不抢占更高级事件输出）。
        """
        current = tank_data.damaged_parts
        previous = getattr(self, "_last_damaged_parts", None)
        self._last_damaged_parts = current
        if previous is None:
            # 重新进入陆战地面：已损坏的部件不是本次边沿，只建立基线
            return
        new_damage = current - previous
        if not new_damage:
            return

        te_cfg = self._cfg.tank_events
        if not getattr(te_cfg, "hit_enabled", False):
            return
        cooldown = float(getattr(te_cfg, "hit_cooldown", 0.0) or 0.0)
        now = time.monotonic()
        if now - getattr(self, "_last_hit_time", 0.0) < cooldown:
            return
        self._last_hit_time = now
        logger.info("部件损伤触发: %s", "、".join(sorted(new_damage)))
        self._apply_event({
            "kind": "hit",
            "mode": "tank",
            "ch_a": te_cfg.hit_ch_a,
            "ch_b": te_cfg.hit_ch_b,
            "duration": te_cfg.hit_duration,
            "wf_a": te_cfg.hit_wf_a,
            "wf_b": te_cfg.hit_wf_b,
        })

    def _update_idle_penalty(self, tank_data, tk_cfg) -> None:
        """更新陆战静止惩罚状态机。

        速度低于阈值持续超过 idle_timeout_s 后进入惩罚输出，直到恢复移动。
        维修中、乘员全灭（被击毁）、死亡等待重生、维修事件激活或功能关闭
        时豁免并重置计时；击杀/被命中事件期间计时继续，仅输出让位给事件。
        被击毁后进入死亡封锁，复活后首次开动才恢复计时。
        """
        exempt = (
            not tk_cfg.idle_enabled
            or tank_data.is_repairing
            or tank_data.crew_alive is False
            or getattr(self, "_repair_blocked_until_idle", False)
            or (self._event_kind == "repair" and self._event_remaining > 0)
        )
        if exempt:
            self._reset_idle_penalty()
            return
        if abs(tank_data.speed_kmh) >= tk_cfg.idle_speed_max:
            if getattr(self, "_idle_death_blocked", False):
                # 死亡瞬间的残留速度帧（坦克被击毁时仍在滑行）只有一两帧，
                # 不能据此解除封锁：持续移动满 IDLE_UNBLOCK_FRAMES 帧才确认。
                frames = getattr(self, "_idle_move_frames", 0) + 1
                self._idle_move_frames = frames
                if frames >= self.IDLE_UNBLOCK_FRAMES:
                    self._idle_death_blocked = False
                    self._idle_move_frames = 0
                    logger.info("坦克持续移动，解除死亡后静止惩罚封锁")
            else:
                self._idle_move_frames = 0
            self._reset_idle_penalty()
            return
        if getattr(self, "_idle_death_blocked", False):
            # 死亡封锁中：选车界面/出生点的静止帧不计时，且清零移动确认。
            self._idle_move_frames = 0
            self._reset_idle_penalty()
            return
        now = time.monotonic()
        start = getattr(self, "_idle_start_time", None)
        if start is None:
            self._idle_start_time = now
            return
        if (not getattr(self, "_idle_active", False)
                and now - start >= tk_cfg.idle_timeout_s):
            self._idle_active = True
            logger.info("静止惩罚触发：速度为 0 已超过 %.1f 秒",
                        tk_cfg.idle_timeout_s)

    def _reset_idle_penalty(self) -> None:
        """退出静止惩罚状态、重置计时并清理仪表盘提示。"""
        self._idle_start_time = None
        if getattr(self, "_idle_active", False):
            self._idle_active = False
            self._overlay_tick = 1
            logger.info("恢复移动，静止惩罚结束")
        if getattr(self, "_idle_label_shown", False):
            self._idle_label_shown = False
            self.window.dashboard.show_event("")

    def _set_idle_waveforms(self, tk_cfg) -> None:
        """静止惩罚期间使用专用波形；随机开关与间隔复用常规配置。"""
        self._set_output_waveform("A", tk_cfg.idle_wf_a, tk_cfg.idle_random_a,
                                   tk_cfg.random_min_a, tk_cfg.random_max_a)
        self._set_output_waveform("B", tk_cfg.idle_wf_b, tk_cfg.idle_random_b,
                                   tk_cfg.random_min_b, tk_cfg.random_max_b)

    def _resume_repair_if_active(self) -> bool:
        """当前坦克仍在有效维修且功能启用时，立即应用维修事件。"""
        config = self._cfg.tank_events
        if not self._repair_is_active(self._last_state):
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
        self._overlay_last_g = ""
        self._overlay_last_speed = ""
        logger.info(f"模式变更: current_mode={self._current_mode} cfg.mode={self._cfg.app.mode}")
        if hasattr(self, "window") and self.window is not None:
            self._apply_game_state(self._last_state)
            self._apply_waveform()

    def _set_output_waveform(self, channel, name, random_enabled=False,
                             random_min=30, random_max=50):
        """缓存波形配置，与下一个强度采样原子提交。"""
        if hasattr(self, "_desired_waveforms"):
            self._desired_waveforms[channel] = WaveformConfig(
                name, random_enabled, random_min, random_max)
        else:
            # 保留旧调用者和插件的同步兼容路径。
            setter = self.coyote.set_waveform_a if channel == "A" else self.coyote.set_waveform_b
            setter(name, random_enabled, random_min, random_max)

    def _select_coyote_device(self, slot_id):
        """将设备选择交给后台连接适配器。"""
        self.coyote.select_device(slot_id)

    def _show_connection_snapshot(self):
        snapshot = self.coyote.snapshot()
        key = (id(self.coyote), snapshot.session, snapshot.bound)
        previous = self._last_connection_session
        if key != previous:
            self._last_connection_session = key
            if previous is not None and (key[:2] != previous[:2] or not snapshot.bound):
                self._cancel_active_event("连接会话改变，丢弃旧事件输出")
            self._strength_sent = None
        panel = self.window.qr_widget
        panel.set_connection_snapshot(snapshot)
        self.window.status_bar.set_coyote_status(snapshot.bound, snapshot.address)
        if snapshot.qr_url != getattr(self, "_displayed_qr", ""):
            self._displayed_qr = snapshot.qr_url
            if snapshot.qr_url:
                self._generate_qr_image(snapshot.qr_url)
            else:
                panel.clear_qr_image()

    def _update_coyote_status(self):
        """同步郊狼状态到 UI"""
        if hasattr(self, "_connection_service"):
            self._show_connection_snapshot()
            return
        status = self.coyote.status
        if (self._running and self._coyote_started
                and not self._coyote_starting
                and not status.server_running):
            # 服务 / Relay 连接在运行中意外退出：5 秒后自动重启
            logger.warning(
                "郊狼连接服务意外停止（%s），5 秒后重启：%s",
                self._coyote_protocol, status.error or "无错误信息")
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
        catalog = getattr(self, "waveform_catalog", WaveformCatalog())
        if self._cfg.app.dglab_protocol == "v4":
            return CoyoteV4Controller(self._cfg.app.v4_relay_url, catalog)
        return CoyoteController(port=self._cfg.app.ws_port, catalog=catalog)

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
        old_controller = self.coyote
        old_controller.clear_all()
        # stop() 最长会阻塞约 6 秒，交给下一次启动线程先停旧再启新，
        # 既不卡 Qt 主线程，也保证旧服务释放端口后新服务才启动
        if not hasattr(self, "_connection_service"):
            self._retiring_controllers.append(old_controller)
        self._coyote_protocol = desired
        self._coyote_started = False
        self._coyote_starting = False
        self.coyote = self._create_coyote_controller()
        self._controllers.append(self.coyote)
        self.window.qr_widget.clear_qr_image()
        if hasattr(self, "_connection_service"):
            self._connection_service.replace(self.coyote)
        else:
            self.window.after(200, self._start_coyote)

    def _sync_overlay(self, mode: str, intensity_a: int, intensity_b: int):
        """同步数据到悬浮窗（按显示开关与数据有效性逐项显示）"""
        self._apply_overlay_settings()
        ov = self.overlay
        if not ov.visible:
            return

        # 当前输出波形名（控制器未就绪时显示恒定）
        coyote = getattr(self, "coyote", None)
        telemetry = getattr(coyote, "telemetry", None)
        wave_a = telemetry.snapshot("A").name if telemetry is not None else "恒定"
        wave_b = telemetry.snapshot("B").name if telemetry is not None else "恒定"

        last = self._last_state

        event_text = ""
        if self._event_remaining > 0:
            if self._event_kind == "repair":
                event_text = "🔧 维修中"
            elif self._event_kind == "kill":
                event_text = f"⚔ 击杀! ({self._event_remaining:.1f}s)"
            elif self._event_kind == "hit":
                event_text = f"🎯 被命中! ({self._event_remaining:.1f}s)"
            elif self._event_kind == "death":
                event_text = f"💀 坠毁! ({self._event_remaining:.1f}s)" if self._event_mode == "aircraft" else f"💀 被摧毁! ({self._event_remaining:.1f}s)"
        elif getattr(self, "_idle_active", False):
            event_text = "🛑 静止超时，请移动!"

        # 每种模式只显示其触发指标：空战/CAS 显示过载，陆战地面显示速度；
        # 未进对局或数据无效时显示 -- 占位，短暂无效沿用上次值防跳动
        g_text = ""
        speed_text = ""
        if mode == "aircraft" or last.vehicle_type == "aircraft":
            # 空战或陆战上飞机（CAS）：过载触发，清空速度缓存防跨上下文残留
            self._overlay_last_speed = ""
            if last.aircraft and last.aircraft.valid:
                g_text = f"{last.aircraft.gforce:.1f}"
                self._overlay_last_g = g_text
            elif self._overlay_last_g:
                g_text = self._overlay_last_g
            else:
                g_text = "--"
        elif mode == "tank":
            # 陆战地面：速度触发，清空过载缓存防跨上下文残留
            self._overlay_last_g = ""
            if last.tank and last.tank.valid:
                speed_text = f"{last.tank.speed_kmh:.0f}"
                self._overlay_last_speed = speed_text
            elif self._overlay_last_speed:
                speed_text = self._overlay_last_speed
            else:
                speed_text = "--"

        # 仅在值变化时更新（减少闪烁）
        ov.update_values(mode, g_text, speed_text, intensity_a, intensity_b,
                  wave_a, wave_b, event_text)

    def _overlay_content_flags(self) -> dict:
        """从配置读取悬浮窗显示项开关。"""
        app_cfg = self._cfg.app
        return {
            key: getattr(app_cfg, f"overlay_show_{key}")
            for key in OVERLAY_CONTENT_FLAGS
        }

    def _apply_overlay_content(self, flags: dict) -> None:
        """应用悬浮窗显示项开关：写配置 → 更新悬浮窗 → 持久化。"""
        app_cfg = self._cfg.app
        changed = False
        for key in OVERLAY_CONTENT_FLAGS:
            attr = f"overlay_show_{key}"
            value = bool(flags.get(key, True))
            if getattr(app_cfg, attr) != value:
                setattr(app_cfg, attr, value)
                changed = True
        self.overlay.set_content_flags(flags)
        if changed:
            self.config_mgr.save()

    def _open_overlay_content_dialog(self):
        """打开（或置顶并同步）悬浮窗显示内容设置对话框。"""
        dialog = self._overlay_content_dialog
        flags = self._overlay_content_flags()
        if dialog is None:
            dialog = OverlayContentDialog(
                flags,
                on_change=self._apply_overlay_content,
                parent=self.window,
            )
            self._overlay_content_dialog = dialog
        else:
            dialog.set_flags(flags)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _update_channel_wave_names(self):
        """把控制器记录的当前波形名同步到仪表盘 A/B 通道卡。"""
        coyote = getattr(self, "coyote", None)
        telemetry = getattr(coyote, "telemetry", None)
        if telemetry is None:
            return
        self.window.dashboard.channel_a.set_wave_name(
            telemetry.snapshot("A").name)
        self.window.dashboard.channel_b.set_wave_name(
            telemetry.snapshot("B").name)

    def _open_channel_scope(self, channel: str):
        """打开（或置顶）对应通道的输出电压曲线窗口。"""
        dialog = self._scope_dialogs.get(channel)
        if dialog is None:
            def telemetry_provider():
                return getattr(getattr(self, "coyote", None), "telemetry", None)

            def bound_provider():
                coyote = getattr(self, "coyote", None)
                status = getattr(coyote, "status", None)
                return bool(status and status.bound)

            dialog = ChannelScopeDialog(
                channel,
                telemetry_provider=telemetry_provider,
                bound_provider=bound_provider,
                parent=self.window,
            )
            self._scope_dialogs[channel] = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_overlay_settings(self):
        """立即应用悬浮窗开关和大小，并在变更时保存配置。"""
        ov = self.overlay
        want = self.window.dashboard.overlay_var.get()
        px = self.window.overlay_value_font
        changed = False

        if want != ov.visible:
            if want:
                ov.show()
            else:
                ov.hide()
            changed = True

        if px != ov.get_value_font():
            ov.set_value_font(px)
            changed = True

        if self._cfg.app.overlay_enabled != want:
            self._cfg.app.overlay_enabled = want
            changed = True
        if self._cfg.app.overlay_size_px != px:
            self._cfg.app.overlay_size_px = px
            changed = True
        if changed:
            # 字号滑条拖动时每个刻度都会进来：内存配置已更新，防抖后再写文件
            self._schedule_config_save()

    def _schedule_config_save(self) -> None:
        """停止变更 SAVE_DEBOUNCE_MS 毫秒后写入配置文件。"""
        timer = getattr(self, "_config_save_timer", None)
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(SAVE_DEBOUNCE_MS)
            timer.timeout.connect(self.config_mgr.save)
            self._config_save_timer = timer
        timer.start()

    def _on_overlay_value_font_changed(self, px: int):
        """悬浮窗右键滑块拖动时同步主窗口滑块（同步过程会自动应用并保存）。"""
        self.window.dashboard.set_overlay_value_font(px)

    def _apply_waveform(self):
        """根据当前模式同步波形设置到郊狼"""
        mode = self.window.get_mode()
        if mode == "aircraft":
            cfg = self._cfg.aircraft
        else:
            # 陆战模式先用坦克波形（后续会根据实际载具切 CAS）
            cfg = self._cfg.tank
        logger.info(f"同步波形: mode={mode} A={cfg.waveform_a} B={cfg.waveform_b}")
        self._set_normal_waveforms(cfg)

    def _set_normal_waveforms(self, cfg) -> None:
        """将常规波形及 A/B 独立随机配置发送给控制器。"""
        self._set_output_waveform("A", cfg.waveform_a, cfg.random_enabled_a,
                                   cfg.random_min_a, cfg.random_max_a)
        self._set_output_waveform("B", cfg.waveform_b, cfg.random_enabled_b,
                                   cfg.random_min_b, cfg.random_max_b)

    def _start_coyote(self):
        """启动当前协议控制器并生成对应 App 配对二维码。"""
        if not self._running:
            return
        if hasattr(self, "_connection_service"):
            self._connection_service.start()
            return
        if self._coyote_started or self._coyote_starting:
            return

        label = "V4 Relay" if self._coyote_protocol == "v4" else "V3 服务端"
        logger.info(f"正在启动郊狼 {label}...")
        self._coyote_starting = True
        controller = self.coyote
        retiring = getattr(self, "_retiring_controllers", [])
        self._retiring_controllers = []
        thread = threading.Thread(
            target=self._start_coyote_worker,
            args=(controller, label, retiring),
            daemon=True,
            name="郊狼连接启动",
        )
        self._start_workers = [worker for worker in self._start_workers
                               if worker.is_alive()]
        self._start_workers.append(thread)
        thread.start()

    def _start_coyote_worker(self, controller, label: str,
                             retiring=()) -> None:
        """在后台先停止旧控制器，再等待新控制器启动，避免阻塞 Qt 主线程。"""
        for old_controller in retiring:
            try:
                old_controller.stop()
            except Exception:
                logger.exception("停止旧郊狼控制器失败")
                mark_runtime_abnormal("停止旧郊狼控制器失败")
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
                    # 启动期间已切换协议：过期控制器在后台停止，不阻塞主线程
                    self._stop_controller_in_background(controller)
                    continue
                self._coyote_starting = False
                self._finish_coyote_start(label, success, url, error)
        except queue.Empty:
            pass

    def _stop_controller_in_background(self, controller) -> None:
        """在守护线程中停止控制器，并登记到退出时等待的线程列表。"""
        def stop_worker():
            try:
                controller.stop()
            except Exception:
                logger.exception("停止过期郊狼控制器失败")
                mark_runtime_abnormal("停止过期郊狼控制器失败")

        thread = threading.Thread(
            target=stop_worker, daemon=True, name="郊狼控制器停止")
        self._start_workers = [worker for worker in self._start_workers
                               if worker.is_alive()]
        self._start_workers.append(thread)
        thread.start()

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
        if not hasattr(self, "_strength_summary"):
            self._strength_summary = StrengthLogSummary()
        self._strength_summary.observe(value_a, value_b)
        reason = ""
        if value_a > 0 or value_b > 0:
            if not status.bound:
                reason = "目标强度非零，但郊狼未绑定，请手机扫码连接"
            elif not status.server_running:
                reason = "目标强度非零，但服务端未运行"
        if reason and reason != getattr(self, "_last_strength_warning", ""):
            logger.warning(reason)
        self._last_strength_warning = reason

        if hasattr(self, "_desired_waveforms"):
            active_event = self._event_remaining > 0
            source = (f"event:{self._output_revision}:{self._event_kind}"
                      if active_event else "normal")
            # 维修是由当前遥测续期的持续状态，其余事件使用绝对到期时间。
            deadline = (getattr(self, "_event_deadline", None)
                        if active_event and self._event_kind != "repair" else None)
            telemetry_deadline = getattr(self, "_last_telemetry_at", 0.0) + 1.0
            deadline = min(deadline, telemetry_deadline) if deadline is not None else telemetry_deadline
            self.coyote.submit_output(OutputIntent(
                ChannelTarget(value_a, self._desired_waveforms["A"]),
                ChannelTarget(value_b, self._desired_waveforms["B"]),
                source, deadline))
            return

        # 去重：值不变时每 STRENGTH_KEEPALIVE_S 秒才重发一次。
        # 控制器对象或绑定状态变化（重连 / 切换协议）后第一帧必定下发。
        now = time.monotonic()
        key = (id(self.coyote), status.bound, value_a, value_b)
        last = getattr(self, "_strength_sent", None)
        if (last is not None and last[0] == key
                and now - last[1] < self.STRENGTH_KEEPALIVE_S):
            return
        self._strength_sent = (key, now)
        self.coyote.set_strength_a(value_a)
        self.coyote.set_strength_b(value_b)


def main():
    """启动独立日志会话，只有明确完成正常退出时才删除自动文件。"""
    session = start_session()
    instance = None
    app = None
    normal = False
    try:
        logger.info("郊狼雷霆 %s 启动；日志：%s", APP_VERSION, session.path)
        # QApplication 先于单实例服务创建，保证本地 IPC 可以安全监听。
        qt_app = QApplication.instance() or QApplication(sys.argv)
        instance = SingleInstance()
        if not instance.acquire():
            logger.info("已有实例运行，已请求唤起主窗口")
            normal = True
            return
        app = App()
        instance.set_activate_callback(app.window.restore_from_tray)
        app.run()
        normal = app._shutdown_complete
    except BaseException:
        session.abnormal = True
        logger.critical("程序入口异常", exc_info=True)
        raise
    finally:
        if app is not None and not app._shutdown_started:
            # 非预期主循环退出也清理设备，但不追认成正常退出。
            try:
                app._on_close()
            except Exception:
                session.abnormal = True
                logger.exception("异常退出清理失败")
        try:
            if instance is not None:
                instance.close()
        except Exception:
            normal = False
            logger.exception("单实例资源清理失败")
        session.finish(normal=normal)


if __name__ == "__main__":
    main()
