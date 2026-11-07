"""8111 记录器的原始证据、异常恢复和停止行为验证。"""

from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools.record_8111 import ConsoleSummary, ENDPOINTS, capture, fetch


class RecorderTests(unittest.TestCase):
    """通过本机 HTTP 替身验证，不连接游戏或设备。"""

    @classmethod
    def setUpClass(cls):
        """启动可返回中文、HTTP 错误和慢响应的本机服务。"""
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                """构造不同网络响应。"""
                if self.path == "/slow":
                    time.sleep(0.15)
                body = '{"valid":true,"msg":"猫酱 击\u200b毁了 IT-1"}'
                if self.path == "/bad":
                    body = "服务暂不可用"
                self.send_response(503 if self.path == "/bad" else 200)
                self.end_headers()
                try:
                    self.wfile.write(body.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                """测试中不输出 HTTP 访问日志。"""

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        """释放本机服务。"""
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_raw_unicode_and_http_error(self):
        """正文不能丢失零宽字符，HTTP 失败也保留正文与状态。"""
        record = fetch("/state", 1, self.url)
        self.assertEqual(record["http_status"], 200)
        self.assertIn("击\u200b毁", record["raw_body"])
        self.assertEqual(json.loads(record["raw_body"]), record["data"])
        self.assertLessEqual(record["started_at"], record["finished_at"])
        bad = fetch("/bad", 1, self.url)
        self.assertEqual(bad["http_status"], 503)
        self.assertEqual(bad["raw_body"], "服务暂不可用")
        self.assertIn("HTTPError", bad["error"])
        self.assertIn("parse_error", bad)

    def test_timeout_then_recovery(self):
        """一次超时不会阻止下一次成功读取。"""
        failed = fetch("/slow", 0.02, self.url)
        self.assertIsNotNone(failed["error"])
        recovered = fetch("/state", 1, self.url)
        self.assertIsNone(recovered["error"])
        console = io.StringIO()
        summary = ConsoleSummary()
        failed["endpoint"] = "/state"
        with redirect_stdout(console):
            summary.show(failed)
            summary.show(recovered)
        self.assertIn("读取恢复", console.getvalue())

    def test_same_id_change_and_menu_transition(self):
        """同 ID 内容变化可见，进出对局不会清除 HUD 对比依据。"""
        summary = ConsoleSummary()
        console = io.StringIO()
        with redirect_stdout(console):
            for event_time, valid in ((12, True), (12, False), (6, True)):
                summary.show({"endpoint": "/map_info.json", "finished_at": "now",
                              "data": {"valid": valid}})
                summary.show({
                    "endpoint": ENDPOINTS[-1], "finished_at": "now",
                    "data": {"events": [], "damage": [
                        {"id": 17, "time": event_time, "msg": "击毁了 IT-1"}
                    ]},
                })
        text = console.getvalue()
        self.assertEqual(text.count("同 ID 内容变化"), 1)
        self.assertIn("valid=False", text)
        self.assertIn("初始快照", text)

    def test_capture_and_keyboard_stop_leave_readable_file(self):
        """停止后每行均能解析，保存完整端点与原始数值。"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.jsonl"
            stop_event = threading.Event()
            with redirect_stdout(io.StringIO()):
                with patch.object(stop_event, "wait", side_effect=KeyboardInterrupt):
                    count = capture(output, base_url=self.url, stop_event=stop_event)
            records = [json.loads(line) for line in output.read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual(count, 4)
            self.assertEqual({r["endpoint"] for r in records}, set(ENDPOINTS))
            self.assertTrue(all(r["data"]["valid"] for r in records))
            self.assertTrue(all("击\u200b毁" in r["raw_body"] for r in records))
            with self.assertRaises(FileExistsError):
                capture(output, duration=0.01, base_url=self.url)

    def test_requested_stop_saves_current_batch(self):
        """信号请求停止时收完当前响应，避免截断 JSON 行。"""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "stopped.jsonl"
            stop_event = threading.Event()
            with redirect_stdout(io.StringIO()):
                with patch.object(stop_event, "wait", return_value=True):
                    capture(output, base_url=self.url, stop_event=stop_event)
            records = [json.loads(line) for line in output.read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 4)


if __name__ == "__main__":
    unittest.main()
