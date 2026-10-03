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

`src/output_telemetry.py` 的 `OutputTelemetry` 由 V3/V4 控制器各持有一个实例：控制器的 asyncio 线程在波形切换（含随机换波）时调用 `record_waveform`、每次下发波形批次时调用 `record_pulse`（记录 4 个 25ms 采样点的最终幅度字节 0-100、强度及预计播放时刻）、强度归零时调用 `record_silence`；Qt 主线程通过 `snapshot()` 加锁读取快照，用于界面显示当前波形名和输出电压曲线。电压换算：曲线值 = 最终幅度字节 × 2（0-200，与强度条同刻度），恒定波形即为位于当前强度的平线。

`src/gui/waveform_scope.py` 的 `WaveformScope` 按预计播放时刻平铺采样点绘制最近约 6 秒滚动曲线（最新批次超过 0.6s 无更新视为输出停止）；`ChannelScopeDialog` 为单通道非模态窗口，按通道单例管理，100ms 自刷新。

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

触发曲线（阶段10-1 起，归一化比例 t∈[0,1] 先经曲线变换再乘通道上限；k 为陡度参数）：
```
linear（线性）: t' = t
exp（指数）:    t' = (e^(k·t) − 1) / (e^k − 1)     # 低值段温和、高值段陡增
log（对数）:    t' = ln(1 + k·t) / ln(1 + k)       # 低值段明显、高值段平缓
```
- 三种曲线均满足 f(0)=0、f(1)=1 且单调递增；k 有效范围 1.5~4.0（配置校验 1.0~6.0）
- 未知曲线名或非法陡度回退线性；`curve` 键存于 `aircraft`/`tank`/`cas` 三段，逐段独立生效

## 事件判定规则

击杀/被击毁/坠毁沿用官方本地化词条匹配（R7）。

部件损伤短脉冲（阶段11-2 起，替代原 hudmsg `*` 前缀方案——查证 8111 无普通命中记录）：
- 数据源：`/indicators` 结构化损伤字段（`tracks_state/engine_state/gunner_state` 等，0=完好 非0=损毁），解析为 `TankData.damaged_parts` 损毁部件名集合
- 主控制器帧间差分：出现新损毁部件（含乘员阵亡）即触发 hit 事件；一发炮弹打坏多部件单帧只触发一次
- 仅陆战驾驶坦克时检测（CAS/空战排除）；冷却 `hit_cooldown`（默认 2 秒，`time.monotonic()` 计时）抑制连发；部件修复后再损毁可再次触发
- 输出优先级：击杀/被击毁/维修事件 > 部件损伤短脉冲 > 常态映射；死亡等待重生期间（`_repair_blocked_until_idle`）忽略
- hudmsg 中含玩家名但未分类的损伤消息以限频诊断日志（20 条/会话）记录原文，备后续"重创/点燃"词条校准

事件配置键（`tank_events` 段）：`hit_enabled`、`hit_ch_a/b`、`hit_duration`（0.1~30）、`hit_wf_a/b`、`hit_cooldown`（0~30）、`hit_random_a/b`

## 陆战静止惩罚状态机（阶段10-3，阶段11-1 补死亡封锁）

- 数据信号：`/indicators` 的 `crew_current/crew_total` 解析为 `TankData.crew_alive`（0 乘员 = 被击毁；字段缺失时为 None 不参与判定）
- 状态机（主控制器 `_apply_game_state` 每周期驱动）：
  - 累计条件：陆战地面、坦克数据有效、功能启用、非维修中、乘员存活、非死亡等待重生、维修事件未激活、`abs(speed) < idle_speed_max`
  - 首次满足记 `time.monotonic()` 起点；持续满足超过 `idle_timeout_s` 进入惩罚
  - 任一条件不满足即重置计时并退出惩罚（波形由常规分支恢复，控制器按配置键去重）
- 死亡封锁（阶段11-1）：tank death 事件立即结束惩罚并封锁；封锁中选车界面/出生点静止帧不计时；复活后首次开动（速度达到判定阈值）或退出对局解除
- 输出优先级：击杀/被击毁/维修/部件损伤事件 > 静止惩罚 > 常态速度映射；事件期间输出让位但计时继续
- 豁免目的：避免复活界面、维修惩罚与静止惩罚叠加双倍电击
- 配置键（`tank` 段）：`idle_enabled`、`idle_timeout_s`（1~120）、`idle_speed_max`（0~50）、`idle_ch_a/b`、`idle_wf_a/b`、`idle_random_a/b`（触发时随机切换波形，随机间隔复用 `random_min/max_a/b`）

## 连接与输出分层（阶段17）

完整接口、失败处理及实机验收步骤见 [连接重构说明](connection-refactor.md)。

- `ConnectionService` 在后台串行管理适配器生命周期；故障结束后等待 5 秒重试，切换先停止旧连接，退出取消重试。GUI 读取不可变快照并更新二维码。
- `CoyoteController` / `CoyoteV4Controller` 保留旧公开入口，并实现 `snapshot()`、`submit_output(OutputIntent)`；V4 额外支持 `select_device(slot_id)`。
- `OutputRuntime` 管理最新双通道意图、会话标识、修订号和按通道停止屏障。相同内容只续期；每个通道独立去重。25ms 后台看门狗处理事件绝对期限与 1 秒游戏采样期限，GUI 暂停不会延长事件。
- `DeviceRegistry` 合并 V4 快照和增量，识别蓝牙连接、静音与强度上限；多设备等待手选，设备离线不自动转移控制对象。
- `V4Rpc` 负责请求 ID、错误、超时与会话撤销。命令基准仅由已完成请求更新，App 实际报告独立存储；强度请求不以传输成功代替执行完成。

### V4 强度与停止

- `t:7` 仅能归零，非零目标使用 `t:3` 相对增减。停止次序为禁止补给 → `device.op.clear` → `t:7,v:0`；两个步骤分别等待响应。强度响应必须是 `completed`，若包含设备/通道/类型则校验一致性。
- 增量结果未知不重复累加，先归零后恢复最新有效目标。上报不直接进入增量公式；命令完成后 1 秒内的报告只用于显示和诊断，永不延迟提升为命令基准。
- 冷却外连续两次偏差触发归零重建基准；连续三轮不能收敛，或连续三次强度恢复失败，停止该通道并提示重新连接。已知上限先钳制，静音停止补给。
- 波形不阻塞等候播放结束，但保留请求关联；错误或 3 秒内无结束响应进入通道错误并停止。`replaced/cleared/cancelled` 对被替换波形是正常结束，对强度请求不是成功。
- 仅初始化完成才进入可输出状态。旧会话响应、输出意图和事件不进入新会话；重连使用最新有效游戏采样。

### V3 强度与停止

- 使用绝对强度指令，停止时归零并清空波形。`StrengthData` 更新 App 实际强度与通道上限；蓝牙状态保持未知。
- 停止发送成功不宣称硬件已经确认；发送失败时阻止继续补给并重试清理。

### 波形与遥测

- 每个源帧为 100ms，一秒使用十个连续帧；播放位置来自单调时钟。幅度缩放规则保留，强度变化不重置播放进度，新波形从首帧开始。
- V3 清空后预充两秒，此后每秒补一秒；V4 每 500ms 替换一秒的连续帧窗口。补给不依赖主程序的重复强度命令。
- 遥测保存已发送帧的预计播放时间，替换/停止删除对应未来帧；GUI 只绘制到当前时刻。曲线是下发数据估算，不是设备电压实测。

## 配置容错（阶段15 A1/D1）

- JSON 解析失败或根节点非对象：整体回退默认值；单字段非法：仅该字段回退默认；成对范围（过载 / 速度 / 随机间隔）min > max 时两者都回退
- 发生任何修正时先把原文件备份为 `config.json.invalid-时间戳`，启动后弹窗列出修正项与备份路径
- 程序目录不可写：首次生成配置失败时继续以内存配置运行并提示"设置将无法保存"；壁纸 / 波形目录无法创建时分别只保留"默认壁纸" / "恒定"
- 日志保留：启动时清理 `logs/` 中超过 30 天的 `run_*.log` / `export_*.log`，最多保留 50 个

## 退出流程（阶段17）

停止接收新游戏输出，取消重连，后台继续接收清理 RPC 响应直到清理完成或失败；A 清理失败仍尝试 B。重复 stop 复用同一清理 Future。连接服务与游戏线程共享 5 秒总等待期限；超时标记异常并保留运行日志，不宣称设备已停止。
