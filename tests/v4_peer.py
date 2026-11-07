"""模拟 V4 App 的实际强度、波形与任务完成响应。"""

import asyncio
import json
import time


class V4Peer:
    """记录协议帧并执行任务，可注入延迟、丢包与错误响应。"""

    def __init__(self, controller):
        self.controller = controller
        self.messages = []
        self.strength = [0, 0]
        self.playing = [False, False]
        self.closed = False
        self.before_response = None
        self.drop = None
        self.error = None
        self.reason = "completed"
        self.drop_response = None
        self.response_sink = controller._handle_frame
        self.response_delay = None
        self.timeline = []
        self.tasks = set()

    async def send(self, message):
        """模拟任务完成后回复，波形请求本身不改变强度。"""
        frame = json.loads(message)
        self.messages.append(frame)
        request = frame.get("data", {})
        self.timeline.append(("send", time.monotonic(), request))
        if self.response_delay is not None:
            delay = (self.response_delay(request) if callable(self.response_delay)
                     else self.response_delay)
            task = asyncio.create_task(self._deliver(frame, delay))
            self.tasks.add(task)
            return
        await self._deliver(frame, 0)

    async def _deliver(self, frame, delay):
        """独立模拟请求到达、App 执行和响应返回；总延迟为一次往返。"""
        request = frame.get("data", {})
        if delay:
            await asyncio.sleep(delay / 2)
        method = request.get("m")
        data = request.get("data", {})
        if self.drop and self.drop(request):
            return
        channel = data.get("c", 0)
        self.timeline.append(("execute", time.monotonic(), request))
        if not self.error:
            if method == "device.op.clear":
                self.playing[channel] = False
            elif method == "device.op":
                kind = data["t"]
                if kind == 3:
                    self.strength[channel] = max(0, min(200, self.strength[channel] + data["v"]))
                elif kind == 7:
                    self.strength[channel] = data["v"]
                elif kind == 0:
                    self.playing[channel] = True
        if method not in {"device.op", "device.op.clear"}:
            return
        if self.before_response:
            await self.before_response(request)
        await asyncio.sleep(delay / 2)
        result = {} if method == "device.op.clear" else {"reason": self.reason}
        response = {"t": "resp", "reqId": request["reqId"], "result": result}
        if self.error:
            response["error"] = self.error
        if self.drop_response and self.drop_response(request):
            return
        self.timeline.append(("response", time.monotonic(), request))
        await self.response_sink({
            "type": "message", "clientId": frame["clientId"], "data": response,
        })

    async def wait_idle(self):
        """等待已发送请求完成，供测试清理所有独立响应任务。"""
        while self.tasks:
            tasks, self.tasks = self.tasks, set()
            await asyncio.gather(*tasks)

    async def close(self):
        """记录关闭操作。"""
        self.closed = True
        await self.wait_idle()
