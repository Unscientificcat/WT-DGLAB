"""官方 V4 设备快照与属性增量合并。"""

import math

from .dglab_state import DeviceSnapshot


class DeviceRegistry:
    """维护设备槽位；蓝牙断开不等同于 App 断开。"""

    def __init__(self):
        self.devices = {}

    def replace(self, devices):
        """替换完整快照。"""
        self.devices.clear()
        self.patch(devices, ())

    def patch(self, added, removed):
        """合并设备新增与移除。"""
        if not isinstance(removed, list) and not isinstance(removed, tuple):
            removed = ()
        if not isinstance(added, list) and not isinstance(added, tuple):
            added = ()
        for slot in removed:
            if isinstance(slot, str):
                self.devices.pop(slot, None)
        for item in added:
            if isinstance(item, dict) and isinstance(item.get("slotId"), str):
                normalized = dict(item)
                for field in ("props", "slotState"):
                    if not isinstance(normalized.get(field), dict):
                        normalized[field] = {}
                self.devices[item["slotId"]] = normalized

    def patch_slots(self, slots):
        """属性支持嵌套对象与官方点分键，保留未更新字段。"""
        for item in slots:
            if not isinstance(item, dict):
                continue
            slot_id = item.get("slotId")
            if not isinstance(slot_id, str):
                continue
            device = self.devices.get(slot_id)
            if device is None:
                continue
            for field in ("props", "slotState"):
                patch = item.get(field)
                if isinstance(patch, dict):
                    device[field] = self._merge(device.get(field, {}), patch)

    @classmethod
    def _merge(cls, old, patch):
        result = dict(old) if isinstance(old, dict) else {}
        for key, value in patch.items():
            result[key] = cls._merge(result.get(key), value) if isinstance(value, dict) else value
        return result

    @staticmethod
    def available(device):
        """明确的离线标志优先；旧 App 未提供标志时保留描述符兼容。"""
        return (device.get("slotState", {}).get("hasDevice") is not False
                and device.get("props", {}).get("connectState") != "disconnected")

    def snapshots(self):
        """返回受支持的候选设备，不包含可变属性字典。"""
        return tuple(DeviceSnapshot(slot, str(item.get("name") or item["type"]),
                                    self.available(item))
                     for slot, item in self.devices.items()
                     if item.get("type") in {"COYOTE_020", "COYOTE_030"})

    def channel(self, slot, channel):
        """解析通道上限与静音；未知上限保持 None。"""
        props = self.devices.get(slot, {}).get("props", {})
        prefix = "channel" + channel
        nested = props.get(prefix, {})
        if not isinstance(nested, dict):
            nested = {}
        limit = props.get(prefix + ".intensityMax", nested.get("intensityMax"))
        if (isinstance(limit, (int, float)) and not isinstance(limit, bool)
                and math.isfinite(limit)):
            limit = max(0, min(200, int(limit)))
        else:
            limit = None
        muted = props.get(prefix + ".isMuted", nested.get("isMuted")) is True
        return limit, muted
