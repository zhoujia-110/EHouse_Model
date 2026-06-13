# -*- coding: utf-8 -*-
"""PyCharm-friendly debug entry for single-face DXF extraction."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ehouse_model.face_extractor import FaceExtractionOptions, extract_face


def main() -> int:
    print("E-House 单面 DXF 中心线识别调试入口")
    print("提示：直接回车会使用方括号里的默认值。")
    print()

    default_dxf = _default_dxf_path()
    dxf_path = _prompt_path("请输入 DXF 文件路径", default_dxf)
    dxf_path = _make_absolute(dxf_path)
    if not dxf_path.exists():
        print(f"找不到 DXF 文件：{dxf_path}")
        return 1

    output_dir = _prompt_path("请输入输出目录", PROJECT_ROOT / "output")
    output_dir = _make_absolute(output_dir)
    face_model_path = output_dir / "face_model.json"
    overlay_path = output_dir / "centerline_overlay.dxf"
    warnings_csv_path = output_dir / "warnings.csv"

    max_pair_width = _prompt_optional_float(
        "最大配对宽度 max_pair_width，单位同 DXF，留空表示自动判断"
    )

    options = FaceExtractionOptions(max_pair_width=max_pair_width)
    model = extract_face(
        dxf_path,
        face_model_path=face_model_path,
        overlay_path=overlay_path,
        warnings_csv_path=warnings_csv_path,
        options=options,
    )

    print()
    print("识别完成。")
    print(f"输入 DXF：{dxf_path}")
    print(f"节点数量：{len(model.nodes)}")
    print(f"杆件数量：{len(model.members)}")
    print(f"中心线候选数量：{len(model.centerline_candidates)}")

    if model.warnings:
        print()
        print("Warnings：")
        for warning in model.warnings:
            print(f"- {warning.id} {warning.code}: {warning.message}")

    print()
    print(f"face_model.json：{face_model_path}")
    print(f"centerline_overlay.dxf：{overlay_path}")
    print(f"warnings.csv：{warnings_csv_path}")
    print()
    print("你可以用 CAD 打开 centerline_overlay.dxf，检查红色中心线是否在构件中间。")
    return 0


def _default_dxf_path() -> Path:
    drawings_dir = PROJECT_ROOT / "drawings"
    dxf_files = sorted(drawings_dir.glob("*.dxf"))
    if dxf_files:
        return dxf_files[0]
    return drawings_dir / "base.dxf"


def _prompt_path(label: str, default: Path) -> Path:
    value = input(f"{label} [{default}]: ").strip().strip('"')
    return Path(value) if value else default


def _prompt_optional_float(label: str) -> float | None:
    value = input(f"{label}: ").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        print("输入不是数字，本次使用自动判断。")
        return None


def _make_absolute(path: Path) -> Path:
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
