"""PyInstaller 打包脚本 — 将 WT-DGLAB 打包为独立的 .exe 文件

用法:
    pip install pyinstaller
    python build.py

产物:
    dist/WT-DGLAB.exe — 可独立运行的 Windows 程序
"""

import os
import sys
import subprocess


def build():
    """运行 PyInstaller 打包"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(project_root, "main.py")
    icon_path = os.path.join(project_root, "icon.ico")

    # PyInstaller 参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",              # 单个 exe 文件
        "--windowed",            # 不显示控制台窗口
        "--name", "WT-DGLAB",
        "--distpath", ".",       # 直接输出到项目根目录
        "--add-data", f"src{os.pathsep}src",
        "--add-data", f"注意事项.txt{os.pathsep}.",
        "--hidden-import", "pydglab_ws",
        "--hidden-import", "qrcode",
        "--hidden-import", "PIL",
        "--hidden-import", "requests",
        "--hidden-import", "websockets",
        "--hidden-import", "PIL.ImageTk",
        "--clean",
        "--noconfirm",
        main_script,
    ]

    # 如果有图标文件则加上
    if os.path.exists(icon_path):
        cmd.insert(-1, f"--icon={icon_path}")

    print("=" * 60)
    print("  WT-DGLAB 打包脚本")
    print("=" * 60)
    print(f"  项目目录: {project_root}")
    print(f"  入口文件: {main_script}")
    print(f"  输出目录: {os.path.join(project_root, 'dist')}")
    print()

    result = subprocess.run(cmd, cwd=project_root)
    if result.returncode == 0:
        exe_path = os.path.join(project_root, "WT-DGLAB.exe")
        print()
        print("=" * 60)
        print(f"  [OK] 打包成功!")
        print(f"  程序位置: {exe_path}")
        print("=" * 60)
    else:
        print()
        print("=" * 60)
        print("  [FAIL] 打包失败，请检查错误信息")
        print("=" * 60)
        sys.exit(result.returncode)


if __name__ == "__main__":
    build()
