# 开发方案：模式切换按钮迁移至仪表盘

> 本方案面向实施者，包含完整的现状机制、改动规格与验收标准。项目为 PySide6 桌面程序，工作目录为项目根目录，遵循 AGENTS.md 工作方式（中文注释、PEP8、完成后更新 devlog）。**注意：只做本方案内容，不要顺手改其他功能。**

## 一、需求与已确认的设计决策

1. 模式（空战/陆战）切换按钮从"触发设置"面板移到**左侧仪表盘**遥测卡数值右侧的空白处，形式为**上下双按钮**（空战在上、陆战在下），当前模式高亮。
2. 触发设置里的按钮**只保留切换设置页的功能**（查看空战设置页/陆战设置页），不再切换实际业务模式，文字改为**"空战设置"/"陆战设置"**。
3. **互不联动**：仪表盘切换模式后，触发设置的查看页**不**自动跟随；设置页只受设置里的按钮控制。允许"模式=空战但正在查看陆战设置页"的状态存在。

## 二、现状机制（实施前历史参考）

- `src/gui/main_window.py` 的 `SettingsPanel`（约 L616 起）：
  - `_build()` 中 `modes` GlassCard（约 L677-699）内含 `air_button`/`tank_button` 两个 QToolButton（objectName `modeButton`，QButtonGroup 互斥），点击调 `_set_mode(mode)`。
  - `_set_mode(mode, notify=True)`（约 L994）：设置按钮选中态 + `self.pages.setCurrentIndex(0/1)`（0=空战页 1=陆战页）+ `notify` 时调用 `self._on_mode_changed_callback()`（→ `MainWindow._on_mode_changed` → `App._on_mode_switched`，这才是业务模式真正切换的点）。
  - `get_mode()`（约 L1007）：**直接读 air_button.isChecked()——模式状态目前存在这对按钮上**。
  - `save_settings()`（约 L1157）：`cfg.app.mode = self.get_mode()`。
  - `_load_config()`（约 L1067）：`self._set_mode(cfg.app.mode)`（默认 notify=True）。
  - `_open_waveform_dialog()`（约 L1240）记录 `self._parameter_mode_before_waveform = self.get_mode()`；`_show_parameter_page()`（约 L1253）恢复 `_set_mode(saved_mode, notify=False)`；打开波形/背景页时 `self.modes.hide()`，回到触发设置页时 `show()`。
  - `SettingsPanel.__init__` 接收 `dashboard_widget`（即仪表盘实例，已用于 refresh_ms）和 `on_mode_changed` 回调。
- `MainWindow`（约 L1576 起）：`get_mode()`（约 L1755）转发 `settings_panel.get_mode()`；构造时把 `on_mode_changed` 传给 SettingsPanel（约 L1631）；`_on_settings_saved`/`_apply_protocol_immediately`（约 L1723/1728）也会调用 `self._on_mode_changed`（这两处**保持不变**）。
- `Dashboard`（约 L327 起）：遥测卡 `value_row`（约 L352-360）= `value_label` + `unit_label` + `addStretch()`——按钮列加在 stretch 之后。
- 波形设置页 `WaveformSettingsDialog` 自己的"空战模式/陆战模式"按钮（约 L1302）只切换波形页内场景，与业务模式无关，**保持不变**。
- `App`（main.py）完全通过 `self.window.get_mode()` 读模式和 `_on_mode_switched` 回调工作，**本方案 App 侧零改动**。
- 相关测试：`tests/test_glass_theme.py::test_settings_are_split_into_mode_specific_cards` 点击 `panel.tank_button` 断言设置页切换（新设计下依然成立）；`tests/test_dglab_v4.py` 的协议按钮测试走 `_apply_protocol_immediately`，不受影响。

## 三、改动规格

### 3.1 `src/gui/main_window.py` — Dashboard（模式状态新归属）

在 `Dashboard._build()` 的 `value_row` 中，`addStretch()` 之后追加一个垂直按钮列：

```python
mode_col = QVBoxLayout()
mode_col.setSpacing(4)
self.mode_air_button = QToolButton()
self.mode_air_button.setObjectName("dashboardModeButton")
self.mode_air_button.setText("空战")
self.mode_air_button.setCheckable(True)
self.mode_tank_button = ...  # 同上，文字"陆战"
self._mode_group = QButtonGroup(self)
self._mode_group.setExclusive(True)
self._mode_group.addButton(self.mode_air_button)
self._mode_group.addButton(self.mode_tank_button)
self.mode_air_button.clicked.connect(lambda: self._on_mode_button_clicked("aircraft"))
self.mode_tank_button.clicked.connect(lambda: self._on_mode_button_clicked("tank"))
mode_col.addWidget(self.mode_air_button)
mode_col.addWidget(self.mode_tank_button)
value_row.addLayout(mode_col)
```

两个按钮 `setFixedSize(52, 26)`；`Dashboard.__init__` 增加 `self._mode_callback = None` 和独立的 `self._current_mode`。新增方法：

- `get_mode() -> str`：返回独立保存的当前业务模式。
- `set_mode(mode)`：blockSignals 方式设置两个按钮 checked（**不触发回调**），未知值按 `"aircraft"` 处理。
- `set_mode_callback(callback)`：注册回调（无参，风格同现有 `set_overlay_callback`）。
- `_on_mode_button_clicked(mode)`：使用 `_current_mode` 与点击目标比较；相同则直接 return，不同则先更新 `_current_mode` 再调用 `self._mode_callback()`。不能用点击后的 `isChecked()` 判断，因为 Qt 发出 `clicked` 时选中态已经更新。

### 3.2 `src/gui/main_window.py` — SettingsPanel（按钮降级为页签）

1. `_build()` 中两按钮文字改为 `"空战设置"`、`"陆战设置"`；点击连接改为 `self._show_mode_page("aircraft"/"tank")`。
2. `_set_mode(mode, notify=True)` **重命名为 `_show_mode_page(mode)`**，删除 `notify` 参数与 `self._on_mode_changed_callback()` 调用——只保留按钮选中态 + `self.pages.setCurrentIndex(0/1)`。
3. `get_mode()` **重命名为 `get_mode_page()`**（语义=当前查看的设置页，实现不变）。
4. `_load_config(sync_mode=True)` 仅在构造初始化和恢复默认时同步仪表盘与初始查看页；普通页面返回调用 `_load_config()` 时不改变模式或查看页。
5. `_show_parameter_page()` 不再通过波形页临时属性恢复模式，直接保留当前独立的设置查看页。
6. `save_settings()`：`cfg.app.mode = self.get_mode()` → `cfg.app.mode = self._dashboard_widget.get_mode()`。
8. 构造参数 `on_mode_changed` 及 `self._on_mode_changed_callback` 成员**删除**（不再有调用点）。

### 3.3 `src/gui/main_window.py` — MainWindow（换线）

1. 构造 SettingsPanel 的调用点删除 `on_mode_changed=self._on_mode_changed` 实参。
2. 其后新增接线：`self.dashboard.set_mode_callback(self._on_dashboard_mode_changed)`。
3. 新增方法：

```python
def _on_dashboard_mode_changed(self) -> None:
    """仪表盘切换模式后立即持久化并通知业务控制器。"""
    mode = self.dashboard.get_mode()
    self._config_mgr.config.app.mode = mode
    self._config_mgr.save()
    if self._on_mode_changed:
        self._on_mode_changed()
```

4. `get_mode()` 改为 `return self.dashboard.get_mode()`。
5. `_on_settings_saved` / `_apply_protocol_immediately` / 托盘等其余逻辑**不动**（保存设置和协议切换仍会触发 `App._on_mode_switched` 重新同步）。

### 3.4 `src/gui/styles.py`

在现有 `QToolButton#modeButton` 及其 `:checked` 规则的选择器组中并入 `QToolButton#dashboardModeButton`（复用同款配色），另加尺寸规则：`padding: 1px 5px; font-size: 12px;`（配合 `setFixedSize(52, 26)`）。

### 3.5 各处明确不做的事

- 不改 `App`/`main.py` 任何代码；不改 `connected`/归零/悬浮窗逻辑；不改波形页内部按钮；不改托盘；**不做**设置页跟随模式；不改版本号（如需发版由用户另行决定）。

## 四、测试计划（新增 `tests/test_dashboard_mode_switch.py`，约 8 项）

1. `MainWindow(config with cfg.app.mode="tank")` 构造后：`window.dashboard.mode_tank_button.isChecked()` 为 True，`window.get_mode() == "tank"`，settings `pages.currentIndex() == 1`。
2. 点击 `mode_tank_button`：`window.get_mode() == "tank"` 且 `on_mode_changed` Mock 恰好被调用 1 次；**再次点击已选中的按钮：Mock 不再被调用**（去重保护）。
3. `dashboard.set_mode("aircraft")` 程序化设置：按钮态变化且回调**不**触发。
4. SettingsPanel 按钮文字为"空战设置"/"陆战设置"；点击 `air_button`/`tank_button`：`pages.currentIndex()` 正确切换，且 `on_mode_changed` Mock **从不**被调用（核心行为变更回归）。
5. 互不联动：仪表盘切到陆战后，settings 的按钮选中态与页面**保持原状**。
6. 持久化：点击仪表盘“陆战”后无需点击保存，重新 `ConfigManager(path).load()` 即得 `app.mode == "tank"`。
7. 恢复默认：`settings_panel._on_reset()` 后仪表盘回到"空战"选中。
8. 波形页往返：进入波形页再返回触发设置页，查看页恢复、`window.get_mode()` 不受影响。

既有测试：`test_glass_theme.py::test_settings_are_split_into_mode_specific_cards`（点 tank_button 切页）应原样通过，无需修改；全量回归目标 ≥167 passed 且全绿。

## 五、文档与收尾（按 AGENTS.md 工作流）

- `docs/design-spec.md`：仪表盘一节补充"数值右侧上下双按钮切换模式"；触发设置一节注明按钮仅切换查看页。
- `devlog/`：新增当日条目，记录方案要点（用户三项决策）、改动清单、测试数。
- `docs/dev-plan.md`：追加本次改动清单（状态待实施方勾选）。
- 完成后运行 `python -m pytest -q` 全量验证，并 `python main.py` 手动确认：仪表盘双按钮切换模式（悬浮窗模式名/波形跟随变化）、设置按钮仅切页、模式与查看页可不一致、重启后模式持久化。

## 六、风险与注意

- 事件期间 `value_label` 显示"⚔ 击杀!"等文案较宽，固定宽按钮列可能挤压数值文本（轻微裁切可接受，不阻塞验收；如有低风险的优雅处理可选做）。
- `SettingsPanel._load_config()` 在构造期执行，`dashboard_widget` 必须已存在（现状已保证：MainWindow 先建 Dashboard 再建 SettingsPanel），勿调整创建顺序。
- `set_mode` 的 blockSignals 方式与 `clicked` 去重保护都不可省略，否则会造成启动时多余的 `App._on_mode_switched` 或随机波形重同步。

## 七、实施修订（2026-09-07）

- Qt 的 `clicked` 信号触发时按钮选中态已经更新，因此重复点击判断不能读取点击后的 `isChecked()`；Dashboard 使用独立的 `_current_mode` 保存切换前状态，完成比较后再更新并通知。
- 仪表盘模式切换立即更新内存中的 `cfg.app.mode` 并写入 `config.json`，避免从波形/背景页返回时恢复旧模式。
- `_load_config()` 的普通调用不再重置模式或设置查看页；仅构造初始化和“恢复默认”显式同步 Dashboard 与设置页。
- 为保持实时数值 50px 字号且避免控件挤压，按钮实际尺寸为 `52×26px`、间距 `4px`，左侧仪表盘首选宽度约 `355px`。
- 基线全量测试为 `167` 项，本次新增 8 项，实施后全量为 `175 passed`。
