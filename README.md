<p align="center">
  <img src="tubiao_ui.jpg" width="128" alt="郊狼雷霆图标">
</p>

<h1 align="center">郊狼雷霆</h1>

<p align="center">
  将《战争雷霆》实时遥测与 DG-LAB 郊狼 3.0 联动的 Windows 桌面程序
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v1%20beta-4f8fe8" alt="版本 v1 beta">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-2d7dd2" alt="Windows 10 / 11">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/DG--LAB%20App-V3%20%2F%20V4-ef6f91" alt="DG-LAB App V3 / V4">
</p>

> [!WARNING]
> 本项目会控制电刺激设备，使用不当可能造成人身伤害。首次使用前必须完整阅读[《注意事项》](注意事项.txt)，所有通道都应从 `0` 强度开始逐步测试。未成年人、孕妇、心脏疾病患者及植入医疗设备者严禁使用。

## 项目简介

郊狼雷霆（WT-DGLAB）读取《战争雷霆》本机 `8111` 端口提供的实时数据，将空战过载、陆战速度和游戏事件映射为郊狼 A/B 通道的强度与波形。

程序支持 DG-LAB 3.x App 的本机 WebSocket 连接，也支持 DG-LAB 4.x App 的 Socket Relay 连接。用户可以在界面中切换 V3 / V4，选择后会自动保存、重建连接并刷新二维码。

本项目是一个 Vibe Coding 实践作品，代码、协议判断和安全行为仍应以实际测试结果为准。

当前版本为 `v1 beta`。协议、界面和自动化回归已经验证；DG-LAB 4.x App 与实际郊狼设备的完整实机联调仍在进行中，请谨慎测试。

## 功能

### 空战模式

- 读取法向过载 `ny`，根据用户设置的 G 值上下限线性映射强度。
- A/B 通道可分别设置最大强度和波形。
- 可为击杀、被击落或坠毁单独设置强度、持续时间与波形。
- 实时仪表盘和透明悬浮窗显示当前 G 值及双通道输出。

### 陆战模式

- 根据载具速度映射电击强度，速度上下限可配置。
- 击杀、被摧毁和维修事件可以使用独立强度与波形。
- 在陆战中进入飞机时自动使用 CAS 过载配置。
- CAS、常规陆战和陆战事件配置彼此独立。

### 通用能力

- DG-LAB V3 / V4 App 双协议切换。
- A/B 双通道独立强度，范围 `0..200`。
- 恒定输出、多种官方波形预设和定时随机波形。
- 浅色 PySide6 三栏界面，默认面向 1080p，支持拖动分栏。
- 透明置顶悬浮窗，提供大 / 中 / 小三档尺寸；大档兼顾 2K 屏幕。
- 参数保存、恢复默认和启动自动加载。
- 数值框与下拉框带滚轮保护，滚动页面时不会误改参数。
- 离开有效对局后清空遥测、取消事件并将 A/B 通道归零。
- 单文件 Windows EXE，用户无需安装 Python 或项目依赖。

## 系统要求

| 项目 | 要求 |
|---|---|
| 操作系统 | 64 位 Windows 10 / 11 |
| 游戏 | Windows 版《战争雷霆》，运行时可访问 `127.0.0.1:8111` |
| 设备 | DG-LAB 郊狼 3.0、电极线与贴片 |
| 手机 | 安装 DG-LAB 3.x 或 4.x App |
| V3 网络 | 手机与电脑位于可互通的同一局域网 |
| V4 网络 | 电脑和手机能够连接所配置的 WebSocket Relay |

## 快速开始

### 使用发布版 EXE

1. 从 GitHub Releases 下载 `WT-DGLAB.exe`。
2. 启动《战争雷霆》，进入机库或对局。
3. 运行 `WT-DGLAB.exe`，阅读并确认注意事项。
4. 在右侧“连接郊狼”区域选择 `V3 App` 或 `V4 App`。
5. 使用手机 App 扫描程序显示的二维码。
6. 先将 A/B 最大强度设为 `0`，确认连接、模式和波形正确后再逐步增加。

发布版已经包含 Python、PySide6、Pillow、WebSocket 等运行依赖，不需要额外安装环境。由于使用 PyInstaller 单文件模式，首次启动时需要解压运行库，可能比后续启动稍慢。

### V3 App 连接

1. 在程序右侧选择 `V3 App`，默认本机服务端端口为 `8765`。
2. 确保手机和电脑连接同一局域网，且未开启 AP 隔离或访客网络隔离。
3. 首次运行时，允许 `WT-DGLAB.exe` 通过 Windows 防火墙的“专用网络”。
4. 在 DG-LAB 3.x App 的 Socket / 扫码控制入口扫描二维码。

V3 只需要局域网入站连接，不需要在路由器上配置公网端口映射，也不建议将 `8765` 暴露到公网。若修改了程序中的 V3 端口，防火墙规则也要允许相应 TCP 端口。

### V4 App 连接

1. 在程序右侧选择 `V4 App`，程序会立即保存选择并连接 Relay。
2. 默认 Relay 为 `wss://trex.dungeon-lab.cn/v4`，也可以填写自行部署的 `ws://` 或 `wss://` 地址。
3. 等待二维码刷新后，在 DG-LAB 4.x App 中选择 Socket 控制并扫码。
4. App 接入后，程序会选择首个可用的郊狼设备槽位并先将 A/B 通道归零。

V4 由程序主动连接 Relay，通常不需要开放电脑的 `8765` 入站端口。官方 Relay 不可达时，可以部署官方 `dglab-websocket-server` 并在界面中填写自建地址。

## 参数说明

| 区域 | 参数 | 作用 |
|---|---|---|
| 空战 | G 值下限 / 上限 | 决定过载映射的起点和满强度点 |
| 陆战 | 速度下限 / 上限 | 决定速度映射的起点和满强度点 |
| CAS | G 值与通道设置 | 陆战中进入飞机时使用 |
| A/B 通道 | 最大强度 | 独立限制两个通道，范围 `0..200` |
| 波形 | 恒定 / 预设 / 随机 | 设置常规映射和事件输出的波形 |
| 事件 | 强度 / 持续时间 | 设置击杀、被击落、被摧毁和维修反馈 |
| 玩家昵称 | 游戏内昵称 | 用于区分与玩家相关的 HUD 事件，请保持完全一致 |
| 刷新间隔 | `50..1000 ms` | 控制读取 8111 数据的频率，默认 `200 ms` |
| 悬浮窗 | 开关与尺寸 | 显示当前遥测、事件和 A/B 输出 |

映射采用线性插值，并将最终强度限制在通道最大值内：

```text
value <= min  -> 0
value >= max  -> channel_max
其他          -> (value - min) / (max - min) * channel_max
```

## 安全机制

- 默认配置的 A/B 最大强度和事件强度均为 `0`。
- 未确认处于有效对局时，不使用 `8111` 端口可能残留的速度或过载值。
- 退出对局、游戏断开、切换协议、设备断开或程序关闭时停止相关输出并归零。
- 新 V4 App 或设备刚接入时先清空通道任务并归零。
- 所有输出强度最终限制在 `0..200`。

这些机制不能替代使用者的安全判断。请勿将电极贴在头部、颈部、胸部或破损皮肤上，也不要在驾驶、操作机械或其他危险环境中使用。

## 常见问题

### 战争雷霆一直显示未连接

- 确认游戏正在运行，并尝试在浏览器打开 `http://127.0.0.1:8111/state`。
- `8111` 是游戏提供的本机接口，通常不需要手动开放防火墙端口。
- 返回 `{"valid": false}` 通常表示当前不在有效对局，程序会保持安全归零。

### V3 扫码后无法连接

- 确认手机和电脑在同一网段，而不是访客 Wi-Fi。
- 允许 `WT-DGLAB.exe` 通过 Windows 专用网络防火墙。
- 确认程序显示的 IP 是手机能够访问的局域网地址。
- 检查 V3 端口是否被其他程序占用。
- 不要为此配置公网端口转发。

### V4 一直停在连接 Relay

- 检查电脑能否访问所填的 `ws://` 或 `wss://` 地址。
- 官方 Relay 不可用时尝试自建 Relay。
- 切回 V3 再切换到 V4 会自动重建连接并刷新二维码，无需点击“保存设置”。


## 从源码运行

### 准备环境

```powershell
git clone https://github.com/Unscientificcat/WT-DGLAB.git
cd WT-DGLAB

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

项目要求 Python 3.11 或更高版本。当前开发与打包环境使用 Python 3.14。

### 运行测试

```powershell
python -m pip install pytest
python -m pytest -q
```

当前完整自动化测试结果为 `34 passed`。实际手机、游戏和电刺激设备仍需要人工联调。

### 打包

```powershell
python build.py
```

打包脚本使用 PyInstaller `--onefile --windowed`，产物为项目根目录下的 `WT-DGLAB.exe`。Windows 程序图标使用预制的多尺寸 `tubiao.ico`。

## 架构

```text
战争雷霆 :8111
       |
       v
  GameReader ---> EventDetector
       |               |
       +-------> MappingEngine
                        |
                  MainWindow / Overlay
                        |
          +-------------+-------------+
          |                           |
          v                           v
 CoyoteController              CoyoteV4Controller
 V3 本机 WS 服务端              V4 Relay 客户端
          |                           |
          v                           v
 DG-LAB 3.x App                 Relay -> DG-LAB 4.x App
          |                           |
          +------------ BLE ----------+
                         |
                    郊狼 3.0
```

主要模块：

| 文件 | 职责 |
|---|---|
| `main.py` | 生命周期、线程队列、UI 与控制器协调 |
| `src/game_reader.py` | 读取并解析战争雷霆 `8111` 数据 |
| `src/event_detector.py` | HUD 击杀 / 死亡事件与维修边沿检测 |
| `src/mapping_engine.py` | G 值 / 速度到 A/B 强度的线性映射 |
| `src/coyote_controller.py` | DG-LAB V3 本机 WebSocket 服务端 |
| `src/coyote_v4_controller.py` | DG-LAB V4 Relay 控制客户端 |
| `src/gui/` | PySide6 主窗口、样式、悬浮窗和注意事项 |
| `src/config_manager.py` | `config.json` 配置加载、保存与默认值 |

更详细的技术资料见 [docs/tech-spec.md](docs/tech-spec.md)、[docs/ui-redesign.md](docs/ui-redesign.md) 和 [docs/v4-app-adaptation.md](docs/v4-app-adaptation.md)。

## 更新日志

### v1 beta

相较 `v0.1`，本版本主要更新如下。

#### 全新界面

- GUI 从 tkinter 全面迁移到 PySide6。
- 重做为浅色三栏控制界面，覆盖主窗口、实时仪表盘、参数设置、二维码、悬浮窗和注意事项。
- 默认适配 1080p，并优化 2K 屏幕下的悬浮窗大档尺寸。
- 数值框和下拉框不再响应悬停滚轮，避免滚动页面时误改参数。
- 发布包改为携带完整 Qt 运行库，免安装兼容性提高，但 EXE 由 `v0.1` 的约 26 MB 增至当前约 270 MB。

#### DG-LAB 4.x App 支持

- 在保留 V3 本机 WebSocket 模式的基础上新增 V4 Socket Relay 控制器。
- 支持官方 Relay 和用户自建 Relay。
- V3 / V4 切换后自动保存、重建控制器并刷新二维码，不再需要额外点击保存。
- 网络连接移出 Qt 主线程，Relay 不可达时不会阻塞界面。
- 修复切换协议时 V3 服务残留异步任务的问题。

#### 遥测和事件检测重写

- 新增独立 `EventDetector`，统一处理 HUD 游标、击杀、被击落、被摧毁和维修事件。
- 持续消费战争雷霆跨局递增的 `lastDmg`，菜单阶段只推进游标，新对局首批事件可以及时触发。
- 修复旧 HUD 历史记录在保存设置、断开或重进对局后重复触发的问题。
- 修复事件刚入队时被空遥测误取消，以及击杀倒计时停在 `5.0s` 的问题。

#### 对局退出安全归零

- 不再仅依赖 `/state` 或速度是否为零判断对局状态。
- 使用 `/map_info.json` 有效性作为输出门槛，拦截菜单中残留的速度和载具数据。
- 离开有效对局时清空仪表与悬浮窗、取消未结束事件，并立即将 A/B 通道归零。

#### 悬浮窗与稳定性

- 修复悬浮窗开关和大 / 中 / 小尺寸按钮不立即生效的问题。
- 悬浮窗改为真正透明背景，并保留置顶与拖动。
- 增大“大”档字号，提高 2K 屏幕可读性，同时保留适合 1080p 的中 / 小档。
- 修复反复打开和关闭注意事项对话框可能导致程序闪退的问题。

#### 设置、品牌与工程质量

- 将刷新间隔移动到左侧仪表盘底部，V3 / V4 连接参数集中在右侧。
- 修复部分波形与随机间隔配置重启后未正确加载的问题。
- 版本号更新为 `v1 beta`，更新窗口、任务栏、任务管理器和 EXE 图标。
- 建立 V3 / V4、遥测安全、事件检测、界面和品牌资源回归测试，当前共 `34` 项。

### v0.1

- 首个可运行版本。
- 支持战争雷霆空战过载与陆战速度映射。
- 支持 DG-LAB 3.x App、本机 WebSocket、A/B 通道、基础波形和事件设置。
- 使用 tkinter 界面，仅提供 V3 连接路径。

## 已知限制

- 当前主要面向 Windows 与郊狼 3.0，未验证其他硬件型号。
- DG-LAB V4 Relay 握手、二维码和协议帧已验证，但 4.x App 与实际设备的完整实机联调仍待完成。
- 战争雷霆接口字段可能随游戏更新或载具类型变化，事件识别也依赖游戏 HUD 文本。
- 项目仍处于 beta 阶段，不建议在无人看护或高强度场景中使用。

## 发布前注意

- `config.json` 可能包含玩家昵称和个人强度设置，公开仓库前应确认其中没有隐私信息。
- `wt-dglab-trace.log` 属于诊断日志，不应作为正式发布内容。
- 建议通过 GitHub Releases 分发 `WT-DGLAB.exe`，不要要求普通用户从源码构建。

## 相关资料

- [战争雷霆 localhost:8111 文档](https://github.com/lucasvmx/WarThunder-localhost-documentation)
- [DG-LAB 郊狼 3.0 蓝牙协议](https://github.com/dungeonlab-open/dglab-bluetooth-protocol/blob/main/coyote/v3/README.md)
- [DG-LAB Python Kit](https://github.com/dungeonlab-open/dglab-kit-python)
- [DG-LAB WebSocket Relay](https://github.com/dungeonlab-open/dglab-websocket-server)

## 许可证与声明

本仓库当前未附带 `LICENSE` 文件，因此不要将其视为已经采用 MIT 或其他开源许可证。准备正式开源时，请由仓库所有者补充合适的许可证。

本项目是非官方第三方工具，与 Gaijin Entertainment、War Thunder、DG-LAB 或地牢实验室不存在隶属或授权关系。相关名称和商标归各自权利人所有。
