# -*- coding: utf-8 -*-
"""PyCharm-friendly DXF preprocessing entry."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ehouse_model.dxf_preprocessor import preprocess_dxf


def main() -> int:
    default_path = PROJECT_ROOT / "drawings" / "Drawing1.dxf"
    prompt = f"请输入要预处理的DXF路径（直接回车使用 {default_path}）：\n> "
    user_input = input(prompt).strip().strip('"')
    dxf_path = Path(user_input) if user_input else default_path
    if not dxf_path.is_absolute():
        dxf_path = PROJECT_ROOT / dxf_path

    if not dxf_path.exists():
        print(f"找不到DXF文件：{dxf_path}")
        return 1

    result = preprocess_dxf(dxf_path)
    print("\n预处理完成：")
    print(f"清理后DXF：{result.clean_dxf_path}")
    print(f"预览Overlay：{result.overlay_dxf_path}")
    print(f"处理报告CSV：{result.report_csv_path}")
    print(f"原始线段数：{result.original_segment_count}")
    print(f"保留线段数（合并前）：{result.kept_segment_count}")
    print(f"删除线段数：{result.removed_segment_count}")
    print(f"输出线段数：{result.output_segment_count}")
    print(f"合并组数：{result.merged_group_count}")
    print(f"交叉封口清理数：{result.cross_removed_segment_count}")
    print(f"相交让位裁剪数：{result.overlap_trimmed_segment_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
