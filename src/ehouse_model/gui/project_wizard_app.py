"""Launcher for the integrated project wizard GUI."""

from __future__ import annotations

from ehouse_model.gui.app import _prepare_qt_runtime


def main() -> int:
    _prepare_qt_runtime()
    from ehouse_model.gui.project_wizard import main as run_project_wizard

    return run_project_wizard()


if __name__ == "__main__":
    raise SystemExit(main())
