"""Preprocess GUI launcher with Windows-friendly Qt diagnostics."""

from __future__ import annotations

from ehouse_model.gui.app import _prepare_qt_runtime


def main() -> int:
    _prepare_qt_runtime()
    try:
        from ehouse_model.gui.preprocess_window import main as run_preprocess_window
    except ImportError as exc:
        print("PySide6/Qt 加载失败。")
        print(str(exc))
        print()
        print("请先确认当前环境可以导入 QtCore：")
        print(r'D:\Users\Administrator\anaconda3\python.exe -c "from PySide6 import QtCore; print(QtCore.qVersion())"')
        return 1
    return run_preprocess_window()


if __name__ == "__main__":
    raise SystemExit(main())
