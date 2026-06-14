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
- [x] 定义淡蓝色主题 tkinter ttk 样式
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

### 阶段3：郊狼控制模块 ✅
- [x] 研究 DG-LAB Socket 协议（基于 PyDGLab-WS 库）
- [x] 实现 WebSocket 服务端（asyncio 后台线程）
- [x] 实现绑定/心跳/强度消息（由 PyDGLab-WS 封装）
- [x] 实现 QR 码生成（qrcode + PIL → tkinter Canvas）
- [x] 线程安全通信（queue.Queue + asyncio.run_coroutine_threadsafe）
- [ ] 连接测试（需要实际手机+郊狼设备 — 用户自行验证）

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
- [ ] 实际 PyInstaller 打包（需用户执行 `pip install pyinstaller && python build.py`）
- [ ] 游戏内实测（需要战争雷霆 + 郊狼设备）

## 开发原则
- 每个阶段完成后验证再进入下一阶段
- 每个模块保持独立，通过明确接口通信
- 所有用户可见字符串使用中文
- 代码注释使用中文

## 技术方案（最终采用）
- GUI: tkinter（Python 自带，0 MB）
- 郊狼: pydglab-ws 库（封装协议细节）
- 游戏数据: requests 轮询 localhost:8111
- 打包: PyInstaller → 单个 .exe
