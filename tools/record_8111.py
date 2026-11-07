"""只读记录战争雷霆 8111 原始响应；Ctrl+C 停止，不依赖项目运行环境。"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import math
from pathlib import Path
import signal
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener


ENDPOINTS = (
    "/state", "/indicators", "/map_info.json",
    "/hudmsg?lastEvt=0&lastDmg=0",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def timestamp():
    """返回带本地时区和毫秒的时间，便于对照程序日志。"""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def fetch(endpoint, timeout, base_url="http://127.0.0.1:8111"):
    """读取一次完整响应，保留 HTTP 错误正文和解析失败信息。"""
    started = time.monotonic()
    record = {
        "endpoint": endpoint, "started_at": timestamp(),
        "http_status": None, "raw_body": None, "data": None,
        "error": None,
    }
    body = None
    # 本地诊断请求不经过系统代理，每个工作线程使用独立 opener。
    opener = build_opener(ProxyHandler({}))
    try:
        try:
            response = opener.open(base_url + endpoint, timeout=timeout)
        except HTTPError as exc:
            response = exc
            record["error"] = f"HTTPError: {exc.code} {exc.reason}"
        with response:
            record["http_status"] = response.status
            record["headers"] = list(response.headers.items())
            body = response.read()
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    if body is not None:
        try:
            record["raw_body"] = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            # 非 UTF-8 响应仍保留原始字节，避免替换字符破坏证据。
            record["raw_body_base64"] = base64.b64encode(body).decode("ascii")
            record["parse_error"] = str(exc)
        else:
            try:
                record["data"] = json.loads(record["raw_body"])
            except ValueError as exc:
                record["parse_error"] = str(exc)
    record["finished_at"] = timestamp()
    record["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return record


class ConsoleSummary:
    """只压缩控制台输出，文件始终保存每次完整采样。"""

    def __init__(self):
        self._health = {}
        self._valid = {}
        self._hud = {}

    def show(self, record):
        """显示连接变化、对局有效状态和 HUD 新增／变化记录。"""
        endpoint = record["endpoint"]
        prefix = record["finished_at"]
        error = record.get("error") or record.get("parse_error")
        if error != self._health.get(endpoint):
            print(f"{prefix} {endpoint} {error or '读取恢复'}", flush=True)
        self._health[endpoint] = error
        data = record.get("data")
        if error or not isinstance(data, dict):
            return
        if "valid" in data:
            valid = data["valid"]
            if endpoint not in self._valid or self._valid[endpoint] != valid:
                print(f"{prefix} {endpoint} valid={valid}", flush=True)
                self._valid[endpoint] = valid
        if endpoint != ENDPOINTS[-1]:
            return
        for category in ("events", "damage"):
            records = data.get(category)
            if not isinstance(records, list):
                continue
            previous = self._hud.get(category)
            if previous is None:
                print(f"{prefix} HUD {category} 初始快照：{len(records)} 条"
                      "（不代表刚发生）", flush=True)
            else:
                for item in records:
                    if item in previous:
                        continue
                    same_id = isinstance(item, dict) and "id" in item and any(
                        isinstance(old, dict) and old.get("id") == item["id"]
                        for old in previous
                    )
                    label = "同 ID 内容变化" if same_id else "新增记录"
                    print(f"{prefix} HUD {category} {label}："
                          f"{json.dumps(item, ensure_ascii=False)}", flush=True)
                if len(records) < len(previous):
                    print(f"{prefix} HUD {category} 记录数减少："
                          f"{len(previous)} → {len(records)}", flush=True)
            self._hud[category] = records


def capture(output, interval=0.5, timeout=1.0, duration=None,
            base_url="http://127.0.0.1:8111", stop_event=None):
    """持续写入 JSONL；慢请求不重叠堆积，停止时收完当前批次。"""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = ConsoleSummary()
    stop_event = stop_event if stop_event is not None else threading.Event()
    deadline = None if duration is None else time.monotonic() + duration
    count = 0
    stopped = False
    # 独占创建，避免误覆盖之前的现场证据。
    with output.open("x", encoding="utf-8") as stream:
        print(f"记录文件：{output.resolve()}\n按 Ctrl+C 停止。", flush=True)
        with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
            batch = 0
            while deadline is None or time.monotonic() < deadline:
                if stop_event.is_set():
                    stopped = True
                    break
                cycle_started = time.monotonic()
                batch += 1
                pending = set()
                try:
                    for endpoint in ENDPOINTS:
                        pending.add(pool.submit(fetch, endpoint, timeout, base_url))
                    for future in as_completed(pending):
                        record = future.result()
                        record["batch"] = batch
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                        stream.flush()
                        pending.remove(future)
                        count += 1
                        summary.show(record)
                    delay = max(0, interval - (time.monotonic() - cycle_started))
                    if deadline is not None:
                        delay = min(delay, max(0, deadline - time.monotonic()))
                    if stop_event.wait(delay):
                        stopped = True
                        break
                except KeyboardInterrupt:
                    stopped = True
                    print("正在保存当前批次，请稍候……", flush=True)
                    for future in as_completed(pending):
                        record = future.result()
                        record["batch"] = batch
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                        stream.flush()
                        count += 1
                    break
    print(f"{'已停止' if stopped else '采样完成'}，共 {count} 条响应："
          f"{output.resolve()}", flush=True)
    return count


def positive_number(value):
    """验证命令行采样时间为有限正数。"""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必须是有限正数")
    return number


def main():
    """解析命令行并启动独立采集。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=positive_number, default=0.5,
                        help="采样间隔秒数，默认 0.5；慢请求完成后再开始下一批")
    parser.add_argument("--timeout", type=positive_number, default=1.0,
                        help="单次网络操作超时秒数，默认 1")
    parser.add_argument("--duration", type=positive_number,
                        help="采样秒数，省略则持续到 Ctrl+C")
    parser.add_argument("--output", type=Path, help="指定新建 JSONL 文件")
    args = parser.parse_args()
    output = args.output or PROJECT_ROOT / "logs" / (
        f"8111_capture_{datetime.now():%Y-%m-%d_%H%M%S_%f}.jsonl"
    )
    stop_event = threading.Event()
    # 信号仅请求停止，避免 Ctrl+C 在写入半行 JSON 时中断主线程。
    previous_handler = signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    try:
        capture(output, args.interval, args.timeout, args.duration,
                stop_event=stop_event)
    except OSError as exc:
        print(f"无法保存记录：{exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
