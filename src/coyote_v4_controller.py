"""DG-LAB 4.x App V4 Socket 控制器。"""

import asyncio
import json
import logging
import math
from .runtime_logging import mark_runtime_abnormal
import queue
import random
import threading
import time
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import websockets

from .coyote_controller import CoyoteStatus
from .command_mailbox import CommandMailbox
from .output_runtime import OutputRuntime
from .dglab_devices import DeviceRegistry
from .dglab_rpc import V4Rpc
from .output_telemetry import OutputTelemetry
from .waveforms import WaveformCatalog, WaveformPlayer


logger = logging.getLogger("CoyoteV4Controller")

DEFAULT_RELAY_URL = "wss://trex.dungeon-lab.cn/v4"
PAIRING_URL_PREFIX = "https://dungeon-lab.cn/s/?v=1&action=socket&url="
COYOTE_DEVICE_TYPES = {"COYOTE_020", "COYOTE_030"}


class CoyoteV4Controller(OutputRuntime):
    """通过 V4 Relay 控制 DG-LAB 4.x App 暴露的郊狼设备。"""

    # 发出增量 / 归零后暂不信任 App 上报的时长（秒）
    CALIB_COOLDOWN_S = 1.0
    # 记录 slots.patch 上报间隔的条数上限（仅诊断）
    REPORT_INTERVAL_LOG_LIMIT = 10
    RPC_TIMEOUT_S = 1.0

    def __init__(self, relay_url: str = DEFAULT_RELAY_URL, catalog: WaveformCatalog | None = None):
        self._relay_url = self.normalize_relay_url(relay_url)
        self._status = CoyoteStatus()
        # 同一 (类型, 通道) 只保留最新命令，避免积压和回放过期强度
        self._cmd_queue = CommandMailbox()
        self._result_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._websocket = None
        self._ready_event = None

        self._target_id = ""
        self._client_id = ""
        self._slot_id = ""
        self._device_name = ""
        self._qr_url = ""
        self._output_lock = asyncio.Lock()
        self._needs_stop = {"A": False, "B": False}
        self._closing = False
        self._binding_task = None
        self._last_strength = {"A": 0, "B": 0}
        # App 实际上报仅作显示和持续偏差检测，与命令完成基准分开保存。
        self._app_strength = {"A": None, "B": None}
        self._slots_diag_logged = False
        # 闭环校准冷却：发出增量 / 归零后 CALIB_COOLDOWN_S 秒内，App 上报
        # 可能仍是发送前的旧值，仅暂存用于诊断，不在冷却结束后重用，
        # 避免以旧值重复计算增量造成超调（强度快速跳变时尤甚）。
        self._calib_block_until = {"A": 0.0, "B": 0.0}
        self._pending_report: dict[str, Optional[int]] = {"A": None, "B": None}
        # slots.patch 上报间隔诊断（供实机确认冷却时长是否合适）
        self._last_report_at: Optional[float] = None
        self._report_interval_logs = 0
        self._catalog = catalog or WaveformCatalog()
        self._catalog.reload()
        self._player_a = WaveformPlayer("恒定", self._catalog)
        self._player_b = WaveformPlayer("恒定", self._catalog)
        self._random_tasks: dict[str, asyncio.Task] = {}
        self._waveform_configs: dict[str, tuple] = {}

        # 输出遥测（波形名 + 下发批次），供界面显示当前波形和电压曲线
        self.telemetry = OutputTelemetry()
        self._init_output_runtime()
        self._stop_future = None
        self._rpc = V4Rpc(self._send_frame)
        self._pending_rpc = self._rpc.pending
        self._registry = DeviceRegistry()
        self._device_snapshots = ()
        self._preferred_slot = ""
        self._limits = {"A": None, "B": None}
        self._muted = {"A": False, "B": False}
        self._next_wave = {"A": 0.0, "B": 0.0}
        self._mismatch_count = {"A": 0, "B": 0}
        self._recoveries = {"A": 0, "B": 0}
        self._failures = {"A": 0, "B": 0}
        self._strength_failures = {"A": 0, "B": 0}
        self._faulted = {"A": False, "B": False}

    @property
    def status(self) -> CoyoteStatus:
        """返回当前 Relay、App 和设备连接状态。"""
        return self._status

    @property
    def relay_url(self) -> str:
        """返回规范化后的 V4 Relay 地址。"""
        return self._relay_url

    def start(self) -> bool:
        """连接 V4 Relay，并等待服务端返回控制方 ID。"""
        if self._running:
            return self._status.server_running

        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break
        self._stop_future = None
        self._runtime_state = "starting"
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        try:
            return self._result_queue.get(timeout=12) is True
        except queue.Empty:
            self._status.error = "连接 V4 Relay 超时"
            self.stop()
            return False

    def stop(self, wait: bool = True) -> None:
        """归零并停止 V4 控制器，可等待后台线程完成清理。"""
        # 清理期间必须保留消息循环，才能接收归零任务的完成响应。
        self._closing = True
        self._invalidate_output()
        loop = self._loop
        if loop and loop.is_running():
            with self._intent_lock:
                if self._stop_future is None:
                    self._stop_future = asyncio.run_coroutine_threadsafe(
                        self._close_websocket(), loop)
                future = self._stop_future
            if wait:
                try:
                    future.result(timeout=3)
                except Exception as error:
                    logger.warning(f"V4 停止清理未完成: {error}", exc_info=True)
                    mark_runtime_abnormal("V4 停止清理未完成")
        else:
            self._running = False
        if (wait and self._thread and self._thread.is_alive()
                and threading.current_thread() is not self._thread):
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                mark_runtime_abnormal("V4 控制线程未能停止")

    def get_qrcode_url(self, ip: str = "") -> str:
        """返回 DG-LAB 4 App 可识别的官方配对链接。"""
        del ip
        return self._qr_url

    def set_strength_a(self, value: int) -> None:
        """设置 A 通道目标强度，范围 0..200。"""
        self._send_cmd(("strength", "A", self._clamp_strength(value)))

    def set_strength_b(self, value: int) -> None:
        """设置 B 通道目标强度，范围 0..200。"""
        self._send_cmd(("strength", "B", self._clamp_strength(value)))

    def clear_all(self) -> None:
        """将 A/B 通道目标强度都归零。"""
        self.stop_output()

    def stop_output(self, channel: str | None = None) -> None:
        """提交单通道或双通道停止屏障，保留屏障之后的恢复命令。"""
        self._invalidate_output(channel)
        if self._running and not self._closing:
            for name in ((channel,) if channel else ("A", "B")):
                self._cmd_queue.put_stop(name)
                logger.info("V4 %s 提交停止屏障", name)

    def set_waveform_a(self, name: str, random_enabled: bool = False,
                       random_min: int = 30, random_max: int = 50) -> None:
        """切换 A 通道波形。"""
        self._send_cmd(("waveform", "A", name, bool(random_enabled), int(random_min), int(random_max)))

    def set_waveform_b(self, name: str, random_enabled: bool = False,
                       random_min: int = 30, random_max: int = 50) -> None:
        """切换 B 通道波形。"""
        self._send_cmd(("waveform", "B", name, bool(random_enabled), int(random_min), int(random_max)))

    @staticmethod
    def normalize_relay_url(relay_url: str) -> str:
        """校验并规范化 Relay WebSocket 地址。"""
        value = str(relay_url or "").strip() or DEFAULT_RELAY_URL
        parsed = urlsplit(value)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("V4 Relay 地址必须以 ws:// 或 wss:// 开头")
        return value

    @staticmethod
    def build_pairing_urls(relay_url: str, target_id: str) -> tuple[str, str]:
        """构建 App WebSocket 地址及官方跳转二维码地址。"""
        parsed = urlsplit(CoyoteV4Controller.normalize_relay_url(relay_url))
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["tid"] = target_id
        app_socket_url = urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        ))
        pairing_url = PAIRING_URL_PREFIX + quote(app_socket_url, safe="")
        return app_socket_url, pairing_url

    @staticmethod
    def scaled_amplitudes(pulse, strength: int) -> tuple[int, ...]:
        """将项目波形帧幅度按强度比例缩放为 0-100 的最终幅度。"""
        _frequencies, amplitudes = pulse
        scale = CoyoteV4Controller._clamp_strength(strength) / 200.0
        return tuple(
            max(0, min(100, int(value * scale))) for value in amplitudes
        )

    @staticmethod
    def pulse_to_hex(pulse, strength: int) -> str:
        """将项目波形帧转换为 V4 郊狼八字节十六进制帧。"""
        frequencies, _amplitudes = pulse
        values = [max(0, min(240, int(value))) for value in frequencies]
        values.extend(CoyoteV4Controller.scaled_amplitudes(pulse, strength))
        return "".join(f"{value:02X}" for value in values)

    @staticmethod
    def _clamp_strength(value: int) -> int:
        """将强度限制在郊狼协议有效范围。"""
        return max(0, min(200, int(value)))

    def _send_cmd(self, command: tuple) -> None:
        """从任意线程向异步控制线程提交命令。"""
        if self._running and not self._closing:
            if command[0] == "strength" and command[2] == 0:
                self._cmd_queue.put_stop(command[1], discard_waveform=False)
            else:
                self._cmd_queue.put(command)

    def _run_loop(self) -> None:
        """在后台线程中运行 V4 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._output_lock = asyncio.Lock()
        self._closing = False
        try:
            loop.run_until_complete(self._async_main())
        except Exception as error:
            self._status.error = str(error)
            logger.error(f"V4 控制线程异常: {error}", exc_info=True)
            mark_runtime_abnormal("V4 控制线程异常退出")
            self._notify_start_result(False)
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
            self._loop = None
            self._set_disconnected()
            self._running = False
            logger.info("V4 控制器已停止")

    async def _async_main(self) -> None:
        """连接 Relay 并并行处理入站消息、命令和心跳。"""
        self._new_session()
        self._runtime_state = "starting"
        logger.info(f"正在连接 V4 Relay: {self._relay_url}")
        try:
            async with websockets.connect(
                self._relay_url,
                open_timeout=8,
                close_timeout=2,
                ping_interval=None,
            ) as websocket:
                self._websocket = websocket
                self._ready_event = asyncio.Event()
                listener = asyncio.create_task(self._message_loop())
                try:
                    await asyncio.wait_for(self._ready_event.wait(), timeout=8)
                except TimeoutError as error:
                    raise RuntimeError("V4 Relay 未返回 hello") from error
                if not self._running or self._closing:
                    # 等待 hello 期间已调用 stop()：不再启动命令与心跳任务，
                    # 由 finally 统一复位状态
                    self._notify_start_result(False)
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
                    return

                self._status.server_running = True
                self._status.error = ""
                self._notify_start_result(True)

                processor = asyncio.create_task(self._command_loop())
                heartbeat = asyncio.create_task(self._heartbeat_loop())
                watchdog = asyncio.create_task(self._runtime_watchdog())
                feeder = asyncio.create_task(self._waveform_loop())
                done, pending = await asyncio.wait(
                    {listener, processor, heartbeat, watchdog, feeder},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    error = task.exception()
                    if error:
                        raise error
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._status.error = str(error)
            self._notify_start_result(False)
            logger.error(f"V4 Relay 连接失败: {error}", exc_info=True)
        finally:
            self._websocket = None
            self._set_disconnected()

    async def _message_loop(self) -> None:
        """持续接收并分派 V4 Relay 帧。"""
        async for raw_message in self._websocket:
            try:
                frame = json.loads(raw_message)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(frame, dict):
                continue
            await self._handle_frame(frame)

    async def _handle_frame(self, frame: dict) -> None:
        """处理一条 V4 Relay 外层帧。"""
        frame_type = frame.get("type")
        if frame_type == "hello":
            target_id = frame.get("clientId")
            if not isinstance(target_id, str) or not target_id:
                return
            self._runtime_state = "waiting_app"
            self._target_id = target_id
            _app_url, self._qr_url = self.build_pairing_urls(
                self._relay_url, target_id
            )
            self._status.address = self._relay_url
            if self._ready_event:
                self._ready_event.set()
            logger.info(f"V4 Relay 已连接，targetId={target_id}")
        elif frame_type == "client_attached":
            client_id = frame.get("clientId")
            if isinstance(client_id, str) and client_id:
                await self._attach_client(client_id)
        elif frame_type == "client_disconnected":
            if frame.get("clientId") == self._client_id:
                self._detach_device("DG-LAB 4 App 已断开")
        elif frame_type == "message":
            client_id = frame.get("clientId")
            if isinstance(client_id, str):
                await self._handle_app_data(client_id, frame.get("data"))
        elif frame_type == "idle_timeout":
            raise RuntimeError("V4 Relay 等待 App 超时")
        elif frame_type == "error":
            message = frame.get("message") or frame.get("code")
            self._status.error = str(message or "V4 Relay 返回错误")

    async def _attach_client(self, client_id: str) -> None:
        """选择首个 App 并请求其设备列表。"""
        if self._client_id and self._client_id != client_id:
            logger.info(f"忽略额外接入的 V4 App: {client_id}")
            return
        if self._client_id == client_id:
            return
        self._new_session()
        self._preferred_slot = ""
        self._registry.replace([])
        self._runtime_state = "waiting_device"
        self._client_id = client_id
        self._status.client_connected = True
        self._status.bound = False
        self._status.address = "V4 App 已接入，等待设备"
        await self._send_request(client_id, "devices.get")
        logger.info(f"V4 App 已接入: {client_id}")

    async def _handle_app_data(self, client_id: str, data) -> None:
        """处理 App 设备快照、增量变化和请求响应。"""
        if client_id != self._client_id or not isinstance(data, dict):
            return

        changed = False
        if data.get("t") == "resp":
            matched = self._rpc.resolve(client_id, data)
            result = data.get("result")
            if matched and isinstance(result, dict) and isinstance(result.get("devices"), list):
                self._registry.replace(result["devices"])
                changed = True
        elif data.get("t") == "ev":
            event = data.get("ev")
            if event == "devices.snapshot" and isinstance(data.get("devices"), list):
                self._registry.replace(data["devices"])
                changed = True
            elif event == "devices.patch":
                self._registry.patch(data.get("added") or [], data.get("removed") or [])
                changed = True
            elif event == "slots.patch":
                slots = data.get("slots") or []
                if isinstance(slots, list):
                    self._registry.patch_slots(slots)
                    self._absorb_slot_strength(slots)
                    changed = True
        if changed:
            await self._refresh_devices()

    async def _refresh_devices(self):
        self._device_snapshots = self._registry.snapshots()
        if self._slot_id:
            device = self._registry.devices.get(self._slot_id)
            if device is None or not self._registry.available(device):
                self._preferred_slot = self._slot_id
                self._detach_device("郊狼蓝牙设备已离线", keep_client=True)
                self._runtime_state = "waiting_device"
                return
            for channel in ("A", "B"):
                old_limit, old_muted = self._limits[channel], self._muted[channel]
                limit, muted = self._registry.channel(self._slot_id, channel)
                self._limits[channel], self._muted[channel] = limit, muted
                if (limit, muted) != (old_limit, old_muted):
                    self._needs_stop[channel] = True
                    self._cmd_queue.put_stop(channel)
                    self._queue_latest_target(channel)
            return
        available = [d for d in self._device_snapshots if d.available]
        if self._preferred_slot:
            preferred = [d for d in available if d.slot_id == self._preferred_slot]
            if not preferred:
                self._runtime_state = "waiting_selection" if available else "waiting_device"
                return
            available = preferred
        if len(available) == 1:
            await self._select_device([self._registry.devices[available[0].slot_id]])
        else:
            self._runtime_state = "waiting_selection" if available else "waiting_device"

    def select_device(self, slot_id: str) -> None:
        """异步选择设备，旧设备完成停止前不初始化新设备。"""
        if self._running and not self._closing:
            self._cmd_queue.put(("select", None, str(slot_id)))

    async def _switch_device(self, slot_id):
        device = self._registry.devices.get(slot_id)
        if device is None or not self._registry.available(device):
            return
        if slot_id == self._slot_id:
            return
        if self._slot_id:
            async with self._output_lock:
                errors = []
                for channel in ("A", "B"):
                    try:
                        await self._stop_channel(channel)
                    except Exception as error:
                        errors.append(error)
                if errors:
                    raise RuntimeError("旧设备停止未确认，无法切换")
        self._detach_device("切换设备", keep_client=True)
        self._preferred_slot = slot_id
        await self._select_device([device])

    def _absorb_slot_strength(self, slots) -> None:
        """从 App slots 增量中提取实际报告，不覆盖命令基准。"""
        if not isinstance(slots, list):
            return
        for slot in slots:
            if (not isinstance(slot, dict)
                    or slot.get("slotId") != self._slot_id):
                continue
            props = slot.get("props")
            if not isinstance(props, dict):
                continue
            if not self._slots_diag_logged:
                self._slots_diag_logged = True
                logger.info(
                    "V4 App 状态上报字段（一次性诊断）: %s", props)
            self._merge_reported_strength(props)

    def _merge_reported_strength(self, props: dict) -> None:
        """更新实际报告；冷却期外的连续偏差触发归零恢复。"""
        now = time.monotonic()
        self._log_report_interval(now)
        for channel, key in (("A", "intensityA"), ("B", "intensityB")):
            value = props.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not math.isfinite(value):
                continue
            value = int(max(0, min(200, value)))
            if value != self._app_strength[channel]:
                logger.info("App 强度上报 session=%s ch=%s value=%s baseline=%s",
                            self._session, channel, value, self._last_strength[channel])
            self._app_strength[channel] = value
            self._reported_at[channel] = now
            if self._needs_stop[channel] or now < self._calib_block_until[channel]:
                # 可能是发送前的旧值：暂存用于诊断，但不能因时间过去就信任它。
                self._pending_report[channel] = value
                continue
            self._pending_report[channel] = None
            if value == self._last_strength[channel]:
                self._mismatch_count[channel] = 0
                self._recoveries[channel] = 0
            else:
                self._mismatch_count[channel] += 1
                if self._mismatch_count[channel] >= 2:
                    self._mismatch_count[channel] = 0
                    self._recoveries[channel] += 1
                    self._needs_stop[channel] = True
                    self._cmd_queue.put_stop(channel)
                    if self._recoveries[channel] >= 3:
                        self._faulted[channel] = True
                        self._channel_errors[channel] = "App 强度持续偏离目标，通道已停止，请重新连接"
                    else:
                        self._queue_latest_target(channel)

    def _log_report_interval(self, now: float) -> None:
        """记录前若干次 slots.patch 上报间隔，供实机评估冷却时长。"""
        previous = self._last_report_at
        self._last_report_at = now
        if (previous is None
                or self._report_interval_logs >= self.REPORT_INTERVAL_LOG_LIMIT):
            return
        self._report_interval_logs += 1
        logger.info("V4 slots.patch 上报间隔: %.2f 秒", now - previous)

    def _begin_calib_cooldown(self, channel: str) -> None:
        """发出增量 / 归零后进入校准冷却期。"""
        self._calib_block_until[channel] = (
            time.monotonic() + self.CALIB_COOLDOWN_S)
        # 本次发送前的暂存上报相对新基准已过期
        self._pending_report[channel] = None

    def _reset_calib_state(self) -> None:
        """断线 / 解绑时清除校准冷却状态。"""
        self._calib_block_until = {"A": 0.0, "B": 0.0}
        self._pending_report = {"A": None, "B": None}

    async def _select_device(self, devices: list) -> None:
        """从设备列表中选择首个郊狼设备并执行安全归零。"""
        if self._slot_id:
            return
        device = next((
            item for item in devices
            if isinstance(item, dict)
            and item.get("type") in COYOTE_DEVICE_TYPES
            and isinstance(item.get("slotId"), str)
        ), None)
        if device is None:
            self._status.bound = False
            self._status.address = "V4 App 已接入，未发现郊狼"
            return

        self._new_session()
        self._faulted = {"A": False, "B": False}
        self._failures = {"A": 0, "B": 0}
        self._strength_failures = {"A": 0, "B": 0}
        self._recoveries = {"A": 0, "B": 0}
        self._mismatch_count = {"A": 0, "B": 0}
        self._limits = {ch: self._registry.channel(device["slotId"], ch)[0] for ch in ("A", "B")}
        self._muted = {ch: self._registry.channel(device["slotId"], ch)[1] for ch in ("A", "B")}
        self._runtime_state = "initializing"
        self._app_strength = {"A": None, "B": None}
        self._slot_id = device["slotId"]
        self._device_name = str(device.get("name") or device.get("type"))
        # 消息循环必须继续接收 RPC 响应，不能在监听协程内等待归零。
        self._binding_task = asyncio.create_task(self._initialize_device())

    async def _initialize_device(self) -> None:
        """清空旧任务并确认双通道归零后才允许业务输出。"""
        identity = (self._session, self._client_id, self._slot_id)
        try:
            async with self._output_lock:
                errors = []
                for channel in ("A", "B"):
                    try:
                        await self._stop_channel(channel)
                    except Exception as error:
                        errors.append(error)
                if errors:
                    raise RuntimeError(str(errors))
        except Exception as error:
            self._status.error = f"V4 绑定归零未确认: {error}"
            logger.warning(self._status.error, exc_info=True)
            if self._websocket is not None:
                await self._websocket.close()
            return
        if identity != (self._session, self._client_id, self._slot_id) or self._closing:
            return
        self._cmd_queue.drop("strength")
        self._last_strength = {"A": 0, "B": 0}
        self._status.bound = True
        self._status.address = f"V4 · {self._device_name}"
        self._publish_snapshot()
        logger.info(
            f"V4 郊狼已就绪: client={self._client_id} slot={self._slot_id}"
        )

    async def _command_loop(self) -> None:
        """顺序执行主线程提交的强度和波形命令。"""
        while self._running:
            try:
                command = self._cmd_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            try:
                await self._execute_command(command)
            except Exception as error:
                self._status.error = str(error)
                logger.warning(f"V4 指令失败: {error}", exc_info=True)
                if self._status.bound and command[0] in {"stop", "strength"}:
                    self._needs_stop[command[1]] = True
                    channel = command[1]
                    self._failures[channel] += 1
                    if self._failures[channel] < 3:
                        self._cmd_queue.put(("stop", channel))
                    else:
                        self._faulted[channel] = True
                        self._channel_errors[channel] = "停止未确认，请检查 App 并重新连接"
                await asyncio.sleep(0.1)

    async def _execute_command(self, command: tuple) -> None:
        """执行单条强度或波形命令。"""
        if command[0] == "reconcile":
            command = self._resolve_reconcile(command)
            if command is None:
                return
        if command[0] == "output":
            await self._execute_intent(command, self._execute_command)
            return
        if command[0] == "select":
            await self._switch_device(command[2])
            return
        async with self._output_lock:
            if not self._closing:
                await self._execute_locked(command)

    async def _execute_locked(self, command: tuple) -> None:
        """在同一输出锁内处理强度、停止和换波，防止随机任务插入。"""
        command_type = command[0]
        channel = command[1]
        if command_type == "stop":
            if self._status.bound:
                await self._stop_channel(channel)
                logger.info("V4 %s 通道停止屏障已执行", channel)
            return
        if command_type == "waveform":
            name = command[2]
            enabled = bool(command[3]) if len(command) > 3 else False
            minimum = int(command[4]) if len(command) > 4 else 30
            maximum = int(command[5]) if len(command) > 5 else minimum
            changed = self._set_waveform(channel, name, enabled, minimum, maximum)
            # 主线程对相同强度去重后不会再触发下发，切换波形需立即生效
            if (changed and not getattr(self, "_applying_intent", False)
                    and self._status.bound and self._last_strength[channel] > 0
                    and not self._needs_stop[channel]
                    and not self._cmd_queue.has_stop(channel)):
                await self._send_waveform(channel, self._last_strength[channel])
            return
        if command_type != "strength" or not self._status.bound:
            return

        self._targets[channel] = self._clamp_strength(command[2])
        limit = self._limits[channel]
        target = min(self._targets[channel], 200 if limit is None else limit)
        if self._muted[channel] or self._faulted[channel]:
            target = 0
        if target == 0:
            await self._stop_channel(channel)
            return
        if self._cmd_queue.has_stop(channel) or not self._output_allowed(channel):
            return
        if self._needs_stop[channel]:
            await self._stop_channel(channel)
        previous = self._last_strength[channel]
        if target != previous:
            # 增量必须收到完成响应后才能成为下一次运算基准。
            try:
                await self._send_operation(channel, {
                    "t": 3,
                    "v": target - previous,
                    "im": True,
                })
            except Exception:
                self._needs_stop[channel] = True
                self._strength_failures[channel] += 1
                if self._strength_failures[channel] >= 3:
                    self._faulted[channel] = True
                    self._channel_errors[channel] = "强度恢复连续失败，请检查 App 并重新连接"
                raise
            self._strength_failures[channel] = 0
            self._begin_calib_cooldown(channel)
            self._last_strength[channel] = target
            # App 上报保持独立，完成响应只更新命令基准。

        if (target > 0 and not self._cmd_queue.has_stop(channel)
                and self._output_allowed(channel)
                and (target != previous or getattr(self, "_applying_intent", False))):
            await self._send_waveform(channel, target)

    def _set_waveform(self, channel: str, name: str, enabled: bool = False,
                      minimum: int = 30, maximum: int = 50) -> bool:
        """更新本地波形播放器和随机切换任务，返回配置是否发生变化。"""
        config_key = (name, enabled, minimum, maximum)
        if self._waveform_configs.get(channel) == config_key:
            return False
        self._waveform_configs[channel] = config_key
        player = self._player_a if channel == "A" else self._player_b
        self._stop_random_task(channel)
        player.set_waveform(name)
        self.telemetry.record_waveform(channel, player.current_name)
        if enabled:
            self._start_random_task(channel, minimum, maximum)
        return True

    async def _send_waveform(self, channel: str, strength: int) -> None:
        """下发一秒可立即替换的 V4 郊狼波形任务。"""
        if not self._output_allowed(channel) or self._needs_stop[channel]:
            return
        player = self._player_a if channel == "A" else self._player_b
        started = time.monotonic()
        pulses = []
        for index in range(10):
            if player.is_constant:
                frequency = 10 if strength <= 50 else 15 if strength <= 100 else 20
                pulse = ((frequency,) * 4, (100,) * 4)
            else:
                pulse = player.pulse_at(started + index * 0.1)
            if pulse is not None:
                pulses.append(pulse)
        await self._send_operation(channel, {
            "t": 0, "d": 1000,
            "v": [self.pulse_to_hex(pulse, strength) for pulse in pulses], "im": True,
        })
        self._next_wave[channel] = started + 0.5
        self.telemetry.replace_future(channel, started)
        for index, pulse in enumerate(pulses):
            self.telemetry.record_pulse(channel, self.scaled_amplitudes(pulse, strength),
                                        strength, played_at=started + index * 0.1)

    async def _waveform_loop(self):
        """每 500ms 替换一秒连续波形窗口，不依赖主线程保活。"""
        while self._running:
            await asyncio.sleep(0.025)
            for (session, method, data, _at), error in self._rpc.collect_errors():
                if session != self._session or self._closing:
                    continue
                if method == "devices.get":
                    self._status.error = error
                    if self._websocket is not None:
                        await self._websocket.close()
                    continue
                channel = "A" if data.get("c") == 0 else "B"
                logger.warning("V4 异步任务失败 session=%s ch=%s error=%s", session, channel, error)
                self._channel_errors[channel] = error
                self._faulted[channel] = True
                self._needs_stop[channel] = True
                self._cmd_queue.put_stop(channel)
            for channel in ("A", "B"):
                if (self._status.bound and self._last_strength[channel] > 0
                        and time.monotonic() >= self._next_wave[channel]
                        and self._output_allowed(channel) and not self._faulted[channel]):
                    try:
                        async with self._output_lock:
                            if (self._output_allowed(channel) and not self._needs_stop[channel]
                                    and not self._cmd_queue.has_stop(channel)):
                                await self._send_waveform(channel, self._last_strength[channel])
                    except Exception as error:
                        self._needs_stop[channel] = True
                        self._channel_errors[channel] = str(error)
                        self._cmd_queue.put_stop(channel)

    async def _reset_channel(self, channel: str) -> None:
        """将指定通道强度安全归零。"""
        await self._send_operation(channel, {"t": 7, "v": 0, "im": True})
        self._last_strength[channel] = 0
        self._begin_calib_cooldown(channel)
        self.telemetry.record_silence(channel)

    async def _stop_channel(self, channel: str) -> None:
        """先清除旧任务，再确认绝对归零；失败时禁止恢复输出。"""
        self._needs_stop[channel] = True
        started = time.monotonic()
        baseline = self._last_strength[channel]
        self._last_strength[channel] = 0
        errors = []
        logger.info("V4 停止开始 session=%s ch=%s baseline=%s", self._session, channel, baseline)
        # clear 会取消未执行的 t:7，故绝不能在归零之后立即 clear。
        try:
            await self._clear_channel(channel)
        except Exception as error:
            logger.warning("V4 %s 清任务失败: %r", channel, error)
            errors.append(error)
        try:
            await self._reset_channel(channel)
        except Exception as error:
            logger.warning("V4 %s 绝对归零失败: %r", channel, error)
            errors.append(error)
        if errors:
            self._app_strength[channel] = None
            raise RuntimeError(f"V4 {channel} 停止未确认: {errors}")
        self._needs_stop[channel] = False
        self._failures[channel] = 0
        if not self._faulted[channel]:
            self._channel_errors[channel] = ""
        logger.info("V4 停止耗时 session=%s ch=%s elapsed=%.3f", self._session, channel, time.monotonic() - started)
        logger.info("V4 %s 停止完成: 原基准=%s，App 归零任务已确认", channel, baseline)

    async def _clear_channel(self, channel: str) -> None:
        """清理指定设备通道上的 V4 操作任务。"""
        if not self._client_id or not self._slot_id:
            raise ConnectionError("V4 App 或设备已断开")
        await self._send_request(
            self._client_id,
            "device.op.clear",
            {"s": self._slot_id, "c": self._channel_number(channel)},
            wait_response=True,
        )

    async def _send_operation(self, channel: str, operation: dict) -> None:
        """向当前 App 和设备发送一条 device.op 请求。"""
        if not self._client_id or not self._slot_id:
            raise ConnectionError("V4 App 或设备已断开")
        payload = {
            "s": self._slot_id,
            "c": self._channel_number(channel),
            **operation,
        }
        result = await self._send_request(
            self._client_id, "device.op", payload,
            wait_response=operation["t"] != 0)
        if operation["t"] != 0:
            if not isinstance(result, dict) or result.get("reason") != "completed":
                raise RuntimeError(f"V4 强度任务未完成: {result}")
            expected = {"type": operation["t"], "slotId": payload["s"], "channel": payload["c"]}
            if any(key in result and result[key] != value for key, value in expected.items()):
                raise RuntimeError(f"V4 响应设备、通道或类型不匹配: {result}")

    async def _send_request(self, client_id: str, method: str,
                            data=None, wait_response: bool = False):
        """发送符合官方 V4 RPC 格式的请求。"""
        session = self._session
        result = await self._rpc.request(client_id, method, data, wait_response,
                                         self.RPC_TIMEOUT_S, session)
        if session != self._session:
            raise ConnectionError("丢弃旧会话操作结果")
        return result

    async def _send_frame(self, frame: dict) -> None:
        """将一条 JSON 外层帧发送到 Relay。"""
        if self._websocket is None:
            raise ConnectionError("V4 WebSocket 已断开")
        await self._websocket.send(json.dumps(
            frame, ensure_ascii=False, separators=(",", ":")
        ))

    async def _heartbeat_loop(self) -> None:
        """按官方 SDK 周期向 V4 Relay 发送应用层 ping。"""
        while self._running:
            await asyncio.sleep(2)
            await self._send_frame({"type": "ping"})

    async def _close_websocket(self) -> None:
        """尽力归零后关闭当前 WebSocket。"""
        self._closing = True
        for channel in ("A", "B"):
            self._stop_random_task(channel)
        try:
            async with self._output_lock:
                if self._slot_id and self._client_id:
                    for channel in ("A", "B"):
                        try:
                            await self._stop_channel(channel)
                        except Exception:
                            logger.exception("V4 %s 退出归零未确认", channel)
                            mark_runtime_abnormal("V4 退出归零未确认")
        finally:
            try:
                if self._websocket is not None:
                    await self._websocket.close()
            finally:
                self._running = False

    def _reject_pending_rpc(self) -> None:
        """使断线会话的所有响应等待立即失败，禁止旧响应污染新会话。"""
        self._rpc.cancel()
        task = self._binding_task
        if task is not None and not task.done():
            task.cancel()
        self._binding_task = None
        for channel in ("A", "B"):
            self._stop_random_task(channel)

    def _detach_device(self, reason: str, keep_client: bool = False) -> None:
        """清除当前 App/设备选择及输出状态。"""
        self._reject_pending_rpc()
        self._new_session()
        self._cmd_queue.clear()
        self._waveform_configs.clear()
        self._needs_stop = {"A": False, "B": False}
        self._slot_id = ""
        self._device_name = ""
        self._last_strength = {"A": 0, "B": 0}
        self._app_strength = {"A": None, "B": None}
        self._reset_calib_state()
        self._status.bound = False
        self.telemetry.reset()
        if not keep_client:
            self._client_id = ""
            self._status.client_connected = False
        self._runtime_state = "waiting_device" if keep_client else "waiting_app"
        self._status.address = reason
        logger.warning(reason)

    def _set_disconnected(self) -> None:
        """将所有 V4 连接状态重置为未连接。"""
        self._reject_pending_rpc()
        self._new_session()
        self._registry.replace([])
        self._device_snapshots = ()
        self._runtime_state = "idle"
        self._needs_stop = {"A": False, "B": False}
        self._status.server_running = False
        self._status.bound = False
        self._status.client_connected = False
        self._status.address = ""
        self._target_id = ""
        self._client_id = ""
        self._slot_id = ""
        self._device_name = ""
        self._qr_url = ""
        self._last_strength = {"A": 0, "B": 0}
        self._app_strength = {"A": None, "B": None}
        self._reset_calib_state()
        self._waveform_configs.clear()
        self.telemetry.reset()
        self._cmd_queue.clear()
        self._publish_snapshot()

    def _notify_start_result(self, result: bool) -> None:
        """仅向 start() 写入一次启动结果。"""
        if self._result_queue.empty():
            self._result_queue.put(result)

    @staticmethod
    def _channel_number(channel: str) -> int:
        """将项目通道名转换为 V4 通道编号。"""
        return 0 if channel == "A" else 1

    def _start_random_task(self, channel: str, minimum: int, maximum: int) -> None:
        """启动指定通道的随机波形切换任务。"""
        self._stop_random_task(channel)
        self._random_tasks[channel] = asyncio.create_task(
            self._random_waveform_loop(channel, minimum, maximum)
        )

    def _stop_random_task(self, channel: str) -> None:
        """停止指定通道的随机波形切换任务。"""
        task = self._random_tasks.pop(channel, None)
        if task and not task.done():
            task.cancel()

    async def _random_waveform_loop(self, channel: str,
                                    minimum: int, maximum: int) -> None:
        """定时为一个通道选择新的随机波形。"""
        player = self._player_a if channel == "A" else self._player_b
        while self._running:
            await asyncio.sleep(random.uniform(max(5, minimum), max(maximum, minimum)))
            choices = [item for item in self._catalog.choices() if item != "恒定"]
            if choices:
                player.set_waveform(random.choice([item for item in choices if item != player.current_name] or choices))
                self.telemetry.record_waveform(channel, player.current_name)
                if self._status.bound and self._last_strength[channel] > 0:
                    try:
                        async with self._output_lock:
                            if (not self._closing and self._status.bound
                                    and not self._needs_stop[channel]
                                    and not self._cmd_queue.has_stop(channel)
                                    and self._last_strength[channel] > 0):
                                await self._send_waveform(
                                    channel, self._last_strength[channel])
                    except Exception as error:
                        logger.warning(f"V4 随机波形下发失败: {error}", exc_info=True)
