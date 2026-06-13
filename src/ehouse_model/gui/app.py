"""GUI launcher with Windows-friendly Qt diagnostics."""

from __future__ import annotations

from pathlib import Path
import os
import sys

_DLL_DIRECTORY_HANDLES: list[object] = []


def main() -> int:
    _prepare_qt_runtime()
    try:
        from ehouse_model.gui.main_window import main as run_main_window
    except ImportError as exc:
        print("PySide6/Qt 加载失败。")
        print(str(exc))
        print()
        print("请先确认当前环境可以导入 QtCore：")
        print(r'D:\Users\Administrator\anaconda3\python.exe -c "from PySide6 import QtCore; print(QtCore.qVersion())"')
        print()
        print("如果仍然失败，检查 PySide6 目录里是否残留旧版 *.cp313-win_amd64.pyd 文件。")
        print("修复后再从 PyCharm 运行 run_gui.py。")
        return 1
    return run_main_window()


def _prepare_qt_runtime() -> None:
    prefix = Path(sys.prefix)
    pyside_dir = prefix / "Lib" / "site-packages" / "PySide6"
    shiboken_dir = prefix / "Lib" / "site-packages" / "shiboken6"
    plugins_dir = pyside_dir / "plugins"
    platforms_dir = plugins_dir / "platforms"

    if plugins_dir.exists():
        os.environ["QT_PLUGIN_PATH"] = str(plugins_dir)
    if platforms_dir.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)

    path_parts = [path for path in (pyside_dir, shiboken_dir) if path.exists()]
    if path_parts:
        os.environ["PATH"] = os.pathsep.join([*(str(path) for path in path_parts), os.environ.get("PATH", "")])

    _add_qt_dll_search_paths()


def _add_qt_dll_search_paths() -> None:
    if not hasattr(os, "add_dll_directory"):
        return

    prefix = Path(sys.prefix)
    candidates = [
        prefix / "Lib" / "site-packages" / "PySide6",
        prefix / "Lib" / "site-packages" / "shiboken6",
        prefix / "Library" / "bin",
    ]
    for path in candidates:
        if path.exists():
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(path)))


if __name__ == "__main__":
    raise SystemExit(main())
