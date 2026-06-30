# -*- coding: utf-8 -*-
"""PyCharm-friendly debug entry for roof DXF extraction."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ehouse_model.roof_processing import export_roof_staad, extract_roof_face


def main() -> int:
    print("E-House 屋盖 DXF 识别调试入口")
    print("提示：屋盖使用与底座相同的识别算法，只是导出到用户指定的全局 Y 平面。")
    print()

    dxf_path = _prompt_path("请输入屋盖 DXF 路径", _default_dxf_path())
    dxf_path = _make_absolute(dxf_path)
    if not dxf_path.exists():
        print(f"找不到 DXF 文件：{dxf_path}")
        return 1

    y_plane = _prompt_float("请输入屋盖全局 Y 坐标(m)", 3.0)
    output_dir = _prompt_path("请输入输出目录", PROJECT_ROOT / "output" / "roof")
    output_dir = _make_absolute(output_dir)

    result = extract_roof_face(
        dxf_path,
        y_plane=y_plane,
        face_model_path=output_dir / "roof_face_model.json",
        overlay_path=output_dir / "roof_centerline_overlay.dxf",
        warnings_csv_path=output_dir / "roof_warnings.csv",
    )
    export_roof_staad(result.face_model, output_dir / "roof_geometry.std", y_plane=y_plane)

    print()
    print("屋盖识别完成。")
    print(f"Y 坐标：{y_plane:g} m")
    print(f"节点数量：{len(result.face_model.nodes)}")
    print(f"杆件数量：{len(result.face_model.members)}")
    print(f"Warnings：{len(result.face_model.warnings)}")
    print(f"face_model.json：{output_dir / 'roof_face_model.json'}")
    print(f"centerline_overlay.dxf：{output_dir / 'roof_centerline_overlay.dxf'}")
    print(f"warnings.csv：{output_dir / 'roof_warnings.csv'}")
    print(f"geometry.std：{output_dir / 'roof_geometry.std'}")
    return 0


def _default_dxf_path() -> Path:
    drawings_dir = PROJECT_ROOT / "drawings"
    roof_candidates = sorted(drawings_dir.glob("*roof*.dxf"))
    if roof_candidates:
        return roof_candidates[0]
    dxf_files = sorted(drawings_dir.glob("*.dxf"))
    if dxf_files:
        return dxf_files[0]
    return drawings_dir / "roof.dxf"


def _prompt_path(label: str, default: Path) -> Path:
    value = input(f"{label} [{default}]: ").strip().strip('"')
    return Path(value) if value else default


def _prompt_float(label: str, default: float) -> float:
    value = input(f"{label} [{default:g}]: ").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        print("输入不是数字，本次使用默认值。")
        return default


def _make_absolute(path: Path) -> Path:
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
