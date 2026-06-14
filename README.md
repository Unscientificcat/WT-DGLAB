# 郊狼雷霆 v0.1

> 战争雷霆 × 郊狼 3.0  

[![Windows](https://img.shields.io/badge/platform-Windows-blue)](https://github.com)
[![Python](https://img.shields.io/badge/python-3.10%2B-yellow)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 简介

**郊狼雷霆** 是一款 Windows 桌面工具，基于《战争雷霆》8111端口实时读取游戏遥测数据，将空战过载、陆战速度等动态映射到**郊狼 3.0** 电击设备上。

### 空战模式

| 游戏数据 | 电击效果 |
|----------|----------|
| 法向过载 (G) | 实时强度，G 越大越刺激 |
| 击杀 / 坠毁 | 预设强度脉冲，持续 5 秒 |

### 陆战模式

| 游戏数据 | 电击效果 |
|----------|----------|
| 行驶速度 (km/h) | 速度越快越刺激 |
| 维修状态 | 维修中持续电击 |
| 击杀 / 被摧毁 | 预设强度脉冲 |
| 空中支援 (CAS) | 上飞机自动切 G 值触发 |

## 功能特性

- 🎮 实时读取 WT 8111 端口数据（HTTP 轮询，~7ms）
- ⚡ 18 种官方波形预设（爬坡、呼吸、潮汐、连击……）+ 随机切换
- 🪟 透明置顶悬浮窗，全屏游戏不遮挡
- 🔧 独立 A/B 通道配置，强度 0-200
- ⚙️ 空战 / 陆战 / CAS 三套设置完全独立
- 📱 手机 QR 码扫码连接，电脑 ↔ 手机 ↔ 郊狼 BLE
- 💻 无需安装，单文件 exe 双击即用

## 快速开始

### 方式一：使用打包好的 exe

下载 `WT-DGLAB.exe`，双击运行。**不需要 Python，不需要安装任何依赖。**

### 方式二：从源码运行

```bash
git clone https://github.com/你的用户名/WT-DGLAB.git
cd WT-DGLAB
pip install -r requirements.txt
python main.py
```

### 使用步骤

1. 启动《战争雷霆》
2. 运行 `WT-DGLAB.exe`
3. 阅读注意事项并确认
4. 手机 DG-LAB App 扫描 QR 码连接
5. 贴上电极，开玩

## 技术栈

| 层级 | 技术 |
|------|------|
| GUI | Python tkinter (ttk 淡蓝色主题) |
| 游戏数据 | HTTP 轮询 `127.0.0.1:8111` |
| 设备控制 | PyDGLab-WS WebSocket 服务端 |
| 打包 | PyInstaller `--onefile` → 单文件 exe |

```
战争雷霆 :8111 ──HTTP──► GameReader ──► MappingEngine ──► CoyoteController ──WS──► 手机App ──BLE──► 郊狼3.0
                                                              │
                                                          MainWindow (tkinter GUI)
```

## 配置文件

`config.json` 首次保存后自动生成，包含所有设置。重要字段：

- `app.mode` — 默认模式 (`"aircraft"` / `"tank"`)
- `aircraft.channel_a_max` — 空战 A 通道最大强度 (0-200)
- `tank.channel_a_max` — 陆战 A 通道最大强度 (0-200)
- `cas.*` — 陆战空中支援独立设置
- `events.player_name` — 游戏内昵称（击杀/死亡检测用）

## 注意事项

**⚠ 使用前请务必阅读《注意事项.txt》全文。每次启动都会弹出。**

- 严禁心脏病患者、孕妇、未成年人使用
- 严禁将电极贴于头部、颈部、胸部
- 严禁在驾驶或操作机械时使用
- 建议从最低强度 (0) 开始逐步调整
- 开发者不对任何人身伤害、设备损坏、游戏封号负责

## 开发

```bash
# 打包
python build.py
# 产物 → WT-DGLAB.exe
```

项目遵循 5 阶段开发计划，详见 [docs/dev-plan.md](docs/dev-plan.md)。

## 相关链接

- [战争雷霆 localhost API 文档](https://github.com/lucasvmx/WarThunder-localhost-documentation)
- [DG-LAB 蓝牙协议](https://github.com/ascend-nebula/dglab-bluetooth-protocol)
- [PyDGLab-WS](https://pypi.org/project/pydglab-ws/)

## 致谢

- DG-LAB / 地牢实验室 —— 郊狼 3.0 硬件
- Gaijin Entertainment —— 战争雷霆

---

*本软件为非官方第三方工具，与 Gaijin Entertainment 及 DG-LAB 无关。*
