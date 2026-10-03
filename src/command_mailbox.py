"""最新命令邮箱 — 主线程与控制器事件循环之间的命令交接

同一 (命令类型, 通道) 只保留最新一条，替代无界 queue.Queue：
主线程每 100ms 提交一次强度，事件循环卡顿或断线时旧命令不会积压，
恢复后也不会回放过期强度。停止屏障优先，其后先波形再强度，
保证旧输出已停止，才切换波形并按新强度输出。
"""

import queue
import threading

# 取出顺序：数值越小越先取出
_TYPE_ORDER = {"stop": -1, "waveform": 0, "strength": 1}


class CommandMailbox:
    """线程安全的最新命令邮箱，接口与 queue.Queue 的非阻塞部分兼容。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[tuple, tuple] = {}

    @staticmethod
    def _key(command: tuple) -> tuple:
        """命令合并键：(类型, 通道)；缺少通道的命令按类型合并。"""
        return (command[0], command[1] if len(command) > 1 else None)

    def put(self, command: tuple) -> None:
        """提交命令，覆盖同一类型同一通道尚未执行的旧命令。"""
        key = self._key(command)
        with self._lock:
            # 先删除再插入，使覆盖后的命令排到同类命令末尾
            self._pending.pop(key, None)
            self._pending[key] = command

    def put_stop(self, channel: str, discard_waveform: bool = True) -> None:
        """提交不可被普通命令覆盖的通道停止屏障。"""
        with self._lock:
            for key in list(self._pending):
                if key[1] == channel and (key[0] == "strength"
                        or (discard_waveform and key[0] == "waveform")):
                    del self._pending[key]
            self._pending[("stop", channel)] = ("stop", channel)

    def has_stop(self, channel: str) -> bool:
        """检查在途操作之后是否必须先执行停止屏障。"""
        with self._lock:
            return ("stop", channel) in self._pending

    def get_nowait(self) -> tuple:
        """按停止、波形、强度顺序取出命令，无命令时抛出 queue.Empty。"""
        with self._lock:
            if not self._pending:
                raise queue.Empty
            key = min(
                self._pending,
                key=lambda item: _TYPE_ORDER.get(item[0], len(_TYPE_ORDER)),
            )
            return self._pending.pop(key)

    def drop(self, command_type: str) -> None:
        """丢弃指定类型的全部待执行命令（如断线时丢弃强度，保留波形配置）。"""
        with self._lock:
            for key in [key for key in self._pending if key[0] == command_type]:
                del self._pending[key]

    def clear(self) -> None:
        """丢弃全部待执行命令。"""
        with self._lock:
            self._pending.clear()

    def empty(self) -> bool:
        """返回是否没有待执行命令。"""
        with self._lock:
            return not self._pending

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)
