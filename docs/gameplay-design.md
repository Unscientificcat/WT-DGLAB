# WT-DGLAB 新玩法设计文档

> 版本：v0.1（2026-09-13）
> 状态：提案（未排期）
> 调研来源：DG-LAB 官方开源协议文档、WarThunder-localhost-documentation、社区开源项目（详见文末参考资料）
> 本文目标：在现有功能（空战过载 / 陆战速度 / CAS / 击杀·被击落·坠毁·维修事件）基础上，系统性梳理"还能做什么玩法"，并给出数据来源、触发逻辑、输出设计、配置结构与落地路线。

---

## 1. 现状盘点

| 能力 | 现状 | 数据来源 |
|---|---|---|
| 空战常态映射 | 过载 `ny` → 线性 → A/B 强度 | `/state` |
| 陆战常态映射 | 速度 `speed` → 线性 → A/B 强度 | `/indicators` |
| CAS | 陆战上飞机后复用 CAS 过载配置 | `/state` + `/indicators` |
| HUD 事件 | 击杀 / 被击落 / 坠毁 / 维修边沿，7 语言 | `/hudmsg` + `/indicators` |
| 波形 | `.pulse` 文件解析 + 常规/事件随机换波 | 本地文件 |
| 输出 | V3 App（本机 WS 服务端）/ V4 App（Relay）双协议、双通道、输出遥测曲线 | 自研控制器 |
| 仲裁 | 单事件覆盖常态映射（事件期间替代强度） | `main.py` |
| 安全 | 离开对局归零、异常配置回退、通道上限 | 已有 |

**技术空隙**（本次玩法的切入点）：

1. 8111 还有 4 个端点完全没用上：`/mission.json`、`/map_obj.json`、`/gamechat`、`/map.img`。
2. `/state` 的攻角、侧滑、马赫数、油量、垂直速度、角速度、发动机温度/转速等几十个字段没用上。
3. `/hudmsg` 只匹配了击杀/坠毁类文本，命中、暴击、起火等文本没用上。
4. `/indicators` 的乘员、模块状态只做了"维修"，没做"损伤→强度"。
5. 映射曲线只有线性，没有阶梯/曲线/多源叠加。
6. 事件系统是"单事件覆盖"，没有冷却、连击、递增、叠加仲裁。
7. V3 协议中手机 App 的 5×2 反馈按钮（`feedback-角标`）没利用——手机端互动玩法是空白。

---

## 2. 数据源调研结论：8111 端点全表

8111 是 Gaijin 官方提供给本地工具的 HTTP 接口，本地免认证；官方论坛明确以"使用 8111 提供的数据"作为合规工具的判定线（相对于读屏/注入），本项目全部数据来自该端口，合规。

| 端点 | 内容 | 当前使用 | 新玩法可用数据 |
|---|---|---|---|
| `/state` | 飞行遥测主数据 | ✅ 部分 | 攻角、侧滑、马赫、油量、垂直速度、角速度、发动机参数、起落架等 |
| `/indicators` | 座舱仪表/载具状态 | ✅ 部分 | 乘员、模块、弹药、维修、油量等 |
| `/map_info.json` | 地图边界/网格 | ✅（仅做对局判定） | 地图实际尺寸（换算距离用） |
| `/hudmsg` | HUD 事件流 | ✅ 部分 | 命中、暴击、起火等新事件文本 |
| `/mission.json` | 任务目标 | ❌ | 目标完成/失败、（部分版本含比分/玩家，需实测） |
| `/map_obj.json` | 地图所有可见对象 | ❌ | 敌我位置、距离、航向、速度（接近/咬尾告警） |
| `/gamechat` | 游戏内聊天 | ❌ | 增量消息（低优先级） |
| `/map.img` | 地图图片 | ❌ | 仅悬浮窗美化可选 |

> 字段名大小写和存在性因版本/机型而异（文档记 `AoA, deg`、实际出现 `aoa, deg` 的情况都有），现有 `_detect_vehicle_type` 的大小写兼容思路要保留。**下列字段标注〔需实测〕的，开发前必须先在实机对局中抓取确认。**

### 2.1 `/state` 关键字段（含未利用字段）

| 字段 | 单位 | 含义 | 玩法价值 |
|---|---|---|---|
| `ny` / `Ny` | G | 法向过载 | 已用 |
| `IAS, km/h` / `TAS, km/h` | km/h | 指示/真实空速 | 显示（已用）、超速告警〔需实测 `IAS max` 滚动极值〕 |
| `M` | 马赫 | 马赫数 | 超速告警、音障事件 |
| `H, m` | m | 气压高度 | 低空飞行玩法、着陆判定 |
| `AoA, deg` | ° | 迎角 | **失速告警**（接近临界迎角） |
| `AoS, deg` | ° | 侧滑角 | 侧滑/乱流惩罚（教官模式） |
| `Vy, m/s` | m/s | 垂直速度 | 着陆判定、俯冲告警 |
| `Wx, deg/s`（另有 Wy/Wz〔需实测〕） | °/s | 滚转角速度 | 桶滚/滚转惩罚（教官模式） |
| `Mfuel, kg` / `Mfuel0, kg` | kg | 当前/满载油量 | **油量焦虑**（油少→背景强度上升） |
| `throttle N, %` | % | 油门 | 显示 |
| `RPM N`、`power N, hp`、`thrust N, kgs` | — | 发动机参数 | 引擎状态映射 |
| `water temp N, C` / `oil temp N, C` | °C | 水/油温 | **过热惩罚**（拉高油门烧引擎） |
| `manifold pressure N, atm` | atm | 进气压力 | 增压状态 |
| `flaps, %`、`gear, %`〔需实测〕、`airbrake, %`〔需实测〕 | % | 襟翼/起落架/减速板 | 起落架未收警告、着陆判定 |
| `aileron/elevator/rudder, %` | % | 舵面位置 | 教官模式（杆量异常） |
| 极值对字段（`IAS, km/h min/max` 等〔需实测〕） | — | 本局滚动极值 | 局末战报（最大过载、最大速度） |

### 2.2 `/indicators` 关键字段

| 字段 | 含义 | 玩法价值 |
|---|---|---|
| `speed`、`throttle`、`mach`、`g_meter`、`g_meter_min/max` | 仪表读数 | **g_meter 极值**可直接做局末战报 |
| `gunner_state / driver_state / commander_state / loader_state` | 乘员阵亡标志（0 活/非0 亡） | **乘员阵亡事件**（每个乘员死一次脉冲一次） |
| `crew_current / crew_total` | 当前/总乘员 | **损伤比例→背景强度**（补全原 R2"陆战损伤映射"） |
| `engine_state / transmission_state / tracks_state / breech_state / barrel_state …` | 模块损毁标志 | **模块损坏事件**（断履带/炸炮闩各自触发） |
| `is_repairing`、`repair_time` | 维修 | 已用 |
| `first_stage_ammo`、弹药计数类字段〔需实测〕 | 弹药 | **弹药告急**（弹仓打空→提醒脉冲） |
| 油量、火警类字段〔需实测〕 | 燃油/起火 | 起火事件备用数据源 |
| 雷达/告警类字段〔需实测，存在性不确定〕 | RWR 等 | 若存在则是**被锁定告警**的第一数据源 |

### 2.3 `/map_obj.json`（本次玩法最大增量的数据源）

- 返回当前地图上所有**可见对象**：`type` ∈ {`airfield`, `aircraft`, `ground_model`, `defending_point`, `bombing_point`, `respawn_base_fighter`, `respawn_base_bomber`}；`icon` 标识具体类别（`Fighter/Bomber/Tracked/Wheeled/Airdefence/Player`…），`icon == "Player"` 是玩家自己。
- `x, y ∈ [0,1]` 归一化坐标；`dx, dy` 是航向单位向量（`atan2(dy,dx)` 求航向角）；机场对象用 `sx/sy/ex/ey` 线段表示。
- 敌我靠 `color` 字段区分（友军与我方同色，敌军为另一色——按"与 Player 同色=友方"判定比猜色值稳）。
- **距离换算**：`距离(m) = hypot(Δx × (map_max.x - map_min.x), Δy × (map_max.y - map_min.y))`，地图尺寸来自 `/map_info.json`（如 min=-32768, max=32768）。map_obj 轮询建议 500ms~1s 一次，独立于 200ms 遥测轮询，避免请求压力。
- 注意：只能看到地图上"应该能看到"的对象（与游戏内地图一致），非透视；陆战地面目标一般仅显示被点亮的单位。

### 2.4 `/mission.json` 与 `/hudmsg`

- `/mission.json`：稳定字段为 `objectives[]`（`primary`、`status ∈ {in_progress, completed, failed}`、`text`）和顶层 `status ∈ {running, fail}`。部分版本含玩家/比分信息〔需实测〕——若确认有双方比分，"比分差惩罚"和"胜负结算"玩法可直接落地；若没有，则用 objectives 完成/失败边沿。
- `/hudmsg`：`damage[]` 记录字段 `id / msg / sender / enemy / mode`，id 跨局累加（现有游标逻辑已处理）。社区已知文本层级：`hit`（命中）→ `critical hit`（暴击）→ `set afire`（点燃）→ `destroyed`（摧毁）→ `has crashed`（坠毁）。**新事件词条必须按 R7 的七语言方法实测收集后写死正则**，本文只定机制不定词条。

---

## 3. 协议侧调研结论：还能榨出什么能力

### 3.1 V3 Socket 协议（官方 Socket 控制协议 V2，郊狼 3.0）

- 二维码：`https://www.dungeon-lab.com/app-download.php#DGLAB-SOCKET#ws(s)://地址:端口/clientId`（现有实现一致）。
- 强度指令三种模式：减 1 / 加 1 / 设为指定值（0-200），App 端上限会钳制；App 强度/上限变化会主动回传 `strength-A+B+Alimit+Blimit`。
- **手机反馈按钮**：App 界面每通道 5 个按钮，按下会上报 `feedback-角标`（0-4 为 A 通道、5-9 为 B 通道）。**当前项目完全没监听** —— 这是"手机端互动玩法"的入口（见玩法 C1）。
- 波形帧：8 字节 HEX = 100ms（4×25ms：4 字节频率 + 4 字节强度）；单条消息最多 100 帧（10 秒），App 队列 500 帧（50 秒）；发送间隔略小于数据时长保证连续（现有 `_send_waveform_pulse` 已遵循）。
- JSON 上限 1950 字符；心跳 60s；错误码 200/209/401…209（对方断开）可用于快速感知 App 掉线。
- **强度 0-200 是相对标量，官方未公开实际电压换算**；波形强度字节 0-100 是该帧相对通道强度的幅度比例（超 100 可"屏蔽"通道），频率字节 10-240 由逻辑频率 10-1000 分段压缩而来。体感上：**强度决定脉冲电压高度，频率平衡参数决定冲击感、强度平衡参数（脉宽）决定体感强弱**。
- 结论：**不要向用户承诺"强度 X = 电压 Y"**；UI 文案保持 0-200 相对刻度。

### 3.2 蓝牙直连（官方 dglab-bluetooth-protocol，郊狼 3.0 BLE V3）

- 写特征 0x150A / 通知特征 0x150B（服务 0x180C），电量 0x1500；每 100ms 一条 20 字节 B0 帧（序号+强度模式+双通道强度+双通道 4×25ms 波形）。
- **BF 指令可写"AB 通道强度软上限 + 两个波形平衡参数"**，断电保存，重连必须重写 —— 如果未来做蓝牙直连模式，可以把"全局安全上限"直接烧进设备端，比软件钳制更硬。
- 本项目当前架构走 App 中转，蓝牙直连属于可选长期方向（Coyote-ESP32 等社区项目证明可行），不阻塞玩法设计。

### 3.3 V4 / Relay

- 官方控制方地址 `wss://trex.dungeon-lab.cn/v4`，官方开源 `dglab-kit`（TS）/`dglab-kit-python`（Python）与官方 Relay 服务端实现 `dglab-websocket-server`；现有自研 V4 控制器与官方 RPC 帧一致，无需改动协议层。
- `clientId + slotId + channel` 寻址天然支持**多 App / 多设备**：玩法上可扩展"多设备角色分配"（见玩法 C5）。

### 3.4 生态项目可借鉴机制

| 项目 | 机制 | 值得借鉴 |
|---|---|---|
| hyperzlib/DG-Lab-Coyote-Game-Hub | 游戏中心：osu!、艾尔登法环等；HTTP 插件 API | **服务端统一钳制上限**；`strength add/sub/set` + `randomStrength` 双层强度；"一键开火"限幅（强度≤40、时长≤30s、可叠加/重置）；波形查询/设置接口；蓝牙直连降延迟 |
| CrimsonSeraph/DG-LAB-Client | JSON 规则引擎 | 规则级联（parents 引用其他规则）、占位符表达式、空值忽略、循环保护、范围钳制 |
| Ljzd-PRO/HL2-DGLabInjuryExperienceMod | 半条命 2 伤害模组 | **按伤害量分档触发不同强度**（轻伤/重伤/濒死） |
| VRChatNext/Shocking-VRChat | OSC → WS | 输入源抽象（游戏事件只是输入源之一） |
| ltx4jay/Coyote-ESP32 | ESP32 蓝牙直连 | 蓝牙直连可行性参考 |
| Minecraft/战雷 B站联动视频 | 社区玩法 | "战败惩罚"、"受击电击"是已被验证的大众化玩法 |

---

## 4. 设计总原则

1. **安全第一**：任何新玩法必须服从全局硬上限、冷却、渐变与紧急停止（见第 6 章）；玩法可以激进，安全机制不可绕过。
2. **数据可信性**：所有新玩法沿用"仅有效对局（`map_info` valid）内输出，离开对局全归零"的既有铁律；`/hudmsg` 游标跨局复用的既有语义不变。
3. **玩法=规则，不改内核**：新玩法统一收敛为"触发器 → 规则 → 输出"的规则引擎，不往 `main.py` 里堆 if；每个玩法可独立开关，默认关闭（除安全机制）。
4. **词条实测先行**：一切基于 HUD 文本的新事件，先做七语言词条收集（R7 方法），未验证词条不上线。
5. **性能预算**：200ms 遥测轮询不变；`/map_obj.json`、`/mission.json` 低频轮询（1s）；文本匹配全部走既有 `_normalize` 后的正则缓存；GUI 刷新节奏不变。

---

## 5. 玩法设计

优先级说明：★=P0（第一批，价值高/风险低/数据已验证），☆=P1（第二批），○=P2（有前置不确定项或工作量大）。

### 5.1 常态映射增强（不新增端点）

#### A1 映射曲线类型 ★

- **想法**：现有线性太"温"。增加曲线选项，让同样的 G 值范围产生不同的体感节奏。
- **曲线**：线性（现状）/ 阶梯（每 2G 一档，跳变更有"过载警告"感）/ 缓入陡出（高 G 区输出陡增，逼迫玩家敬畏大过载）/ 平滑 S 形。
- **实现**：`MappingEngine` 增加 `_curve(value, ratio)` 归一化变形函数，配置项 `curve: linear|step|ease_in|smooth`，阶梯数 `curve_steps`。UI：触发设置页一组单选。
- **风险**：无新数据依赖，纯本地。

#### A2 多源叠加常态映射 ★

- **想法**：常态强度不再只看一个指标，多指标各算各的归一化值，取**最大值**输出（叠加但不会爆表）。
- **空战可叠源**：过载（现状）＋失速告警（AoA 超阈值）＋超速告警（IAS/M 超阈值）＋低油量（Mfuel/Mfuel0 < X%）。陆战可叠源：速度（现状）＋乘员损伤比例＋模块损坏数量。
- **实现**：每个源产出 `(enabled, normalized)`，仲裁层 `intensity = max(各源) × 通道最大值`。配置在 aircraft/tank 段内扩展 `sources: {gforce: {...}, stall: {...}, overspeed: {...}, fuel: {...}}`。
- **UI**：触发设置页每个常态源一行：开关 + 上下限/阈值。默认全部保持现状（只开过载/速度），用户逐个加。

#### A3 油量焦虑 ☆

- **想法**：油量低于阈值后，背景强度随油量线性上升——"油少了身上越来越疼"，倒逼玩家规划返场。
- **数据**：`Mfuel / Mfuel0`（空战）。阈值可设（默认 20% 起感，0% 满强度）。
- **归属**：作为 A2 的一个源实现。

#### A4 陆战损伤映射（补全 R2）★

- **想法**：原需求 R2 的"损伤→强度"一直没做。用乘员与模块状态合成损伤比例：`损伤比例 = w1×(阵亡乘员/总乘员) + w2×(损毁模块/关键模块数)`，映射到背景强度。
- **数据**：`/indicators` 的 `crew_*`、`*_state` 字段（项目已解析乘员与模块）。
- **实现**：`MappingEngine.map_tank_damage(damage_ratio, ...)`；作为陆战 A2 叠加源；权重默认各 0.5，可配置。与维修事件互斥逻辑沿用现有边沿检测。

### 5.2 事件触发类

#### B1 被命中 ☆

- **想法**：被打一炮就来一下短脉冲——比"被摧毁"早得多、频繁得多的反馈，是空陆通用的高频事件。
- **数据**：`/hudmsg` damage 中"命中类"词条（七语言实测收集；英文社区样本为 "…has hit…" 系列）。
- **输出**：默认 3s、低强度（建议默认≤40）、可随机换波；**冷却 2s**（防连射刷屏）。
- **配置**：`tank_events/aircraft_events` 增加 `hit_enabled / hit_ch_a/b / hit_duration / hit_wf_a/b / hit_random_a/b / hit_cooldown`。

#### B2 暴击/模块损坏 ☆

- **想法**：暴击（critical hit）或己方模块被打坏（炮闩、履带、发动机）→ 中强度脉冲，比 B1 更痛。
- **数据**：HUD "critical" 词条；己方模块损坏用 `/indicators` 模块字段**边沿检测**（0→非0），比文本更可靠且免翻译——**优先用 indicators 边沿**，HUD 暴击作为空战补充。
- **输出**：4s，默认中强度；冷却 3s。断履带、炸炮闩这类"大件"可单独配置更高强度（进阶：按模块重要性加权）。

#### B3 起火 ☆

- **想法**：起火=大危机，给一个"灾难级"强脉冲，火扑灭前持续低强度"灼烧感"（如果有灭火能力，灭火后停止）。
- **数据**：HUD "set afire" 词条（该词条已从官方文档和 Reddit 样本双重确认存在，是除击杀/坠毁外最有把握的文本事件）；起火持续可用低频 HUD 文本或温度字段辅助〔需实测〕。
- **输出**：触发瞬间 5s 强脉冲；后续"灼烧"作为持续源叠加（`afire_burn_intensity`，默认低）。

#### B4 乘员阵亡 ○

- **想法**：陆战每个乘员阵亡单独一记重脉冲——"车上的人一个个没了"。车长阵亡可加特殊提示。
- **数据**：`/indicators` 乘员字段边沿（0→1）。已在解析，实现成本低。
- **依赖**：B2 的边沿检测框架。

#### B5 弹药架殉爆 / 一击致命 ○

- **想法**：被一发入魂（从满血直接摧毁）与普通被摧毁区分开，殉爆给最大档脉冲——"死也要死得响"。
- **实现**：-death 事件触发时检查上一周期乘员/血量状态是否接近满值；或 HUD 中摧毁与命中间隔 <500ms。属体验加分项，P2。

#### B6 被锁定告警（雷达锁定/导弹告警）☆

- **想法**：现代喷气机玩法的灵魂——被雷达锁定后持续"嘀嘀"脉冲，锁定解除才停；导弹来袭升级为连续强脉冲。
- **数据**：首选 `/indicators` 雷达/告警字段〔**需实测确认 8111 是否暴露**〕；**若 8111 无此数据，用 `/map_obj.json` 近似**：敌机距离 <R km 且接近中（距离变化率为负）→ 按距离映射"紧张感"强度。此近似玩法独立命名为 B7。
- **输出**：持续源（不是脉冲），锁定期间 `intensity = 比例 × 上限`，锁定解除 500ms 内滑落为 0。

#### B7 敌机接近 / 被咬尾 ★（数据已验证，价值最高的新玩法）

- **想法**："地图上有敌机在逼近"本身就是恐惧。敌机越近、越在尾巴后面，背景强度越高——把小地图的战场感知变成身体感知。
- **数据**：`/map_obj.json`（500ms~1s 轮询）+ `/map_info.json` 尺寸换算距离；玩家自身 `icon=="Player"`；敌机=`aircraft` 且颜色≠我方；咬尾判定=敌机在我机后方扇区（我机航向与敌机方位夹角 >120°）且距离 <1500m 且接近中。
- **输出设计**（持续源）：
  - `d ≥ D_far`（默认 5km）：0；
  - `D_close(800m) ≤ d < D_far`：线性上升至 `proximity_max`（默认 60）；
  - 咬尾命中时：在接近强度上再 +`tail_max`（默认 30，钳制在全局上限内）；
  - 最近敌机多架时取最近一架；也可配置"数量加成"（1v3 的绝望感）。
- **实现**：新增 `ProximityTracker`（`src/proximity_tracker.py`）：输入 map_obj+map_info，输出 `nearest_dist / closing_rate / tail_angle`；轮询放独立低频线程，结果由主循环合并进 A2 叠加层。空战/陆战都可开（陆战对敌地面单位同理：`ground_model` 距离）。
- **风险**：低——纯地图公开信息，无透视问题；请求频率低。**注意 map_obj 归一化坐标异常值（如重生点 dy=±300）要过滤。**

#### B8 投弹/打火箭/放干扰弹 ☆

- **想法**：投放武器给一个"卸货"脉冲：丢炸弹→短促两连；放干扰弹→每枚一个极短"滴"。既是反馈也是弹药计数确认。
- **数据**：首选 `/state` 挂载/干扰弹计数字段〔需实测〕，备选 `/indicators` 弹药计数边沿；都不可用则降级为"HUD 命中词条中含 bomb/rocket 来源时触发"。
- **输出**：50~100ms 级极短脉冲（用一帧 8 字节波形实现），强度可配置。**注意高频短脉冲的总强度预算**（见第 6 章）。

#### B9 击杀连击 ☆

- **想法**：20 秒内连续击杀，每杀强度升级（10/20/35/55…），配合悬浮窗显示 x2/x3——把"杀疯了"变成滚雪球的刺激。
- **实现**：EventEngine 内置 `streak` 计数器（窗口可配，默认 20s），`kill_ch = base × (1 + streak × step)`，钳制全局上限。击杀间隔超窗或死亡清零。

#### B10 战局惩罚 ○

- **想法**：比分落后或任务目标失败时，队伍一起"疼"：目标 failed → 全员强脉冲一次；胜利 → 奖励波形（见 C4）。
- **数据**：`/mission.json` 的 `objectives[].status` 边沿（in_progress→failed）；比分字段若实测存在则做"分差映射"（落后越多背景越强，上限 40）。
- **风险**：比分字段存在性未确认；objectives 文本多语言。先做 objectives 边沿，比分做实验特性。

#### B11 着陆判定 ○

- **想法**：把着陆做成小游戏：接地垂直速度超阈值（硬着陆）→ 惩罚脉冲；平稳接地（<2m/s）→ 奖励短波形。空战党练技术的新动力。
- **数据**：`Vy`（接地瞬间）+ `gear, %`〔需实测〕 + `H, m` <50m 的组合边沿。
- **输出**：惩罚按 |Vy| 分档；奖励用 C4 的" Success "波形播放 2s。

#### B12 随机轮盘（俄式轮盘）★

- **想法**：开启后每 N 秒掷骰子，X% 概率来一发随机强度（0~上限内随机）随机时长的脉冲——什么都不做也可能挨电，紧张感拉满，直播效果极佳。
- **实现**：独立定时器 + 全局上限钳制；配置 `roulette_enabled / roulette_interval_min,max / roulette_chance / roulette_strength_max / roulette_duration_max`。属于"事件"页的一个开关。
- **注意**：默认关闭；概率与强度上限默认保守（10%、≤60）。

#### B13 死亡连坐（惩罚递增）☆

- **想法**：每次被摧毁，全局强度系数 +10%（可配），死得越多常态越疼；下机/重开对局清零。防摆烂机制。
- **实现**：EventEngine 计数器，乘在常态映射结果上；配置 `escalate_enabled / escalate_step / escalate_cap`。

### 5.3 互动与综合玩法

#### C1 手机端互动（副驾/观众遥控）★

- **想法**：V3 App 上有 10 个反馈按钮（每通道 5 个）和手动强度加减——现在程序完全没监听。把它们变成玩法入口：
  - **副驾模式**：朋友拿手机，A 通道按钮"加电/减电"，B 通道按钮触发预设事件（如"轮盘一发"）——现实版"后座武器官"；
  - **主播模式**：手机放弹幕助手手里，观众投票决定惩罚。
- **实现**：V3 控制器增加 feedback 消息监听（PyDGLab-WS 已暴露反馈按钮事件），映射为可配置动作表（加电/减电/设值/触发某事件/换波形）；V4 协议有对应能力〔需按 V4 帧实测〕。
- **UI**：连接页新增"手机端互动"配置卡（动作映射表）。默认关闭。

#### C4 内置程序化波形库 ☆

- **想法**：不依赖用户找 `.pulse` 文件，内置一批程序生成波形，事件/奖励直接引用：
  - `心跳`（60→140bpm 随强度加速）、`警报脉冲`（双短一长）、`地震`（低频连续）、`爬升`（幅度阶梯上升）、`脉冲串`（机关枪）、`奖励波浪`（平滑正弦包络）。
- **实现**：`WaveformCatalog` 增加虚拟条目（生成器函数产出 `(freq[4], amp[4])` 元组序列，循环填充 8 字节帧），与现有随机换波、输出遥测零冲突；UI 波形下拉框自动多出这些条目（带 ⚙ 前缀标识内置）。

#### C5 多设备支持（V4）○

- **想法**：V4 寻址天然支持多设备。角色化：设备 1 = 主设备（常态+事件），设备 2 = 惩罚设备（只吃事件/轮盘）——或双人各接一台，A 玩家吃空战、B 玩家吃陆战。
- **实现**：V4 控制器从"选第一台"升级为设备池 + 每设备角色配置；通道指令按角色路由。工作量大，放 P2。

#### C6 本局战报 ☆

- **想法**：对局结束（`map_info` valid→false）时，弹出/悬浮窗显示本局：最大 G（`g_meter_max` 或自采样）、最大速度、被电总时长、触发事件次数 Top3、死亡次数与总强度积分——给用户"看得见的代价"，也方便调参。
- **实现**：EventEngine/仲裁层累计计数（纯内存 + 可选落盘 `stats/` 目录），对局结束边沿触发展示。

---

## 6. 安全设计（新增玩法的强制底座）

现有安全资产：离开对局归零、异常回退、App 端上限。新增四层：

1. **全局硬上限 `global_max`（P0）**：主界面显眼滑条（默认 80，最大 200）。**所有**玩法输出（常态、事件、轮盘、手机互动）先经 `min(value, global_max)` 再下发。UI 上任何强度的显示都以钳制后为准。
2. **事件冷却与限频（P0）**：每类事件独立冷却（hit 2s / critical 3s / fire 30s…）；全局突发限频器：任意 10 秒窗口内"事件型"输出总时长 ≤6s（超出的排队丢弃，悬浮窗提示"已限流"）。参照 Game Hub"一键开火限幅"经验。
3. **渐变 Ramp（P1）**：常态映射的 tick 间强度变化限速（默认每 100ms ≤10）；事件脉冲不受限（要的就是突然）。断崖式 map_obj 接近强度尤其需要 ramp 防抖。
4. **紧急停止（P0）**：全局热键（默认 `Ctrl+Alt+X`）+ 托盘菜单项：立即 `clear_all` 并冻结所有触发 30s（悬浮窗红字提示）；冻结期可再按一次立即恢复。事件页提供"单事件试玩"按钮（强度走 `global_max` 钳制，时长≤30s）。

另外：README 与注意事项补充"新玩法默认关闭、逐个开启、先低后高"的使用指引。

---

## 7. 技术实现方案

### 7.1 架构演进：触发规则引擎

```
GameReader(200ms 遥测) ─┐
MapObjReader(1s 低频)  ─┤→ DataBus(GameState 扩展)
MissionReader(1s 低频) ─┘        │
                                 ▼
EventEngine(原 EventDetector 扩展)
  ├─ HudTextDetectors(命中/暴击/起火…)   → 一次性事件
  ├─ EdgeDetectors(乘员/模块/弹药/目标)  → 一次性事件
  ├─ StreakTimer / EscalationCounter     → 修饰器
  └─ ProximityTracker(map_obj)           → 持续源
                                 ▼
Arbitrator（新模块 src/arbitrator.py，主线程 tick 内调用）
  output = clamp( max(常态叠加层, 持续源层, ramp(事件脉冲)) ,
                  global_max, 通道上限, 限频器 )
                                 ▼
CoyoteController / CoyoteV4Controller（接口不变）
```

- **数据层**：`GameReader` 增加 `fetch_map_objects()`、`fetch_mission()`（独立低频轮询线程，带异常静默）；`GameState` 增加 `mission`、`map_objects`、派生字段（`nearest_enemy_dist` 等）。保留 raw 字典以便调试导出。
- **事件层**：`EventDetector` 保持 HUD 文本匹配职责并扩展词条；新增边沿/窗口/接近检测器。事件字典统一扩为 `{kind, mode, ch_a, ch_b, duration, wf_a, wf_b, cooldown, priority}`。
- **仲裁层**：把 `main.py::_apply_game_state` 中"事件覆盖/常态映射"的分支逻辑下沉为 `Arbitrator.resolve(state, active_events, config) -> (intensity_a, intensity_b, label)`。`main.py` 只负责 UI 与下发。**这步是所有新玩法的前置重构，建议单独一个 PR + 回归测试先行。**
- **配置层**：`config.default.json` 扩展示例（向后兼容：缺键用默认值，现有校验器按段扩展）：

```json
"aircraft": {
  "curve": "linear", "curve_steps": 5,
  "sources": {
    "gforce":   {"enabled": true, "min": 1.0, "max": 10.0},
    "stall":    {"enabled": false, "aoa_deg": 14, "intensity": 40},
    "overspeed":{"enabled": false, "max_ias": 900, "intensity": 30},
    "fuel":     {"enabled": false, "pct_start": 20, "intensity": 50},
    "proximity":{"enabled": false, "far_km": 5.0, "close_km": 0.8, "max": 60, "tail_bonus": 30}
  }
},
"events_extra": {
  "hit":     {"enabled": false, "ch_a": 40, "ch_b": 40, "duration": 3.0, "cooldown": 2.0, "wf_a": "恒定", "wf_b": "恒定"},
  "fire":    {"enabled": false, "ch_a": 90, "duration": 5.0, "cooldown": 30.0, "burn": 15},
  "roulette":{"enabled": false, "interval_min": 30, "interval_max": 90, "chance": 0.1, "max": 60}
},
"safety": {
  "global_max": 80,
  "burst_window_s": 10, "burst_max_event_s": 6,
  "ramp_per_tick": 10, "freeze_hotkey": "Ctrl+Alt+X", "freeze_seconds": 30
}
```

- **UI 集成**：触发设置页常态区改为"映射源列表"（每源一行：开关+参数）；事件区新增事件行模板（开关/强度/时长/冷却/波形/随机/试玩按钮）；连接页加手机互动卡；状态栏加"紧急停止"红色按钮 + 全局上限滑条。
- **多语言词条**：新增 HUD 词条按 R7 流程：游戏内实测七语言样本 → 写入 `PASSIVE/ACTIVE/CRASH` 同级的 `HIT/CRITICAL/FIRE` 常量组 → 回归测试加真实样本。

### 7.2 性能与健壮性要点

- map_obj 解析每秒 ≤1 次，对象数几百个内纯 Python 足够；坐标异常值（|dy|>1 的重生点类）过滤。
- 所有新端点请求失败静默降级（玩法自动失效，不影响既有输出），沿用 `fetch_hudmsg_with_status` 的成败分离模式。
- HUD 高频文本（hit 可能每秒多条）依赖冷却与限频器，而不是靠匹配丢弃。
- 测试：延续 pytest 惯例，新增 `test_arbitrator.py`、`test_proximity.py`、`test_event_extra.py`、`test_safety_limits.py`；现有 175 项回归必须保持绿。

---

## 8. 分期落地路线图

| 优先级 | 内容 | 前置依赖 | 预估量级 |
|---|---|---|---|
| **P0** | 仲裁层重构 Arbitrator；全局硬上限；紧急停止热键；事件冷却/限频；B12 随机轮盘；B7 敌机接近/咬尾（数据已验证，体验增益最大） | 无 | 各 1~2 天 |
| **P0.5** | 字段实测：抓取 `/state` 起落架/挂载/极值字段、`/indicators` 弹药/油量/雷达字段、`/mission.json` 比分字段，固化到本文档 | 实机对局 | 半天 |
| **P1** | A1 曲线、A2 多源叠加、A4 陆战损伤映射、C1 手机端互动、C4 内置波形、B1/B2/B3 HUD 新事件（先收词条）、B9 连击、B13 递增、C6 战报、渐变 Ramp | P0 仲裁层 | 每项 0.5~1.5 天 |
| **P2** | B6 被锁定（视 8111 字段实测结果）、B10 战局惩罚、B11 着陆判定、B5 殉爆、C5 多设备、蓝牙直连 BF 软上限 | P0.5 实测结论 | 视结论 |

## 9. 开放问题（需实机确认清单）

1. `/state` 是否含 `gear/airbrake`、挂载计数、`IAS max` 等滚动极值字段；字段大小写实况。
2. `/indicators` 空战时是否有雷达/RWR/导弹告警、干扰弹计数、油量、火警字段（决定 B6/B8 走哪条数据通路）。
3. `/mission.json` 是否含比分/玩家字段（决定 B10 的形态）。
4. HUD 命中/暴击/起火词条的七语言精确格式（复用 R7 收集方法）。
5. V3 App 反馈按钮在 PyDGLab-WS 事件流中的实际载荷格式（C1 开发前确认）；V4 是否有等价交互。

---

## 10. 参考资料

**战雷 8111**
- WarThunder-localhost-documentation（端点文档）：https://github.com/lucasvmx/WarThunder-localhost-documentation
- WarThunder（Python 遥测库）：https://github.com/PowerBroker2/WarThunder
- 官方论坛"使用 8111 的工具"：https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664
- 官方论坛"LAN API 是唯一合规数据源"：https://forum.warthunder.com/t/why-dont-we-have-an-api-for-war-thunder/90815?page=3
- 8111 汇总帖（Reddit）：https://www.reddit.com/r/Warthunder/comments/f4p8g1/link_localhost8111_api_docs/

**DG-LAB 官方开源（dungeonlab-open）**
- Socket 控制协议 V2（郊狼3.0，二维码/消息/波形帧/错误码）：https://github.com/dungeonlab-open/dglab-websocket-simple （`socket/v2/README.md`）
- 蓝牙协议（郊狼 V3 BLE：B0/BF/B1 帧、软上限、频率压缩映射）：https://github.com/dungeonlab-open/dglab-bluetooth-protocol （`coyote/v3/README.md`、`coyote/README.md` 波形解释）
- 官方 Python 工具包：https://github.com/dungeonlab-open/dglab-kit-python
- 官方 Relay 服务端：https://github.com/dungeonlab-open/dglab-websocket-server

**社区项目**
- PyDGLab-WS（本项目 V3 底层库）：https://github.com/Ljzd-PRO/PyDGLab-WS
- DG-Lab-Coyote-Game-Hub（游戏中心 + HTTP 插件 API + 限幅机制）：https://github.com/hyperzlib/DG-Lab-Coyote-Game-Hub （插件 API：`docs/api.md`）
- DG-LAB-Client（JSON 规则引擎：级联/占位符/钳制）：https://github.com/CrimsonSeraph/DG-LAB-Client
- HL2-DGLabInjuryExperienceMod（按伤害分档电击）：https://github.com/Ljzd-PRO/HL2-DGLabInjuryExperienceMod
- Shocking-VRChat（OSC 输入源抽象）：https://github.com/VRChatNext/Shocking-VRChat
- Coyote-ESP32（蓝牙直连硬件方案）：https://github.com/ltx4jay/Coyote-ESP32
- AliceInCradle_X_DGLAB（第三方游戏接入 Game Hub API 案例）：https://github.com/sllying/AliceInCradle_X_DGLAB
- 官方论坛"手柄震动→DG-Lab"：https://forum.dg-bbs.com/d/33
