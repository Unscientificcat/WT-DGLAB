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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qrcode
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src.config_manager import ConfigManager
from src.game_runtime import GameRuntime
from src.game_reader import GameReader, GameState
from src.connection_service import ConnectionService
from src.coyote_controller import CoyoteController
from src.coyote_v4_controller import CoyoteV4Controller
from src.waveforms import WaveformCatalog
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

        self._event_kind = ""
        self._event_mode = ""
        self._event_remaining = 0.0
        self._idle_active = False
        self._view_snapshot = None
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

        # ===== 郊狼控制器 =====
        self._coyote_protocol = self._cfg.app.dglab_protocol
        self.coyote = self._create_coyote_controller()
        self._controllers.append(self.coyote)
        self._connection_service = ConnectionService(self.coyote)
        self._last_connection_session = None
        self.window.qr_widget.on_device_selected = self._select_coyote_device

        # ===== 线程间通信 =====
        self._game_runtime = GameRuntime(
            self.game_reader, self.coyote, self._cfg, self.waveform_catalog,
            self._connection_diagnostics)
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
        """后台服务独立维护业务时钟、采集和输出。"""
        self._game_runtime.run(self._stop_event)

    def _schedule_ui_refresh(self):
        """安排下一次 UI 刷新"""
        self.window.after(100, self._ui_tick)

    def _ui_tick(self):
        """只渲染后台快照，不在 Qt 定时器中计算或提交设备输出。"""
        try:
            self._update_coyote_status()
            self._render_trigger_snapshot(self._game_runtime.snapshot())
            self._update_channel_wave_names()
        except Exception:
            logger.exception("UI 刷新异常")
        finally:
            if self._running:
                self._schedule_ui_refresh()

    def _render_trigger_snapshot(self, result):
        """主窗口和悬浮窗显示同一个触发引擎结果。"""
        self._view_snapshot = result
        state, mode = result.game, result.mode
        self._last_state = state
        self._event_kind, self._event_mode = result.kind, result.event_mode
        self._event_remaining = result.remaining
        self._idle_active = result.kind == "idle"
        if state is not getattr(self, "_last_status_sample", None):
            self._last_status_sample = state
            if state.link_ok:
                self._wt_fail_count = 0
                self._wt_connected = True
            else:
                self._wt_fail_count += 1
                if self._wt_fail_count >= 3:
                    self._wt_connected = False
        self.window.status_bar.set_wt_status(self._wt_connected)
        dashboard = self.window.dashboard
        if result.kind and result.kind != "idle":
            dashboard.update_event(result.label, result.a, result.b)
        elif state.connected and state.vehicle_type == "aircraft" and state.aircraft:
            dashboard.update_aircraft(state.aircraft.gforce, result.a, result.b)
        elif state.connected and state.vehicle_type == "tank" and state.tank:
            dashboard.update_tank(state.tank.speed_kmh, result.a, result.b)
        else:
            dashboard.clear(mode)
        dashboard.show_event(result.label)
        dashboard.setToolTip(result.diagnostic)
        self._sync_overlay(mode, result.a, result.b)

    def _on_mode_switched(self):
        """保存设置后向后台发布配置，不在 GUI 中重算触发。"""
        if hasattr(self, "coyote"):
            self._switch_coyote_protocol_if_needed()
        self._current_mode = (self.window.get_mode() if self._window_ready
                              else self._cfg.app.mode)
        self._overlay_last_g = self._overlay_last_speed = ""
        if hasattr(self, "_game_runtime"):
            self._game_runtime.configure(self._cfg, self.coyote)

    def _select_coyote_device(self, slot_id):
        """将设备选择交给后台连接适配器。"""
        self.coyote.select_device(slot_id)

    def _show_connection_snapshot(self):
        snapshot = self.coyote.snapshot()
        key = (id(self.coyote), snapshot.session, snapshot.bound)
        previous = self._last_connection_session
        if key != previous:
            self._last_connection_session = key
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
            self.window.qr_widget.set_status("已连接")
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
                text = "连接异常，请查看运行日志"
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
        result = getattr(self, "_view_snapshot", None)
        if result is not None:
            event_text = result.label
            if result.kind:
                wave_a, wave_b = result.wave_a, result.wave_b

        # 每种模式只显示其触发指标：空战/CAS 显示过载，陆战地面显示速度；
        # 未进对局或数据无效时显示 -- 占位，短暂无效沿用上次值防跳动
        g_text = ""
        speed_text = ""
        if not last.connected:
            self._overlay_last_g = self._overlay_last_speed = ""
        if mode == "aircraft" or last.vehicle_type == "aircraft":
            # 空战或陆战上飞机（CAS）：过载触发，清空速度缓存防跨上下文残留
            self._overlay_last_speed = ""
            if last.connected and last.aircraft and last.aircraft.valid:
                g_text = f"{last.aircraft.gforce:.1f}"
                self._overlay_last_g = g_text
            elif self._overlay_last_g:
                g_text = self._overlay_last_g
            else:
                g_text = "--"
        elif mode == "tank":
            # 陆战地面：速度触发，清空过载缓存防跨上下文残留
            self._overlay_last_g = ""
            if last.connected and last.tank and last.tank.valid:
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
        """事件预览显示业务波形，其余显示适配器实际选择的波形。"""
        result = getattr(self, "_view_snapshot", None)
        if result is not None and result.kind:
            self.window.dashboard.channel_a.set_wave_name(result.wave_a)
            self.window.dashboard.channel_b.set_wave_name(result.wave_b)
            return
        coyote = getattr(self, "coyote", None)
        telemetry = getattr(coyote, "telemetry", None)
        if telemetry is None:
            return
        self.window.dashboard.channel_a.set_wave_name(
            telemetry.snapshot("A").name)
        self.window.dashboard.channel_b.set_wave_name(
            telemetry.snapshot("B").name)

    def _open_channel_scope(self, channel: str):
        """打开（或置顶）对应通道的输出强度曲线窗口。"""
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
        """兼容启动回调：波形设置随完整配置交给后台。"""
        if hasattr(self, "_game_runtime"):
            self._game_runtime.configure(self._cfg, self.coyote)

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
            self.window.qr_widget.set_status("连接服务启动失败，请查看运行日志")
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



def main():
    """启动独立日志会话，只有明确完成正常退出时才删除自动文件。"""
    session = start_session()
    instance = None
    app = None
    normal = False
    try:
        logger.info("郊狼雷霆 %s 启动；入口：%s；程序目录：%s；日志：%s",
                    APP_VERSION, sys.executable if getattr(sys, "frozen", False)
                    else os.path.abspath(__file__), _application_directory(), session.path)
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
