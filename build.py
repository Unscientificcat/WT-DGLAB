"""构建 WT-DGLAB 的目录版 Windows 发布包并生成 ZIP。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from src.version import APP_VERSION as VERSION

APP_NAME = "WT-DGLAB"
PACKAGE_NAME = f"{APP_NAME} {VERSION}"

# PyInstaller 会沿 PATH 收集第三方目录里的 ICU 和 UCRT 副本。符号名带
# icu_78 版本化重命名的 icuuc.dll 一旦进入发布包，就会在运行时遮蔽
# Windows 系统的 icuuc 转发器，导致 Qt6Core 加载失败（错误 127，
# 找不到指定的程序）。旧 UCRT/API 集桩文件同理存在遮蔽风险。
# PySide6 轮子本身不携带 ICU，这些统一交由 Windows 系统提供。
SHADOWING_BINARY_PATTERNS = (
    "icuuc*.dll", "icudt*.dll", "icuin*.dll",
    "ucrtbase.dll", "api-ms-win-*.dll",
)


def _remove_shadowing_binaries(package_dir: Path) -> None:
    """删除包内会遮蔽系统运行库的第三方 DLL。"""
    internal = package_dir / "_internal"
    if not internal.is_dir():
        return
    for pattern in SHADOWING_BINARY_PATTERNS:
        for path in internal.glob(pattern):
            path.unlink()
            print(f"  [清理] {path.relative_to(package_dir)}")


def _remove_directory(path: Path) -> None:
    """删除构建脚本明确管理的目录。"""
    if path.exists():
        shutil.rmtree(path)


def validate_package(package_dir: Path) -> None:
    """检查运行包结构，并拒绝源码和开发文件混入。"""
    required_files = [
        package_dir / f"{APP_NAME}.exe",
        package_dir / "config.default.json",
        package_dir / "README.md",
        package_dir / "LICENSE",
        package_dir / "resources" / "注意事项.txt",
        package_dir / "resources" / "tubiao.ico",
        package_dir / "resources" / "tubiao_ui.jpg",
        package_dir / "resources" / "wallpaper_default.png",
    ]
    missing = [str(path.relative_to(package_dir))
               for path in required_files if not path.is_file()]
    if not (package_dir / "_internal").is_dir():
        missing.append("_internal/")
    if missing:
        raise RuntimeError(f"运行包缺少必需内容: {', '.join(missing)}")

    shadowing = [
        str(path.relative_to(package_dir))
        for pattern in SHADOWING_BINARY_PATTERNS
        for path in (package_dir / "_internal").glob(pattern)
    ]
    if shadowing:
        raise RuntimeError(
            "运行包包含会遮蔽系统运行库的 DLL: "
            f"{', '.join(shadowing[:5])}"
        )

    forbidden_names = {
        ".git", ".pytest_cache", "__pycache__", "build", "devlog",
        "docs", "src", "tests",
    }
    violations = []
    for path in package_dir.rglob("*"):
        relative = path.relative_to(package_dir)
        if (relative.parts[0] != "_internal"
                and any(part in forbidden_names for part in relative.parts)):
            violations.append(str(relative))
        elif (path.is_file() and path.suffix.lower() in {".py", ".pyw"}
              and relative.parts[0] != "_internal"):
            violations.append(str(relative))
    if violations:
        sample = ", ".join(violations[:10])
        raise RuntimeError(f"运行包包含禁止内容: {sample}")


def _create_zip(package_dir: Path, zip_path: Path) -> None:
    """将版本目录压缩为包含顶层版本目录的 ZIP。"""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if (package_dir / "waveforms").is_dir():
            archive.writestr(f"{package_dir.name}/waveforms/", "")
        for path in package_dir.rglob("*"):
            if path.is_file():
                if path.name == "config.json":
                    continue
                archive_name = Path(package_dir.name) / path.relative_to(package_dir)
                archive.write(path, archive_name.as_posix())


def _copy_release_files(project_root: Path, package_dir: Path) -> None:
    """把用户可见的发布文件复制到 EXE 外部。"""
    resources_target = package_dir / "resources"
    shutil.copytree(project_root / "resources", resources_target, dirs_exist_ok=True)
    # 提供用户放置自定义 .pulse 文件的目录，不生成示例波形。
    (package_dir / "waveforms").mkdir(exist_ok=True)
    # 提供用户放置自定义壁纸的目录，不生成示例图片。
    (package_dir / "backgrounds").mkdir(exist_ok=True)
    for name in ("config.default.json", "README.md", "LICENSE"):
        shutil.copy2(project_root / name, package_dir / name)


def build() -> Path:
    """执行 PyInstaller 目录构建、内容检查和 ZIP 压缩。"""
    project_root = Path(__file__).resolve().parent
    main_script = project_root / "main.py"
    icon_path = project_root / "resources" / "tubiao.ico"
    resources_dir = project_root / "resources"
    dist_root = project_root / "dist"
    staging_dist = project_root / "build" / "onedir-dist"
    work_path = project_root / "build" / "onedir-work"
    spec_path = project_root / "build" / "onedir-spec"
    package_dir = dist_root / PACKAGE_NAME
    zip_path = dist_root / f"{PACKAGE_NAME}.zip"

    for path in (resources_dir, icon_path, resources_dir / "wallpaper_default.png",
                 project_root / "config.default.json",
                 project_root / "README.md", project_root / "LICENSE"):
        if not path.exists():
            raise FileNotFoundError(f"缺少构建输入: {path}")

    dist_root.mkdir(exist_ok=True)
    _remove_directory(staging_dist)
    _remove_directory(work_path)
    _remove_directory(spec_path)
    _remove_directory(package_dir)

    separator = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onedir", "--windowed", "--name", APP_NAME,
        "--distpath", str(staging_dist),
        "--workpath", str(work_path),
        "--specpath", str(spec_path),
        "--contents-directory", "_internal",
        "--collect-all", "PySide6",
        "--hidden-import", "pydglab_ws", "--hidden-import", "qrcode",
        "--hidden-import", "PIL", "--hidden-import", "requests",
        "--hidden-import", "websockets", "--icon", str(icon_path),
        "--clean", "--noconfirm", str(main_script),
    ]

    print("=" * 60)
    print("  WT-DGLAB 目录版打包")
    print("=" * 60)
    print(f"  版本: {VERSION}")
    print(f"  输出: {package_dir}")
    result = subprocess.run(command, cwd=project_root)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    generated_dir = staging_dist / APP_NAME
    if not generated_dir.is_dir():
        raise RuntimeError(f"PyInstaller 未生成目录: {generated_dir}")
    shutil.move(str(generated_dir), str(package_dir))
    _remove_directory(staging_dist)
    _copy_release_files(project_root, package_dir)
    _remove_shadowing_binaries(package_dir)
    validate_package(package_dir)
    _create_zip(package_dir, zip_path)
    print(f"  [OK] 目录包: {package_dir}")
    print(f"  [OK] ZIP: {zip_path}")
    return package_dir


if __name__ == "__main__":
    build()
