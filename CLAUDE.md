# CLAUDE.md — WT-DGLAB 项目工作说明

## 项目简介

WT-DGLAB 是一款 Windows 桌面软件，将战争雷霆游戏数据与郊狼 3.0 电击设备联动。飞机根据过载控制电击，坦克根据损伤控制电击。

## 标准文件路径

| 文件 | 路径 | 用途 |
|------|------|------|
| 需求规格 | [docs/requirements.md](docs/requirements.md) | 功能需求 R1~R5 |
| 技术规格 | [docs/tech-spec.md](docs/tech-spec.md) | 技术栈、架构、协议、公式 |
| 设计规范 | [docs/design-spec.md](docs/design-spec.md) | 配色方案、UI 布局、字体、交互 |
| 开发计划 | [docs/dev-plan.md](docs/dev-plan.md) | 5 阶段开发步骤和检查清单 |
| 开发日志 | [devlog/](devlog/) | 每日开发记录（已完成/待办） |
| 配置文件 | [config.json](config.json) | 运行时生成，用户设置持久化 |

## 工作方式

### 开发原则
1. **逐阶段推进** — 按 5 个阶段依次完成，每阶段验证后再进入下一阶段
2. **模块独立** — 每个模块通过明确接口通信，便于测试和替换
3. **中文优先** — 所有 UI 字符串和代码注释使用中文
4. **用户友好** — 界面简洁直观，错误有提示，操作有反馈

### 代码风格
- Python 代码遵循 PEP 8
- 类名使用 PascalCase，函数/变量使用 snake_case
- 所有公开方法需有 docstring
- GUI 控件使用 Qt 的对象命名机制（setObjectName）便于 QSS 定位

### 每阶段工作流程
1. 阅读 `docs/dev-plan.md` 确认当前阶段目标
2. 实现模块代码
3. 手动验证功能正常
4. 更新 `devlog/` 记录当日完成和待办
5. 更新 `docs/dev-plan.md` 中的阶段状态

### 验证方法
- GUI 验证：`python main.py` 启动后检查界面显示
- 数据验证：启动战争雷霆后检查数据读取
- 设备验证：需要实际手机 + 郊狼 3.0 设备

## 项目结构

```
WT-DGLAB/
├── main.py                     # 程序入口
├── requirements.txt            # Python 依赖
├── config.json                 # 用户配置（运行时生成）
├── CLAUDE.md                   # 本文件
├── docs/                       # 项目文档
│   ├── requirements.md         # 需求规格
│   ├── tech-spec.md            # 技术规格
│   ├── design-spec.md          # 设计规范
│   └── dev-plan.md             # 开发计划
├── devlog/                     # 开发日志
│   └── YYYY-MM-DD.md           # 每日日志
├── src/
│   ├── __init__.py
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # 主窗口 UI
│   │   └── styles.py           # 淡蓝色 QSS 样式
│   ├── config_manager.py       # JSON 配置读写
│   ├── game_reader.py          # WT 8111 数据读取（阶段2）
│   ├── coyote_controller.py    # 郊狼 WS 服务端（阶段3）
│   └── mapping_engine.py       # 数据→强度映射（阶段4）
└── build.py                    # PyInstaller 打包脚本（阶段5）
```

## 关键技术细节

### 战争雷霆数据
- 端口：`localhost:8111`
- 端点：`/state`（GET → JSON）
- 过载字段：`ny`（法向 G-force）
- 损伤字段：需在阶段2抓包确认

### 郊狼 3.0 控制
- 架构：电脑(WS Server) ↔ 手机 App(WS Client) ↔ BLE ↔ 郊狼
- 端口：默认 8765
- 强度范围：0-200
- 连接方式：生成含本机 IP + 端口的 QR 码，手机扫码连接

### 映射公式
```
intensity = (value - min) / (max - min) * channel_max
clamped to [0, channel_max]
```
