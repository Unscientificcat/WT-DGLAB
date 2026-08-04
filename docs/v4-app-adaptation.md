# DG-LAB 4.x App Socket 适配开发文档

## 目标

在保留现有 DG-LAB 3.x App 连接方式的前提下，为 WT-DGLAB 增加 DG-LAB 4.x App 的 V4 Socket 控制能力。用户可在右侧“连接郊狼”区域选择 V3 或 V4，现有战争雷霆读取、强度映射、事件检测和波形设置保持不变。

## 官方资料结论

- V3：当前项目使用 `pydglab-ws` 在电脑上启动 WebSocket 服务端，App 扫码后与本地控制端配对。
- V4：程序作为控制方连接 V4 Relay；Relay 返回 `targetId`，App 使用带 `tid=targetId` 的地址接入。
- 官方 V4 Relay 控制方地址为 `wss://trex.dungeon-lab.cn/v4`；自建 Relay 默认监听 `ws://127.0.0.1:9998`。控制方地址末尾不能多加 `/`。
- V4 配对链接格式：`https://dungeon-lab.cn/s/?v=1&action=socket&url=<编码后的 App WebSocket 地址>`。
- V4 设备操作必须同时指定 App 的 `clientId`、设备的 `slotId` 和通道。
- Python SDK `dglab-kit-python` 当前 GitHub 版本要求 Python 3.13+ 和 `websockets>=15.0.1`；截至本次实施时 PyPI 尚无可安装发行版。

参考资料：

- <https://github.com/dungeonlab-open/dglab-kit-python>
- <https://github.com/dungeonlab-open/dglab-kit>
- <https://github.com/dungeonlab-open/dglab-websocket-server>
- <https://github.com/dungeonlab-open/dglab-bluetooth-protocol/blob/main/coyote/v3/README.md>

## 交互设计

- 右侧连接设置增加 `V3 App` / `V4 App` 分段切换按钮。
- V3 模式显示“本机服务端端口”，继续使用现有本地二维码流程。
- V4 模式显示“Relay 地址”，默认使用官方 V4 Relay；允许填写自建 `ws://` 或 `wss://` 地址。
- 点击 V3/V4 按钮后立即保存选择、重建连接控制器并刷新对应二维码，不需要再点击“保存设置”，也不要求重启程序。
- 状态区域区分“正在连接 Relay”“等待 App 接入”“等待设备”“已连接”和错误状态。
- 配置文件新增字段时保持向后兼容；旧配置默认继续使用 V3。

## 技术设计

- 保留 `CoyoteController` 作为 V3 实现，新增 `CoyoteV4Controller`。
- 两个控制器提供一致的公开接口：`start()`、`stop()`、`status`、`get_qrcode_url()`、强度设置、波形设置和 `clear_all()`。
- 主控制器根据 `app.dglab_protocol` 创建对应实现，并在连接设置保存后按需切换。
- V4 默认选择首个接入 App 的首个可用郊狼设备；App 或设备断开后立即将状态置为未绑定，不继续发送输出。
- 官方 Python SDK 与现有 V3 库的 `websockets` 版本要求互斥，因此 V4 控制器按官方 SDK 帧结构实现所需的最小 RPC 子集，同时继续固定 V3 的稳定依赖版本。
- V4 强度采用绝对目标值语义：跟踪上一次已发送值，并使用归零或带正负值的强度增量达到目标值。
- V4 波形继续复用项目现有波形播放器，将每个 100ms 脉冲转换为 SDK 接受的四帧频率/强度数据。
- 不在桌面程序中内嵌 Relay；用户可使用官方 Relay 或自行部署官方 `dglab-websocket-server`。

## 安全要求

- 新 App 或设备刚接入时，A/B 通道先归零，再允许正常输出。
- 退出有效对局、切换协议、关闭程序或连接断开时清理 V4 操作并归零。
- 所有强度继续限制在 `0..200`。
- Relay 未连接、App 未接入或设备槽位不可用时不发送强度与波形任务。

## 验证清单

- [x] 旧 `config.json` 加载后默认 V3，保存重载不丢失协议与 Relay 地址。
- [x] 右侧 V3/V4 切换会切换对应输入项并持久化。
- [x] V3 现有二维码和控制器行为保持兼容。
- [x] V4 Relay 握手后生成符合官方格式的二维码。
- [x] App 接入及设备快照后正确进入已绑定状态。
- [x] V4 A/B 强度归零、增加、减少和波形下发参数正确。
- [x] 切换协议会停止旧控制器并启动新控制器。
- [x] 完整自动测试、Python 语法检查和 Qt 离屏启动通过。
- [ ] 使用 DG-LAB 4.x App 与实际郊狼设备联调。

## 实施记录

### 2026-08-04

- 已完成官方 V4 Socket、Relay、二维码和设备寻址方式复核。
- 已确认采用双协议并存方案，由用户在右侧连接面板自行选择。
- 已完成 V3/V4 配置、右侧切换控件、控制器重建和非阻塞连接流程。
- 已完成官方 V4 Relay 真实握手、二维码生成和干净断开验证。
- 已完成 V3 本机服务启动/停止回归及 29 项自动测试。
- 已完成完整应用内从 V3 点击切换 V4、连接官方 Relay并自动刷新二维码的端到端验证。
