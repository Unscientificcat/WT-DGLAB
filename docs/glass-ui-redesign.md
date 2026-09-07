# WT-DGLAB UI 重构执行文档 v3.2：浅色磨砂玻璃主题（Glassmorphism）

> **本文档即完整执行规范**，自带全部设计参数与红线，不依赖执行方环境中的任何 skill 或外部上下文。
> 执行者：GPT。制定日期：2026-09-05。前置会话结论已全部沉淀在本文档中。

---

## 一、目标与范围

把现有"淡蓝白扁平"界面重构为**浅色磨砂玻璃（glassmorphism）**风格：窗口底层铺一张背景图，各功能模块（顶栏、实时状态、参数设置、连接面板、设置区块、注意事项对话框）改为半透明白玻璃圆角卡片，卡片背后透出模糊后的底图。视觉基调保持明亮轻量，数据与可读性始终优先于装饰。

**只动 UI 层**：

- `src/gui/*`（样式重写 + 新增 glass 模块 + 接入）
- `src/config_manager.py`（新增 2 个配置字段）
- `build.py`（打包资源）
- `config.default.json`、`AGENTS.md`、`docs/design-spec.md`、`devlog/`

业务逻辑（游戏读取、强度映射、波形、事件检测、郊狼通信）不重构、不改行为。

### 现状速览（供执行者定位）

- 技术栈：PySide6（Qt Widgets）+ Fusion 风格 + 全局 QSS（`src/gui/styles.py` 中的 `COLORS` 与 `STYLESHEET`），中文界面，代码直构建控件。
- 主窗口 `src/gui/main_window.py`（约 1500 行）：`StatusBar`（品牌+状态 pill）、`Dashboard`（实时 G/速度、A/B 通道、悬浮窗控制、刷新间隔）、`SettingsPanel`（参数/波形切换 + 空战/陆战页 + 可折叠事件区块）、`WaveformSettingsDialog`（内嵌波形页）、`QRWidget`（二维码 + V3/V4 连接设置）、`MainWindow`（三栏 QSplitter + 托盘 + 启动置顶）。
- 布局：默认 1280×780，最小 1080×660；splitter 三栏约 295/620/285。
- 悬浮窗 `src/gui/overlay.py`：透明置顶文字，大/中/小三档——**本次完全不动**。
- 注意事项 `src/gui/disclaimer_dialog.py`：模态对话框，读 `resources/注意事项.txt`。

---

## 二、已确认的设计决策（用户拍板，不可擅改）

1. **背景图**：EXE 同级 `backgrounds/` 文件夹（完全仿照 `src/waveforms.py` 中 `WaveformCatalog` 的目录模式），用户自行放入图片，设置页中选择生效；默认壁纸使用 `resources/wallpaper_default.png`。
2. **明暗基调**：浅色磨砂（白玻璃卡片 + 深灰蓝文字）。
3. **动效**：轻动效（悬停高光、进度条平滑、事件呼吸灯）；页面淡入为实验项。
4. **游戏内悬浮窗**：完全不动（透明文字方案保留）。
5. **目标环境**：1080p 为主，兼顾高 DPI（按 devicePixelRatio 正确缩放）。

---

## 三、参考项目（已调研，可对照学习）

### 开源 UI 实现

| 项目 | 用法 | 许可证注意 |
|---|---|---|
| [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)（重点读 `acrylic_label.py`） | 技术验证与思路来源：QPainterPath 圆角裁剪、亮度色+tintColor 双层叠加、缓存模糊结果（resize 只重缩放不重模糊）、QThread+信号规避 QPixmap 跨线程 | **GPLv3 非商业**：只参考思路，**禁止复制代码** |
| [BackDrop-in-PyQt-PySide](https://github.com/GvozdevLeonid/BackDrop-in-PyQt-PySide) | 同款"卡片背后模糊底图"视觉基准 + hover 高光动画参考 | demo 级，仅参考 |
| [QT-PyQt-PySide-Custom-Widgets](https://github.com/KhamisiKibet/QT-PyQt-PySide-Custom-Widgets) | 半透明圆角卡片 dashboard 样式参数参考 | 以仓库 LICENSE 为准，默认不引入依赖 |
| [PythonBlurBehind](https://github.com/Peticali/PythonBlurBehind) / [qframelesswindow](https://github.com/zhiyiYo/PyQt-Frameless-Window) | **明确不用**：OS 级窗口背后模糊，本设计不需要，且 Win10 拖动卡顿 | — |
| [CSS glassmorphism 配方](https://gist.github.com/midhunhk/5267be7a9e45a2151aee1731c078ee3a) | 参数基准：blur + 白色叠加 + 细边框 + saturate(180%) | — |

### UI 设计 Skill（Agent Skills 生态）

| Skill | 结论 |
|---|---|
| [TypeUI Glassmorphism skill 文件](https://www.typeui.sh/design-skills/glassmorphism) | **直接对口**，其框架无关的规则已蒸馏进本文件第四节 |
| [Anthropic frontend-design](https://github.com/anthropics/skills)、[superdesign-skill](https://github.com/superdesigndev/superdesign-skill) | 理念可借鉴（反平庸 AI 审美），工作流为 Web 向，不照搬 |
| Qt/桌面专属 skill | **不存在**——故本文件自带完整设计参数 |

**零新增依赖**：模糊与饱和度用项目已有的 Pillow（`ImageFilter.GaussianBlur`、`ImageEnhance.Color`）；自研 `glass.py` 约 200 行。

---

## 四、视觉规范（执行参数）

**设计意图**：玻璃是结构不是装饰——对话框=顶层、面板=中层、内容=底层，用透明度表达空间层级；**玻璃与可读性冲突时永远优先可读性**。

- **玻璃卡片**：圆角 10px；底 = 卡片正后方模糊底图区域 + 白色叠加 **60~75%**（自适应，见下）；边框 1px 低不透明白 `rgba(255,255,255,0.45~0.6)`（edge-light 受光感）；顶部 1~2px 白色高光渐变；**悬停用透明度微增而非换色**；**输入框焦点态用实色主色描边**（半透明描边在模糊背景上不可见）。**不用** QGraphicsDropShadowEffect（每卡一层位图，内存大且文字发虚）。
- **底图**：cover 模式铺满窗口（保纵横比居中裁切）；**先饱和度 ×1.15（`ImageEnhance.Color`）再高斯模糊半径≈32**；**模糊图按逻辑分辨率生成**，Qt 按 dpr 放大绘制（模糊图放大无画质损失，4K 省 4 倍内存与计算）。
- **磨砂质感**：模糊层上叠 64×64 噪点纹理平铺，透明度 0.03（"真磨砂"与"半透明色块"观感差距的关键）。
- **自适应对比度（防深色壁纸毁界面）**：加载壁纸时一次性计算平均亮度；暗图白色叠加升至 0.75、亮图用 0.6；模糊图上的可读性滤罩 `rgba(244,247,252,0.25~0.4)` 联动调整。
- **层间距**：卡片间距 ≥10px（现有 10~12px 保留），防止相邻模糊边界糊成噪音。
- **文字与状态色**：沿用现有色板——正文 `#26364A`、次要 `#718095`、主色 `#4B89D8`、事件粉 `#EC8DA7`、成功 `#46B68A`、错误 `#E36D7D`。
- **QR 区域永远纯白底**，不受玻璃主题影响，保证手机可扫。
- **按钮**不做逐个背景裁切（每按钮裁一次太浪费），用"半透明色填充 + 细边框"近似玻璃质感。
- **回退（可访问性护栏）**：壁纸缺失/损坏/开关关闭 → 淡蓝渐变底 + 不透明白卡片（等效现状样式），**绝不白屏、绝不抛异常**。
- **只支持静态图**：jpg/jpeg/png/webp/bmp；不支持 GIF；低分辨率壁纸可用（反正要模糊）。
- **玻璃语言完整清单**（缺一个都会显得突兀）：`StatusBar`、`Dashboard`、`QRWidget`、全部 `sectionCard`、波形页 4 个 QFrame（header/nav/editor/footer）、可折叠事件区块、注意事项对话框；滚动条、下拉框弹出层、托盘菜单 QMenu 同步调整。GlassCard 自身及内部所有容器 QSS 一律 `background: transparent`，**逐个排查**滚动区视口（QScrollArea viewport）与 QStackedWidget 页面，防止 QSS 底色盖住模糊图。

---

## 五、技术路线（性能核心 + 已识别坑位）

**核心原则：模糊只算一次，卡片只做裁切。** 这保证了运行时开销近零。

1. **模糊管线**（新模块 `src/gui/glass.py`）：
   - 加载/换图时**在 GUI 线程同步执行**：Pillow 读图 → 饱和度 → cover 缩放至窗口逻辑尺寸 → 高斯模糊 → 转 QImage → QPixmap 缓存。
   - **不做异步**：QPixmap 不能跨线程创建（子线程只可产 QImage），同步几十毫秒用户无感，且避免"先见灰底、壁纸突然弹出"的首帧跳变。
   - 窗口 resize：进行中先用旧缓存拉伸顶替，停止 250ms（QTimer 防抖）后重算。
2. **`BackdropCanvas(QWidget)`**：central widget 底层，不透明绘制原图 + 滤罩 + 噪点（防闪烁）；持有模糊缓存与版本号；保持 `QWidget#appSurface` 的结构定位。
3. **`GlassCard(QFrame)`**：paintEvent 中把自身 rect `mapTo(window)`，从模糊缓存裁切对应区域 → QPainterPath 圆角裁剪 → 白色叠加 + 边框 + 顶部高光。
   - **缓存失效策略（否则 splitter 拖动背景错位）**：moveEvent、resizeEvent、模糊缓存版本号变化时重新裁切。
4. **`BackgroundCatalog`**：完全仿照 `WaveformCatalog`（`src/waveforms.py:158`）：`application_directory()/backgrounds`，按需 `ensure_directory()`，扩展名白名单扫描，`choices()` 返回 `["默认壁纸", *文件名]`。
5. **动效**：
   - QSS `:hover`（按钮/卡片）；
   - `ChannelCard` 进度条用**单个 QVariantAnimation 实例**持续追踪新目标值（**禁止**每 100ms tick 新建动画对象，会定时器风暴）；
   - 事件触发时实时状态卡片粉色呼吸灯边框（QPropertyAnimation 循环，事件结束停止）；
   - 设置页切换淡入（QGraphicsOpacityEffect）为**实验项**：实测子控件渲染异常/文字发虚则移除；
   - 多显示器：监听 `windowHandle().screenChanged` 重建缓存（不同屏 dpr 不同）。
6. **内存**：全窗口原图 + 逻辑分辨率模糊图 ≈10MB@1080p；换图时释放旧缓存。

---

## 六、文件级任务清单

| 文件 | 动作 |
|---|---|
| `src/gui/glass.py` | **新建**：`BackdropCanvas`、`GlassCard`、`BackgroundCatalog`、模糊管线、亮度自适应、噪点纹理 |
| `src/gui/styles.py` | **重写 QSS** 为玻璃主题；`COLORS` 字典**既有键全保留**（`StatusPill.set_connected` 依赖 success/error 键） |
| `src/gui/main_window.py` | 背景层接入（BackdropCanvas 垫底 + 原三栏结构上移）；各面板 GlassCard 化；设置面板顶部按钮组从 **[参数设置\|波形设置]** 扩为 **[参数设置\|波形设置\|外观设置]**（复用 `_show_parameter_page` 的页面切换模式）；外观页 = 背景下拉框 + 打开背景文件夹按钮 + 启用背景开关；**选择背景立即应用并立即持久化**（对齐 V3/V4 协议切换的即时生效行为，不等"保存设置"） |
| `src/gui/disclaimer_dialog.py` | 仅视觉：铺底图 + 玻璃卡片化（静态模糊，一次性），逻辑不动 |
| `src/config_manager.py` | `AppSettings` 新增 `background_enabled: bool = True`、`background_image: str = ""`（空=默认壁纸，非空=backgrounds/ 内文件名）；旧配置缺字段由 dataclass 默认值兼容 |
| `config.default.json` | 同步增加上述两字段 |
| `resources/wallpaper_default.png` | 默认壁纸资源；缺失时回退淡蓝底，不影响程序启动 |
| `build.py` | PyInstaller 收集新壁纸资源 |
| `tests/test_glass_theme.py` | **新建**（`QT_QPA_PLATFORM=offscreen`）：BackgroundCatalog 扫描/回退、config 新字段往返、GlassCard 离屏绘制冒烟、无效文件名与文件被删回退、壁纸缺失不崩溃 |
| `docs/design-spec.md` | 更新为玻璃主题视觉规范 |
| `devlog/YYYY-MM-DD.md` | 记录当日完成与待办 |
| `AGENTS.md` | 项目结构清单补 `src/gui/glass.py` 一行 |
| `src/gui/overlay.py` | **不改** |
| `main.py` | **预期不改**（见第七节软约束） |

**配置安全收口**：`background_image` 只允许是 `backgrounds/` 内的文件名——拒绝路径分隔符与 `..`，扩展名白名单，Windows 大小写用 casefold 匹配；启动时文件不存在 → 回退默认壁纸并清空该字段。

---

## 七、约束（双层，优先级从高到低）

### 硬约束——业务行为不得改变

游戏数据解析结果、强度映射公式、事件触发语义与安全归零、`config.json` 既有字段含义、托盘/单实例/启动置顶/关闭最小化到托盘的行为。

### 软约束——文件优先不改，判断权在执行者

优先不动 `main.py`、`game_reader.py`、`mapping_engine.py`、`coyote_controller.py`、`coyote_v4_controller.py`、`event_detector.py`、`waveforms.py`、`single_instance.py`。**若执行者判断确有必要（如接口适配），允许最小化修改，但必须在交付说明中列出每个改动的文件与理由。**

尽量保留的 GUI 对外接口（`main.py` 依赖）：

- `status_bar.set_wt_status()` / `set_coyote_status()`
- `dashboard.update_aircraft()` / `update_tank()` / `update_event()` / `show_event()` / `clear()` / `set_overlay_callback()` / `overlay_var`
- `qr_widget.set_status()` / `set_qr_image()` / `clear_qr_image()` / `set_protocol()` / `get_protocol()` / `ws_port` / `v4_relay_url`
- `dashboard.get_mode()` / `save_settings()` / `save_button`
- `window.after()` / `run()` / `quit()` / `get_mode()` / `get_config()` / `show_startup()` / `restore_from_tray()` / `save_current_settings()` / `set_close_callback()` / `overlay_enabled` / `overlay_size`

尽量保留的测试依赖 objectName（现有 108 项测试引用）：

- `status_bar.brand_mark`（38×38 pixmap）、`dashboard.refresh_ms`、`settings_panel.save_button`、`settings_panel.cas_enabled`、`qr_widget` 不得有 `refresh_ms`、各 `NoWheel*` 控件、悬浮窗尺寸档
- 窗口标题保持 `郊狼雷霆 v1 beta_3`（`test_gui_branding.py` 精确断言），**本次不升版本号**

**测试规则**：确需调整接口/对象名时，同步适配对应测试，**只许适配结构、不许削弱断言**；全量测试保持绿色。

代码风格：中文注释 + PEP8 + `setObjectName` 机制照旧。测试运行在项目根创建 `backgrounds/` 空目录属预期行为（与现有 `waveforms/` 一致）。

---

## 八、实施顺序（每步可独立验证）

1. `glass.py` + config 字段 + `tests/test_glass_theme.py` → 单独跑通
2. `styles.py` QSS 重写 → 离屏冒烟测试
3. `main_window.py` 接入背景层、卡片化、外观设置页 → 原生截图检查
4. 注意事项对话框视觉
5. 全量 `pytest`（现有测试必须全绿）+ 1280×780 / 最小 1080×660 / splitter 拖动 / 深浅两张壁纸对比截图（**含最坏情况：深色杂色壁纸下文字对比度**）
6. `build.py` + 文档收尾（design-spec、devlog、AGENTS.md）

---

## 九、验收标准

- [ ] 全量 pytest 通过；无 WT/无设备环境可正常启动
- [ ] 清空 `backgrounds/`、关闭背景开关、壁纸文件被删三种情况均回退正常，无异常无白屏
- [ ] 1080p 与最小窗口无裁切重叠；splitter 拖动、窗口缩放时玻璃背景跟随正确无错位
- [ ] resize 防抖无明显卡顿
- [ ] 深色壁纸下文字对比度合格
- [ ] 背景选择即时生效、即时持久化，重启后保持
- [ ] PyInstaller 打包成功且包含默认壁纸

---

## 十、性能结论（已与用户确认）

启动时同步模糊多花几十毫秒（用户无感）；运行时每帧只裁切缓存图，无逐帧模糊；内存增加约 10MB@1080p；动效全 CPU 侧、开销可忽略。提供"启用背景"开关兜底低端机。

---

## 十一、待用户提供

默认壁纸位于 `resources/wallpaper_default.png`（建议 1920×1080 及以上，JPG/PNG）。

可选增强：将 [TypeUI Glassmorphism skill 文件](https://www.typeui.sh/design-skills/glassmorphism) 原文粘贴给执行方作为补充设计上下文（本文件已含其核心规则，非必需）。
