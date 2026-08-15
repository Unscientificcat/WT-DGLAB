# 开发执行步骤

## 总体阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| 1 | 基础框架 — 主窗口、主题、配置管理 | ✅ 完成 |
| 2 | 游戏数据模块 — HTTP 轮询、数据解析 | ✅ 完成 |
| 3 | 郊狼控制模块 — WebSocket、QR码、心跳 | ✅ 完成 |
| 4 | 映射引擎 + 设置面板联调 | ✅ 完成 |
| 5 | 整合测试 + PyInstaller 打包 | 🚧 进行中 |

## 阶段详细

### 阶段1：基础框架 ✅
- [x] 创建项目目录结构
- [x] 实现 ConfigManager（JSON 配置读写）
- [x] 定义浅色 PySide6 / QSS 主题
- [x] 实现 MainWindow 布局（状态栏+面板+QR区）
- [x] 实现 SettingsPanel（所有参数设置控件）
- [x] 实现 Dashboard（实时数据展示面板）
- [x] 实现 StatusBar（连接状态指示）
- [x] 实现 QRWidget（QR 码区域）
- [x] 创建 main.py 入口（App 类集成各模块）
- [x] 验证 GUI 正常启动显示

### 阶段2：游戏数据模块 ✅
- [x] 实现 GameReader HTTP 轮询
- [x] 解析飞机过载数据（ny 字段）
- [x] 解析坦克损伤数据（indicators + state 双重提取）
- [x] 连接 Dashboard 实时显示
- [x] auto-detect 载具类型
- [x] 异常处理（WT未运行、超时、JSON解析失败）
- [x] 独立 EventDetector（跨局 HUD 游标、击杀/死亡、维修边沿）

### 阶段3：郊狼控制模块 ✅
- [x] 研究 DG-LAB Socket 协议（基于 PyDGLab-WS 库）
- [x] 实现 WebSocket 服务端（asyncio 后台线程）
- [x] 实现绑定/心跳/强度消息（由 PyDGLab-WS 封装）
- [x] 实现 QR 码生成（qrcode + PIL → Qt QPixmap）
- [x] 线程安全通信（queue.Queue + asyncio.run_coroutine_threadsafe）
- [x] V3/V4 App 用户选择、配置迁移和连接重建
- [x] V4 Relay、官方二维码、设备快照、强度与波形控制
- [x] V3 本机服务和 V4 官方 Relay 握手验证
- [ ] V4 实际设备测试（需要 4.x App + 郊狼设备）

### 阶段4：映射引擎 ✅
- [x] 实现 MappingEngine 线性映射
- [x] 解耦飞机映射和坦克映射为独立方法
- [x] 连接 GameReader → MappingEngine → CoyoteController
- [x] 设置面板参数在轮询中实时生效
- [x] 异常处理（边界值、除零保护）

### 阶段5：整合与打包 🚧
- [x] 端到端模块集成（main.py App 类）
- [x] 异常状态处理（WT未运行 → 零强度、设备断连 → 忽略指令）
- [x] PyInstaller 打包脚本（build.py）
- [x] 自动回归测试（基础 37 项；托盘更新后 41 项；单实例更新后 44 项）
- [x] 实际 PyInstaller 打包（`WT-DGLAB v1 beta_1.exe`）
- [x] 重写 GitHub README，并补充 `v1 beta_1` 相对 `v1 beta` 的更新日志
- [ ] 游戏内实测（需要战争雷霆 + 郊狼设备）

### 2026-08-15：v1 beta_1 发布整理 ✅
- [x] 统一程序窗口标题、Windows 应用标识和发布版本号为 `郊狼雷霆 v1 beta_1`
- [x] 将 PyInstaller 产物命名为 `WT-DGLAB v1 beta_1.exe`
- [x] README 和开发日志补充今晚的托盘、持久化、单实例、维修恢复及 CAS 更新
- [x] 整理源码、文档、测试、图标和新版 EXE 到 `release`
- [x] 根目录与 `release` 自动化测试均通过 `51 passed`

### 2026-08-15：托盘、配置持久化与图标更新 🚧
- [x] 确认交互和配置存储方案
- [x] 建立专项开发文档
- [x] 点击关闭按钮后隐藏到系统托盘
- [x] 托盘恢复窗口和真正退出程序
- [x] 配置保存到 EXE 同目录且缺失时自动生成
- [x] 关闭到托盘和托盘退出时自动保存当前设置
- [x] 使用 `tubiao1.jpg` 替换全部程序图标
- [x] 自动测试与 PyInstaller 打包（托盘阶段根目录与 `release` 均为 41 项通过）

### 2026-08-15：单实例与重复启动 🚧
- [x] Windows 命名互斥锁阻止第二业务实例
- [x] Qt 本地 IPC 通知已有实例显示主窗口
- [x] 隐藏到托盘后重复启动可以触发恢复
- [x] 激活请求应答和启动竞态重试
- [x] 新增单实例回归测试（完整测试 44 项通过）
- [x] PyInstaller 重新打包与双进程实机验证

### 2026-08-15：维修事件覆盖恢复 🚧
- [x] 定位维修边沿被击杀优先级消费的根因
- [x] 击杀/死亡结束后重新检查当前维修状态
- [x] 持续维修时立即恢复维修强度和波形
- [x] 新增维修覆盖场景回归测试（完整测试 47 项通过）
- [x] 同步 `release` 与 PyInstaller 重新打包

### 2026-08-15：陆战 CAS 触发开关与事件修复 🚧
- [x] 增加可持久化的“启用 CAS 触发”开关
- [x] 关闭 CAS 时同时禁止过载和击杀/坠毁事件输出
- [x] 陆战 CAS 复用陆战事件配置并保留飞机事件显示语义
- [x] 增加 CAS 配置、事件选择和输出门控测试（完整测试 51 项通过）
- [x] 同步 `release` 与 PyInstaller 重新打包

## 开发原则
- 每个阶段完成后验证再进入下一阶段
- 每个模块保持独立，通过明确接口通信
- 所有用户可见字符串使用中文
- 代码注释使用中文

## 技术方案（最终采用）
- GUI: PySide6（Qt 桌面界面，详见 `docs/ui-redesign.md`）
- 郊狼 V3: pydglab-ws 本机服务端
- 郊狼 V4: 按官方 V4 RPC 帧实现的 Relay 客户端
- 游戏数据: requests 轮询 localhost:8111
- 打包: PyInstaller → 单个 .exe
