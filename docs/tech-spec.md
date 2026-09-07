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
| 打包 | PyInstaller | latest | `--onedir` 目录包并压缩为 ZIP |

## 架构

```
main.py (入口)
    │
    ├── ConfigManager     — JSON 配置读写
    ├── MainWindow (GUI)  — PySide6 主窗口
    │   ├── StatusBar     — 连接状态指示
    │   ├── Dashboard     — 实时数据展示（通道卡点击打开曲线窗口）
    │   ├── SettingsPanel — 参数设置
    │   ├── OverlayContentDialog — 悬浮窗显示内容设置
    │   └── QRWidget      — QR 码展示
    ├── GameReader        — HTTP 轮询 WT 数据
    ├── MappingEngine     — 游戏数据 → 电击强度
    ├── CoyoteController  — V3 本机 WebSocket 服务端
    ├── CoyoteV4Controller — V4 Relay 控制客户端
    │   └── OutputTelemetry — 线程安全输出遥测（波形名 + 下发批次）
    ├── OverlayWindow     — 悬浮窗（显示项可开关）
    └── ChannelScopeDialog — 单通道输出电压曲线窗口

### 输出遥测层

`src/output_telemetry.py` 的 `OutputTelemetry` 由 V3/V4 控制器各持有一个实例：控制器的 asyncio 线程在波形切换（含随机换波）时调用 `record_waveform`、每次下发波形批次时调用 `record_pulse`（记录 4 个 25ms 采样点的最终幅度字节 0-100 与当前强度）、强度归零时调用 `record_silence`；Qt 主线程通过 `snapshot()` 加锁读取快照，用于界面显示当前波形名和输出电压曲线。电压换算：曲线值 = 最终幅度字节 × 2（0-200，与强度条同刻度），恒定波形即为位于当前强度的平线。

`src/gui/waveform_scope.py` 的 `WaveformScope` 按批次真实时间间隔平铺采样点绘制最近约 6 秒滚动曲线（最新批次超过 0.6s 无更新视为输出停止）；`ChannelScopeDialog` 为单通道非模态窗口，按通道单例管理，100ms 自刷新。

悬浮窗显示项由 `overlay_show_*` 配置开关控制（`src/gui/overlay.py` 的 `OVERLAY_CONTENT_FLAGS`）：模式、实时过载、实时速度、事件提示、A/B 通道强度、A/B 通道波形名，共 8 项默认全开；过载/速度行的可见性 = 开关 且 该指标本轮有数据。

### 波形资源层

`src/waveforms.py` 的 `WaveformCatalog` 管理 EXE 同级 `waveforms` 目录，启动和手动刷新时仅扫描根目录 `*.pulse`。解析器支持官方明文 `Dungeonlab+pulse:`、多 section、速度 `1/2/4`、频率模式与休止时间，输出统一的 `(4 字节频率, 4 字节强度)` Pulse 元组。V3 和 V4 均使用该 8 字节帧，恒定波形由播放器按当前强度生成。

常规配置保存 `random_enabled_a/b` 与 `random_min/max_a/b`；事件配置保存各事件的 `*_random_a/b`。旧预设名和 `random_interval` 在加载时迁移为恒定及 A/B 范围。

### 发布目录

发布版为免安装目录包：EXE 与 PyInstaller 依赖位于 `_internal/`，图标和注意事项位于外部 `resources/`，安全模板为 `config.default.json`。用户配置只写入 EXE 同目录的 `config.json`；新版本不自动迁移旧目录配置。构建脚本同时生成可运行目录和同名 ZIP。
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
