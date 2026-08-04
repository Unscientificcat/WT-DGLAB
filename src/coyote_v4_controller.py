"""DG-LAB 4.x App V4 Socket 控制器。"""

import asyncio
import json
import logging
import queue
import random
import threading
import time
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import websockets

from .coyote_controller import CoyoteStatus
from .waveforms import WaveformPlayer, random_waveform_name


logger = logging.getLogger("CoyoteV4Controller")

DEFAULT_RELAY_URL = "wss://trex.dungeon-lab.cn/v4"
PAIRING_URL_PREFIX = "https://dungeon-lab.cn/s/?v=1&action=socket&url="
COYOTE_DEVICE_TYPES = {"COYOTE_020", "COYOTE_030"}


class CoyoteV4Controller:
    """通过 V4 Relay 控制 DG-LAB 4.x App 暴露的郊狼设备。"""

    def __init__(self, relay_url: str = DEFAULT_RELAY_URL):
        self._relay_url = self.normalize_relay_url(relay_url)
        self._status = CoyoteStatus()
        self._cmd_queue: queue.Queue = queue.Queue()
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
        self._request_counter = 0
        self._last_strength = {"A": 0, "B": 0}

        self._player_a = WaveformPlayer("恒定")
        self._player_b = WaveformPlayer("恒定")
        self._random_tasks: dict[str, asyncio.Task] = {}

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

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        try:
            return self._result_queue.get(timeout=12) is True
        except queue.Empty:
            self._status.error = "连接 V4 Relay 超时"
            self.stop()
            return False

    def stop(self) -> None:
        """停止 V4 控制器并关闭 Relay 连接。"""
        self._running = False
        loop = self._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_websocket(), loop)

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
        self.set_strength_a(0)
        self.set_strength_b(0)

    def set_waveform_a(self, name: str, random_interval: int = 30) -> None:
        """切换 A 通道波形。"""
        self._send_cmd(("waveform", "A", name, random_interval))

    def set_waveform_b(self, name: str, random_interval: int = 30) -> None:
        """切换 B 通道波形。"""
        self._send_cmd(("waveform", "B", name, random_interval))

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
    def pulse_to_hex(pulse, strength: int) -> str:
        """将项目波形帧转换为 V4 郊狼八字节十六进制帧。"""
        frequencies, amplitudes = pulse
        scale = CoyoteV4Controller._clamp_strength(strength) / 200.0
        values = [max(0, min(240, int(value))) for value in frequencies]
        values.extend(
            max(0, min(100, int(value * scale))) for value in amplitudes
        )
        return "".join(f"{value:02X}" for value in values)

    @staticmethod
    def _clamp_strength(value: int) -> int:
        """将强度限制在郊狼协议有效范围。"""
        return max(0, min(200, int(value)))

    def _send_cmd(self, command: tuple) -> None:
        """从任意线程向异步控制线程提交命令。"""
        if self._running:
            self._cmd_queue.put(command)

    def _run_loop(self) -> None:
        """在后台线程中运行 V4 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_main())
        except Exception as error:
            self._status.error = str(error)
            logger.error(f"V4 控制线程异常: {error}")
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

                self._status.server_running = True
                self._status.error = ""
                self._notify_start_result(True)

                processor = asyncio.create_task(self._command_loop())
                heartbeat = asyncio.create_task(self._heartbeat_loop())
                done, pending = await asyncio.wait(
                    {listener, processor, heartbeat},
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
            logger.error(f"V4 Relay 连接失败: {error}")
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

        devices = None
        if data.get("t") == "ev" and data.get("ev") == "devices.snapshot":
            devices = data.get("devices")
        elif data.get("t") == "resp":
            result = data.get("result")
            if isinstance(result, dict):
                devices = result.get("devices")
        elif data.get("t") == "ev" and data.get("ev") == "devices.patch":
            removed = data.get("removed") or []
            if self._slot_id in removed:
                self._detach_device("郊狼设备已断开", keep_client=True)
            devices = data.get("added")

        if isinstance(devices, list):
            await self._select_device(devices)

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

        self._slot_id = device["slotId"]
        self._device_name = str(device.get("name") or device.get("type"))
        self._last_strength = {"A": 0, "B": 0}
        await self._reset_channel("A")
        await self._reset_channel("B")
        self._status.bound = True
        self._status.address = f"V4 · {self._device_name}"
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
                logger.warning(f"V4 指令失败: {error}")

    async def _execute_command(self, command: tuple) -> None:
        """执行单条强度或波形命令。"""
        command_type = command[0]
        channel = command[1]
        if command_type == "waveform":
            name = command[2]
            interval = command[3] if len(command) > 3 else 30
            self._set_waveform(channel, name, interval)
            return
        if command_type != "strength" or not self._status.bound:
            return

        target = command[2]
        previous = self._last_strength[channel]
        if target != previous:
            if target == 0:
                await self._reset_channel(channel)
                await self._clear_channel(channel)
            else:
                await self._send_operation(channel, {
                    "t": 3,
                    "v": target - previous,
                    "im": True,
                })
            self._last_strength[channel] = target

        if target > 0:
            await self._send_waveform(channel, target)

    def _set_waveform(self, channel: str, name: str, interval: int) -> None:
        """更新本地波形播放器和随机切换任务。"""
        player = self._player_a if channel == "A" else self._player_b
        if name == "随机":
            player.set_waveform(random_waveform_name())
            self._start_random_task(channel, interval)
        else:
            self._stop_random_task(channel)
            player.set_waveform(name)

    async def _send_waveform(self, channel: str, strength: int) -> None:
        """下发一秒可立即替换的 V4 郊狼波形任务。"""
        player = self._player_a if channel == "A" else self._player_b
        if player.is_constant:
            frequency = 10 if strength <= 50 else 15 if strength <= 100 else 20
            pulse = (
                (frequency,) * 4,
                (100,) * 4,
            )
        else:
            pulse = player.next_pulse()
            if pulse is None:
                return
        frame = self.pulse_to_hex(pulse, strength)
        await self._send_operation(channel, {
            "t": 0,
            "d": 1000,
            "v": [frame] * 10,
            "im": True,
        })

    async def _reset_channel(self, channel: str) -> None:
        """将指定通道强度安全归零。"""
        await self._send_operation(channel, {"t": 7, "v": 0, "im": True})
        self._last_strength[channel] = 0

    async def _clear_channel(self, channel: str) -> None:
        """清理指定设备通道上的 V4 操作任务。"""
        if not self._client_id or not self._slot_id:
            return
        await self._send_request(
            self._client_id,
            "device.op.clear",
            {"s": self._slot_id, "c": self._channel_number(channel)},
        )

    async def _send_operation(self, channel: str, operation: dict) -> None:
        """向当前 App 和设备发送一条 device.op 请求。"""
        if not self._client_id or not self._slot_id:
            return
        payload = {
            "s": self._slot_id,
            "c": self._channel_number(channel),
            **operation,
        }
        await self._send_request(self._client_id, "device.op", payload)

    async def _send_request(self, client_id: str, method: str,
                            data=None) -> None:
        """发送符合官方 V4 RPC 格式的请求。"""
        request_id = self._next_request_id()
        request = {
            "t": "req",
            "reqId": request_id,
            "requestId": request_id,
            "m": method,
        }
        if data is not None:
            request["data"] = data
        await self._send_frame({
            "type": "message",
            "clientId": client_id,
            "data": request,
        })

    async def _send_frame(self, frame: dict) -> None:
        """将一条 JSON 外层帧发送到 Relay。"""
        if self._websocket is None:
            return
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
        try:
            if self._status.bound:
                await self._reset_channel("A")
                await self._reset_channel("B")
                await self._clear_channel("A")
                await self._clear_channel("B")
            if self._websocket is not None:
                await self._websocket.close()
        except Exception:
            pass

    def _detach_device(self, reason: str, keep_client: bool = False) -> None:
        """清除当前 App/设备选择及输出状态。"""
        self._slot_id = ""
        self._device_name = ""
        self._last_strength = {"A": 0, "B": 0}
        self._status.bound = False
        if not keep_client:
            self._client_id = ""
            self._status.client_connected = False
        self._status.address = reason
        logger.warning(reason)

    def _set_disconnected(self) -> None:
        """将所有 V4 连接状态重置为未连接。"""
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
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

    def _notify_start_result(self, result: bool) -> None:
        """仅向 start() 写入一次启动结果。"""
        if self._result_queue.empty():
            self._result_queue.put(result)

    def _next_request_id(self) -> str:
        """生成当前控制器内唯一的 V4 请求 ID。"""
        self._request_counter += 1
        return f"wt-{int(time.time() * 1000):x}-{self._request_counter:x}"

    @staticmethod
    def _channel_number(channel: str) -> int:
        """将项目通道名转换为 V4 通道编号。"""
        return 0 if channel == "A" else 1

    def _start_random_task(self, channel: str, interval: int) -> None:
        """启动指定通道的随机波形切换任务。"""
        self._stop_random_task(channel)
        self._random_tasks[channel] = asyncio.create_task(
            self._random_waveform_loop(channel, max(5, int(interval)))
        )

    def _stop_random_task(self, channel: str) -> None:
        """停止指定通道的随机波形切换任务。"""
        task = self._random_tasks.pop(channel, None)
        if task and not task.done():
            task.cancel()

    async def _random_waveform_loop(self, channel: str,
                                    interval: int) -> None:
        """定时为一个通道选择新的随机波形。"""
        player = self._player_a if channel == "A" else self._player_b
        while self._running:
            await asyncio.sleep(interval)
            player.set_waveform(random_waveform_name(player.current_name))
