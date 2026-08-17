# 技术规格

## 技术栈

| 层次 | 技术 | 版本要求 | 用途 |
|------|------|----------|------|
| 语言 | Python | ≥3.11 | 主开发语言 |
| GUI | PySide6 | ≥6.7.0 | Qt 桌面框架，负责主窗口、悬浮窗和注意事项对话框 |
| HTTP | requests | ≥2.28.0 | 轮询 WT localhost:8111 |
| WebSocket | websockets | ≥12.0、<13.0 | V3 本机服务端与 V4 Relay 客户端 |
| QR码 | qrcode | ≥7.4.0 | 生成连接二维码 |
| 图像 | Pillow | ≥9.0.0 | QR 码图像处理 |
| 打包 | PyInstaller | latest | 打包为独立 .exe |

## 架构

```
main.py (入口)
    │
    ├── ConfigManager     — JSON 配置读写
    ├── MainWindow (GUI)  — PySide6 主窗口
    │   ├── StatusBar     — 连接状态指示
    │   ├── Dashboard     — 实时数据展示
    │   ├── SettingsPanel — 参数设置
    │   └── QRWidget      — QR 码展示
    ├── GameReader        — HTTP 轮询 WT 数据
    ├── MappingEngine     — 游戏数据 → 电击强度
    ├── CoyoteController  — V3 本机 WebSocket 服务端
    └── CoyoteV4Controller — V4 Relay 控制客户端
```

## 数据协议

### WT 8111 端口
- 端点：`http://localhost:8111/state`
- 方法：GET
- 格式：JSON
- 频率：默认 200ms 轮询
- 事件：`/hudmsg` 的 `damage` 记录没有结构化的击杀方和受害方字段，根据官方本地化词条解析 `msg`
- 语言：事件文本自动支持英语、俄语、法语、德语、简体中文、繁体中文和日文

### 郊狼 WebSocket 协议
- V3：电脑(服务端) ↔ 3.x App(客户端) ↔ 蓝牙 ↔ 郊狼，默认本机端口 `8765`
- V4：电脑(控制方) ↔ V4 Relay ↔ 4.x App(被控方) ↔ 蓝牙 ↔ 郊狼
- V4 官方控制方地址：`wss://trex.dungeon-lab.cn/v4`；自建 Relay 默认端口 `9998`
- V4 使用 `targetId` 配对，并通过 `clientId + slotId + channel` 定位设备通道
- 强度范围：0-200（整数）
- V4 关键消息：`hello`、`client_attached`、`devices.get`、`device.op`、`device.op.clear`

## 映射公式

线性插值：
```
if value <= min:     intensity = 0
elif value >= max:   intensity = max_intensity
else:                intensity = (value - min) / (max - min) * max_intensity
```
