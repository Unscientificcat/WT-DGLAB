"""采集、触发引擎与输出的后台运行服务；GUI 只读取快照。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import logging
import threading
import time

from .event_detector import EventDetector
from .dglab_state import OutputIntent
from .game_reader import GameState
from .trigger_engine import TriggerEngine
from .trigger_models import TriggerSnapshot


logger = logging.getLogger("GameRuntime")


class OutputDispatcher:
    """将完整业务结果交给当前连接，统一处理输出来源切换。"""

    def __init__(self):
        self._key = None
        self._allowed = False
        self._controller = None

    def dispatch(self, controller, snapshot):
        """先撤销旧来源，再提交新计划；不执行阻塞网络操作。"""
        intent = snapshot.intent
        if self._controller is not None and self._controller is not controller:
            self._controller.stop_output()
        self._controller = controller
        key = (id(controller), intent.expected_session, intent.source)
        if self._key != key or (self._allowed and not snapshot.output_allowed):
            controller.stop_output()
        self._key = key
        self._allowed = snapshot.output_allowed
        controller.submit_output(intent)


class GameRuntime:
    """单业务线程维护状态机，采集请求在另一个有界执行器中运行。"""

    TICK_SECONDS = 0.025

    def __init__(self, reader, controller, config, catalog=None, diagnostics=None):
        self.reader = reader
        self.detector = EventDetector(reader)
        self.engine = TriggerEngine(catalog)
        self.dispatcher = OutputDispatcher()
        self.diagnostics = diagnostics
        self._lock = threading.Lock()
        self._controller = controller
        self._config = deepcopy(config)
        self._published = TriggerSnapshot(GameState(), config.app.mode)

    def configure(self, config, controller=None):
        """从 GUI 原子发布一份配置副本，后台不读取正在编辑的配置。"""
        copy = deepcopy(config)
        with self._lock:
            self._config = copy
            if controller is not None:
                self._controller = controller

    def snapshot(self):
        """读取最新界面快照，界面不再消费或执行事件。"""
        with self._lock:
            return self._published

    def _context(self):
        with self._lock:
            return self._config, self._controller

    def process(self, state, config, now):
        """消费完整采集批次；入口也用于无网络的生产链路回放。"""
        context = state
        if (not state.vehicle_type and state.mission_status == "unknown"
                and self.engine.mode == config.app.mode):
            context = replace(state, vehicle_type=self.engine.recent_vehicle)
        events = self.detector.detect_records(
            context, config.app.mode, config.events, config.tank_events)
        self.engine.observe(state, events, config, now)
        if self.diagnostics:
            self.diagnostics.observe(state.link_ok)

    def advance(self, now=None):
        """运行一次后台时钟与输出提交，不访问任何 Qt 控件。"""
        now = time.monotonic() if now is None else now
        config, controller = self._context()
        if self.engine.mode != config.app.mode:
            self.engine.observe(GameState(mission_status="unknown"), (), config, now)
        connection = controller.snapshot()
        result = self.engine.tick(config, (id(controller), connection.session),
                                  connection.bound, now)
        self.dispatcher.dispatch(controller, result)
        with self._lock:
            self._published = result
        return result

    def run(self, stop_event):
        """运行采集和时钟，退出时释放 HTTP 线程池和旧输出。"""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="8111批次")
        pending = None
        next_poll = 0.0
        captured = None
        try:
            while not stop_event.is_set():
                now = time.monotonic()
                config, controller = self._context()
                if pending is not None and pending.done():
                    try:
                        state = pending.result()
                    except Exception:
                        logger.exception("8111 采集批次异常")
                        state = GameState(mission_status="unknown", sampled_at=now)
                    state.event_session, state.event_output_bound, poll_config = captured
                    # 配置场景变化期间到达的旧批次只更新 HUD 基线，不授予新场景输出。
                    if poll_config.app.mode != config.app.mode:
                        self.detector.detect_records(
                            state, poll_config.app.mode, poll_config.events,
                            poll_config.tank_events)
                    else:
                        self.process(state, config, now)
                    pending = None
                    next_poll = now + max(0.05, config.app.refresh_interval_ms / 1000)
                if pending is None and now >= next_poll:
                    connection = controller.snapshot()
                    captured = ((id(controller), connection.session), connection.bound, config)
                    pending = executor.submit(self.reader.collect)
                self.advance(now)
                stop_event.wait(self.TICK_SECONDS)
        except Exception:
            logger.exception("游戏业务线程异常，停止设备输出")
            with self._lock:
                self._published = replace(self._published, a=0, b=0,
                                          output_allowed=False, intent=OutputIntent(),
                                          diagnostic="游戏业务线程异常，已停止输出")
        finally:
            _, controller = self._context()
            controller.stop_output()
            executor.shutdown(wait=True, cancel_futures=True)
            self.reader.close()
