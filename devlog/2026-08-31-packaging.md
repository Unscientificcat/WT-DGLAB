# 2026-08-31：目录化打包与 ZIP 发布

- [x] 将 PyInstaller 从 `--onefile` 改为 `--onedir`，依赖集中到 `_internal/`。
- [x] 新增统一运行时路径模块，源码和冻结运行均从 EXE 同目录 `resources/` 读取资源。
- [x] 新增安全的 `config.default.json`，首次启动生成同目录 `config.json`，不带入个人配置。
- [x] `build.py` 自动生成目录包、检查禁止内容并压缩为 ZIP。
- [x] 发布包不包含项目源码、测试和开发文档；用户配置不会进入 ZIP。
- [x] 回归测试 `105 passed`。
- [x] 目录版 EXE 启动冒烟检查通过。

## 产物

- `dist/WT-DGLAB v1 beta_2/`
- `dist/WT-DGLAB v1 beta_2.zip`

PyInstaller 对 PySide6 的部分可选 QML/数据库插件会输出缺少外部厂商 DLL 的警告；本项目使用的 Qt Widgets、Network 和 GUI 路径构建完成并已通过启动检查。
