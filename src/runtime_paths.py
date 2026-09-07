"""应用目录和外部资源路径。"""

import os
import sys


def application_directory() -> str:
    """返回源码项目根目录或打包后 EXE 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def resource_path(filename: str) -> str:
    """返回 EXE 或源码项目下外部 resources 目录中的资源路径。"""
    return os.path.join(application_directory(), "resources", filename)
