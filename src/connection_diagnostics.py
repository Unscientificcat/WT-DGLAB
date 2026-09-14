"""8111 连续失败后的只读后台诊断，不参与游戏数据或强度计算。"""

import csv
import io
import json
import logging
import subprocess
import sys
import threading
import time
from urllib.request import getproxies

import requests

from .runtime_paths import application_directory


logger = logging.getLogger("ConnectionDiagnostics")
DIAGNOSTIC_REVISION = "8111-diag-1"


class ConnectionDiagnostics:
    """连续三次失败后诊断，最多每分钟一次，独立于业务轮询线程。"""

    def __init__(self):
        self._failures = 0
        self._last_probe = float("-inf")
        self._worker = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        try:
            proxy_types = sorted(key for key in getproxies() if key != "no")
        except Exception:
            proxy_types = ["检测失败"]
        logger.info(
            "连接诊断版本=%s；运行方式=%s；程序目录=%s；解释器/EXE=%s；"
            "业务地址=http://127.0.0.1:8111/state；业务超时=0.5s；"
            "所有遥测请求 trust_env=False，禁用代理与重定向；"
            "系统/环境代理类型=%s（仅检测存在性，不代表请求经过代理）",
            DIAGNOSTIC_REVISION, "EXE" if getattr(sys, "frozen", False) else "源码",
            application_directory(), sys.executable, proxy_types or "未发现")

    def observe(self, link_ok: bool) -> None:
        """接收业务连接状态，按次数及冷却时间安排独立探测。"""
        with self._lock:
            self._failures = 0 if link_ok else self._failures + 1
            if (self._stop.is_set() or self._failures < 3
                    or time.monotonic() - self._last_probe < 60
                    or (self._worker is not None and self._worker.is_alive())):
                return
            self._last_probe = time.monotonic()
            try:
                self._worker = threading.Thread(target=self._probe, name="8111连接诊断", daemon=True)
                self._worker.start()
            except Exception:
                self._worker = None
                logger.exception("无法启动后台诊断，业务轮询继续")

    def stop(self) -> bool:
        """取消后续探测并等待已有任务；返回是否已结束。"""
        with self._lock:
            self._stop.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=5)
            return not worker.is_alive()
        return True

    def _probe_http(self, session, path):
        url = "http://127.0.0.1:8111" + path
        started = time.monotonic()
        try:
            with session.get(url, timeout=(2, 2), allow_redirects=False, stream=True) as response:
                # 只读取有限内容进行格式识别，不记录完整页面或玩家信息。
                body = bytearray()
                for chunk in response.iter_content(1024):
                    if self._stop.is_set():
                        return False
                    body.extend(chunk)
                    if len(body) >= 8192:
                        break
                elapsed = (time.monotonic() - started) * 1000
                kind = "首页内容"
                valid = response.status_code == 200
                if path == "/state":
                    try:
                        data = json.loads(body)
                        kind = f"JSON 类型={type(data).__name__}"
                        valid = valid and isinstance(data, dict)
                        if isinstance(data, dict):
                            flag = data.get("valid")
                            kind += f"；valid={flag if isinstance(flag, bool) else '非布尔值或未提供'}"
                    except (ValueError, UnicodeError):
                        kind = "内容非完整 JSON（或超过8KiB诊断上限）"
                        valid = False
                logger.info("后台直连探测：%s；HTTP=%s；Content-Type=%s；"
                            "总耗时=%.0fms；连接/读取超时各2s；%s",
                            url, response.status_code, response.headers.get("Content-Type", "未提供"),
                            elapsed, kind)
                return valid
        except requests.RequestException as error:
            logger.warning("后台直连探测失败：%s；耗时=%.0fms；%s: %s；"
                           "错误不能单独证明防火墙拦截",
                           url, (time.monotonic() - started) * 1000,
                           type(error).__name__, error)
            return False

    def _listener_info(self) -> None:
        if sys.platform != "win32" or self._stop.is_set():
            return
        options = dict(capture_output=True, text=True, errors="replace", timeout=2,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        result = subprocess.run(["netstat", "-ano", "-p", "tcp"], **options)
        if result.returncode:
            logger.warning("8111 监听进程检测失败：netstat 返回 %s", result.returncode)
            return
        listeners = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
                if parts[1].rsplit(":", 1)[-1] == "8111" and parts[4].isdigit():
                    listeners.append((parts[1], parts[4]))
        if not listeners:
            logger.warning("采样时未发现 TCP 8111 监听；检查游戏服务是否启动或暂时退出")
        names = {}
        for address, pid in listeners[:8]:
            if self._stop.is_set():
                return
            if pid not in names:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], **options)
                rows = list(csv.reader(io.StringIO(result.stdout)))
                names[pid] = next((row[0] for row in rows if len(row) > 1 and row[1] == pid),
                                  "进程已退出或查询受限")
            logger.info("8111 监听证据：地址=%s；PID=%s；进程=%s；"
                        "若不是实际游戏进程，请检查端口占用；这是采样证据而非根因判定",
                        address, pid, names[pid])

    def _probe(self) -> None:
        try:
            logger.info("连续三次连接失败，开始后台诊断（不改变连接灯或设备输出）")
            with requests.Session() as session:
                session.trust_env = False
                session.proxies = {"http": None, "https": None}
                root_ok = self._probe_http(session, "/")
                if self._stop.is_set():
                    return
                state_ok = self._probe_http(session, "/state")
            if self._stop.is_set():
                return
            if root_ok and not state_ok:
                logger.warning("首页可达但 /state 不可用：浏览器首页成功不能代替遥测接口验证")
            elif state_ok:
                logger.info("后台 /state 在更长超时下可用：对照业务耗时检查0.5s超时、"
                            "瞬时恢复、数据解析或UI异常；不能仅据本次探测认定超时是根因")
            else:
                logger.warning("后台直连仍失败：结合监听进程与错误码，检查服务、"
                               "安全软件按进程拦截；确认浏览器和程序在同一电脑与同一时刻测试")
            self._listener_info()
        except Exception:
            logger.exception("后台连接诊断未完成，不影响业务轮询")
