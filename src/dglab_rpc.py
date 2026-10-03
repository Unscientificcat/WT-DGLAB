"""V4 请求编码、关联响应与会话取消。"""

import asyncio
import logging
import time


logger = logging.getLogger(__name__)


class V4Rpc:
    """仅跟踪协议请求，不推断硬件输出结果。"""

    def __init__(self, send_frame):
        self._send = send_frame
        self.pending = {}
        self._counter = 0
        self.notifications = {}
        self.errors = []

    async def request(self, client_id, method, data, wait, timeout, session):
        """发送请求；超时不重发非幂等操作。"""
        self._counter += 1
        request_id = f"wt-{session}-{self._counter}"
        request = {"t": "req", "reqId": request_id, "m": method}
        if data is not None:
            request["data"] = data
        key = (client_id, request_id)
        future = asyncio.get_running_loop().create_future() if wait else None
        if future is not None:
            self.pending[key] = future
        else:
            self.notifications[key] = (session, method, data, time.monotonic())
        started = time.monotonic()
        if wait:
            logger.info("RPC 发送 session=%s req=%s method=%s data=%s", session, request_id, method, data)
        try:
            async with asyncio.timeout(timeout):
                await self._send({"type": "message", "clientId": client_id, "data": request})
                return await future if future is not None else None
        finally:
            self.pending.pop(key, None)
            if future is not None and not future.done():
                future.cancel()
            if wait:
                logger.info("RPC 等待结束 req=%s elapsed=%.3f", request_id, time.monotonic() - started)

    def resolve(self, client_id, response):
        """仅完成同一 App 的在途请求，忽略重复或旧响应。"""
        request_id = response.get("reqId") or response.get("requestId")
        if not isinstance(request_id, str):
            return False
        key = (client_id, request_id)
        future = self.pending.get(key)
        notification = self.notifications.pop(key, None)
        matched = notification is not None or (future is not None and not future.done())
        if notification is not None:
            result = response.get("result")
            reason = result.get("reason") if isinstance(result, dict) else None
            error = response.get("error")
            if error or (notification[1] == "device.op"
                         and reason not in {"completed", "cleared", "replaced", "cancelled"}):
                self.errors.append((notification, str(error or "波形响应格式无效")))
        if future is None or future.done():
            return matched
        logger.info("RPC 响应 req=%s result=%s error=%s", key[1], response.get("result"), response.get("error"))
        if response.get("error"):
            future.set_exception(RuntimeError(str(response["error"])))
        else:
            future.set_result(response.get("result"))
        return True

    def cancel(self):
        """会话结束时使所有请求立即失败。"""
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("V4 会话已结束"))
        self.pending.clear()
        self.notifications.clear()
        self.errors.clear()

    def collect_errors(self):
        """收集异步波形／设备请求错误；无响应不能无限增长。"""
        now = time.monotonic()
        for key, request in list(self.notifications.items()):
            if now - request[3] >= 3.0:
                self.notifications.pop(key, None)
                self.errors.append((request, "App 异步请求响应超时"))
        errors, self.errors = self.errors, []
        return errors
