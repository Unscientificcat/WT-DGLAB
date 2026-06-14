# 技术规格

## 技术栈

| 层次 | 技术 | 版本要求 | 用途 |
|------|------|----------|------|
| 语言 | Python | ≥3.11 | 主开发语言 |
| GUI | tkinter | Python 自带 | 标准库桌面框架，无需安装 |
| HTTP | requests | ≥2.28.0 | 轮询 WT localhost:8111 |
| WebSocket | websockets | ≥12.0 | 郊狼设备通信服务端 |
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
    └── CoyoteController  — WebSocket 服务端
```

## 数据协议

### WT 8111 端口
- 端点：`http://localhost:8111/state`
- 方法：GET
- 格式：JSON
- 频率：默认 200ms 轮询

### 郊狼 WebSocket 协议
- 架构：电脑(服务端) ↔ 手机 App(客户端) ↔ 蓝牙 ↔ 郊狼
- 端口：默认 8765
- 强度范围：0-200（整数）
- 关键消息：绑定、心跳、强度控制、波形

## 映射公式

线性插值：
```
if value <= min:     intensity = 0
elif value >= max:   intensity = max_intensity
else:                intensity = (value - min) / (max - min) * max_intensity
```
