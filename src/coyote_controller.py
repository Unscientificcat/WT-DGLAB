"""郊狼 3.0 控制模块 — 基于 PyDGLab-WS 库实现 WebSocket 服务端

架构：
    PC (本模块, WS Server) ←→ 手机 DG-LAB App (WS Client) ←→ 蓝牙 ←→ 郊狼 3.0

用法：
    controller = CoyoteController(port=8765)
    controller.start()           # 启动 WS 服务端
    url = controller.get_qrcode_url(ip)  # 获取二维码地址
    # ... 用户手机扫码 ...
    controller.set_strength_a(100)  # A 通道强度 0-200
    controller.set_strength_b(80)   # B 通道强度 0-200
    controller.stop()            # 停止服务
"""

import asyncio
import logging
import queue
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .waveforms import WaveformPlayer, ALL_WAVEFORMS, random_waveform_name

logger = logging.getLogger("CoyoteController")


# ============================================================
# 状态数据
# ============================================================

@dataclass
class CoyoteStatus:
    """郊狼连接状态"""
    server_running: bool = False      # WS 服务端是否运行中
    client_connected: bool = False    # 手机 App 是否已连接
    bound: bool = False               # 是否已绑定成功
    address: str = ""                 # WS 地址 (如 ws://192.168.1.5:8765)
    error: str = ""                   # 最近的错误信息


# ============================================================
# 控制器
# ============================================================

class CoyoteController:
    """郊狼 3.0 控制器（线程安全）

    在后台线程运行 asyncio 事件循环和 WebSocket 服务端。
    主线程通过同步方法发送命令。
    """

    def __init__(self, port: int = 8765):
        self._port = port
        self._status = CoyoteStatus()

        # 线程间通信
        self._cmd_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()

        # 后台线程
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

        # PyDGLab-WS 对象（在 asyncio 线程中创建）
        self._server = None
        self._client = None
        self._qr_url: str = ""

        # 脉冲状态追踪
        self._last_pulse_a: int = -1
        self._last_pulse_b: int = -1

        # 波形播放器
        self._player_a = WaveformPlayer("恒定")
        self._player_b = WaveformPlayer("恒定")
        self._random_tasks: dict = {}  # {"A": task, "B": task}

    # ============================================================
    # 公开 API（主线程调用）
    # ============================================================

    @property
    def status(self) -> CoyoteStatus:
        return self._status

    def start(self) -> bool:
        """启动 WebSocket 服务端（阻塞直到服务启动或超时）

        Returns:
            True 表示启动成功
        """
        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # 等待服务端就绪
        try:
            result = self._result_queue.get(timeout=10)
            return result is True
        except queue.Empty:
            self._status.error = "服务启动超时"
            return False

    def stop(self):
        """停止服务端"""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def get_qrcode_url(self, ip: str = "") -> str:
        """获取二维码 URL（由 PyDGLab-WS 客户端生成，非简单 ws:// 地址）

        调用前需确保 start() 已成功。
        """
        if not self._qr_url:
            # 客户端还没生成，用 ws 地址应急
            if ip:
                ws_uri = f"ws://{ip}:{self._port}"
            else:
                local_ip = self._get_local_ip()
                ws_uri = f"ws://{local_ip}:{self._port}"
            self._status.address = ws_uri
            return ws_uri

        self._status.address = self._qr_url
        return self._qr_url

    def set_strength_a(self, value: int):
        """设置 A 通道强度（0-200）"""
        self._send_cmd(("strength", "A", max(0, min(200, value))))

    def set_strength_b(self, value: int):
        """设置 B 通道强度（0-200）"""
        self._send_cmd(("strength", "B", max(0, min(200, value))))

    def clear_all(self):
        """将 A/B 通道强度都清零"""
        self.set_strength_a(0)
        self.set_strength_b(0)

    def set_waveform_a(self, name: str, random_interval: int = 30):
        """设置 A 通道波形"""
        self._send_cmd(("waveform", "A", name, random_interval))

    def set_waveform_b(self, name: str, random_interval: int = 30):
        """设置 B 通道波形"""
        self._send_cmd(("waveform", "B", name, random_interval))

    # ============================================================
    # 内部方法
    # ============================================================

    def _send_cmd(self, cmd: tuple):
        """向后台线程发送命令（非阻塞）"""
        if self._running:
            self._cmd_queue.put(cmd)

    @staticmethod
    def _get_local_ip() -> str:
        """获取本机局域网 IP 地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ============================================================
    # 后台事件循环
    # ============================================================

    def _run_loop(self):
        """后台线程：运行 asyncio 事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        try:
            loop.run_until_complete(self._async_main())
        except Exception as e:
            logger.error(f"后台线程异常: {e}")
            self._status.error = str(e)
        finally:
            self._status.server_running = False
            self._running = False
            loop.close()
            logger.info("郊狼服务端已停止")

    async def _async_main(self):
        """异步主函数 — 官方 Socket 协议流程"""
        try:
            from pydglab_ws import DGLabWSServer, RetCode, StrengthOperationType, Channel

            server = DGLabWSServer("0.0.0.0", self._port, heartbeat_interval=15)
            self._server = server

            async with server:
                self._status.server_running = True
                logger.info(f"WebSocket 服务端已启动，端口 {self._port}")

                # --- 绑定循环（断线后自动重连）---
                while self._running:
                    # 创建本地客户端
                    self._client = server.new_local_client()
                    self._status.client_connected = True
                    logger.info(f"本地客户端已创建: {self._client.client_id}")

                    # 生成 QR 码 URL
                    local_ip = self._get_local_ip()
                    ws_uri = f"ws://{local_ip}:{self._port}"
                    self._qr_url = self._client.get_qrcode(ws_uri)
                    logger.info(f"QR 码 URL: {self._qr_url}")

                    # 通知主线程就绪
                    while not self._result_queue.empty():
                        self._result_queue.get_nowait()
                    self._result_queue.put(True)

                    # 等待手机扫码绑定
                    logger.info("等待手机扫码绑定...")
                    self._status.error = ""
                    try:
                        ret = await self._client.bind()
                    except Exception as e:
                        logger.warning(f"绑定异常: {e}")
                        await asyncio.sleep(2)
                        continue

                    if ret != RetCode.SUCCESS:
                        logger.warning(f"绑定失败: {ret}")
                        await asyncio.sleep(2)
                        continue

                    self._status.bound = True
                    self._status.error = ""
                    logger.info(f"绑定成功! target_id={self._client.target_id}")

                    # 绑定后复位软上限：强度归零，防止残留值
                    await self._client.set_strength(
                        channel=Channel.A,
                        operation_type=StrengthOperationType.SET_TO,
                        value=0)
                    await self._client.set_strength(
                        channel=Channel.B,
                        operation_type=StrengthOperationType.SET_TO,
                        value=0)

                    # --- 并行运行：事件监听 + 命令处理 ---
                    stop_event = asyncio.Event()
                    listener = asyncio.create_task(
                        self._event_listener(stop_event))
                    processor = asyncio.create_task(
                        self._cmd_processor(stop_event))

                    # 等待 stop_event（断连信号）
                    await stop_event.wait()
                    # 取消两个任务
                    for task in [listener, processor]:
                        if not task.done():
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass

                    # 清理
                    self._status.bound = False
                    self._status.client_connected = False
                    self._last_pulse_a = -1
                    self._last_pulse_b = -1
                    logger.warning("郊狼连接已断开，自动等待重新扫码...")
                    await asyncio.sleep(1)

        except ImportError:
            self._status.error = "pydglab-ws 未安装"
            logger.error("pydglab-ws 未安装，请运行: pip install pydglab-ws")
            self._result_queue.put(False)
        except Exception as e:
            self._status.error = str(e)
            logger.error(f"服务端启动失败: {e}")
            try:
                self._result_queue.put(False)
            except Exception:
                pass

    async def _event_listener(self, stop_event: asyncio.Event):
        """监听 data_generator() — 主动感知断连"""
        from pydglab_ws import RetCode

        try:
            async for event in self._client.data_generator():
                if event == RetCode.CLIENT_DISCONNECTED:
                    logger.warning("手机 App 已断开连接")
                    stop_event.set()
                    return
            # data_generator 结束 = 连接已关闭，触发断连
            logger.warning("事件流结束，连接可能已关闭")
            stop_event.set()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"事件监听异常: {e}")
            stop_event.set()

    async def _cmd_processor(self, stop_event: asyncio.Event):
        """处理命令队列 — 向郊狼发送强度和波形"""
        from pydglab_ws import StrengthOperationType, Channel

        while not stop_event.is_set():
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            try:
                await self._exec_command(cmd)
            except Exception as e:
                err_msg = str(e)
                if "timeout" in err_msg.lower() or "keepalive" in err_msg.lower():
                    logger.warning("指令超时，连接可能已断开")
                    stop_event.set()
                    return
                else:
                    logger.error(f"指令失败: {cmd[0] if cmd else '?'}: {err_msg}")

    async def _exec_command(self, cmd: tuple):
        """执行单条命令"""
        from pydglab_ws import StrengthOperationType, Channel

        cmd_type = cmd[0]

        if cmd_type == "waveform":
            channel_str = cmd[1]
            name = cmd[2]
            interval = cmd[3] if len(cmd) > 3 else 30
            if name == "随机":
                name = random_waveform_name()
                # 启动该通道的随机切换任务
                if channel_str == "A":
                    self._start_channel_random("A", interval)
                else:
                    self._start_channel_random("B", interval)
            elif channel_str == "A":
                self._stop_channel_random("A")
            else:
                self._stop_channel_random("B")
            if channel_str == "A":
                self._player_a.set_waveform(name)
            else:
                self._player_b.set_waveform(name)
            return

        if cmd_type != "strength":
            return

        channel_str = cmd[1]
        value = cmd[2]
        channel = Channel.A if channel_str == "A" else Channel.B

        # 设置通道强度
        await self._client.set_strength(
            channel=channel,
            operation_type=StrengthOperationType.SET_TO,
            value=value
        )

        # 用波形播放器发送脉冲
        if value > 0:
            last = self._last_pulse_a if channel_str == "A" else self._last_pulse_b
            if value != last:
                await self._client.clear_pulses(channel)
            await self._send_waveform_pulse(channel, value)
            if channel_str == "A":
                self._last_pulse_a = value
            else:
                self._last_pulse_b = value
        else:
            await self._client.clear_pulses(channel)
            if channel_str == "A":
                self._last_pulse_a = 0
            else:
                self._last_pulse_b = 0

    async def _send_waveform_pulse(self, channel, strength: int):
        """从波形播放器取一条 pulse，按强度缩放后发送"""
        player = self._player_a if channel.name == "A" else self._player_b

        if player.is_constant:
            # 恒定模式：固定频率 + 均匀强度
            wave_strength = max(0, min(100, strength // 2))
            if wave_strength == 0:
                return
            if strength <= 50:
                freq = 10
            elif strength <= 100:
                freq = 15
            else:
                freq = 20
            pulse = ((freq, freq, freq, freq),
                     (wave_strength, wave_strength, wave_strength, wave_strength))
        else:
            # 波形预设模式：取预设的 pulse，按当前强度缩放波形强度
            pulse = player.next_pulse()
            if pulse is None:
                return
            freqs, strengths = pulse
            # 缩放波形强度 (0-100) 到目标强度比例
            scale = strength / 200.0
            scaled = tuple(max(0, min(100, int(s * scale))) for s in strengths)
            pulse = (freqs, scaled)

        pulses = tuple(pulse for _ in range(10))
        await self._client.add_pulses(channel, *pulses)

    def _start_channel_random(self, ch: str, interval: int):
        """启动单通道随机波形切换"""
        self._stop_channel_random(ch)
        task = asyncio.ensure_future(self._channel_random_loop(ch, interval))
        self._random_tasks[ch] = task

    def _stop_channel_random(self, ch: str):
        task = self._random_tasks.pop(ch, None)
        if task and not task.done():
            task.cancel()

    async def _channel_random_loop(self, ch: str, interval: int):
        """单通道随机波形切换循环"""
        player = self._player_a if ch == "A" else self._player_b
        while self._running:
            await asyncio.sleep(interval)
            new_name = random_waveform_name(
                player.current_name if not player.is_constant else None
            )
            player.set_waveform(new_name)
            logger.info(f"随机波形: 通道{ch} → {new_name}")
