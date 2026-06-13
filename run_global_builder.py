# -*- coding: utf-8 -*-
"""PyCharm-friendly debug entry for project.json to global_model.json."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ehouse_model.global_model import build_global_outputs
from ehouse_model.project_model import (
    EHouseProject,
    ProjectDimensions,
    ProjectFaceSpec,
    write_project_json,
)


def main() -> int:
    print("E-House 全局三维模型生成调试入口")
    print("提示：直接回车会使用方括号里的默认值。")
    print()

    project_json_path = _prompt_path("请输入 project.json 路径", PROJECT_ROOT / "project.json")
    project_json_path = _make_absolute(project_json_path)
    if not project_json_path.exists():
        print("未找到 project.json，先创建一个单面项目配置。")
        _create_single_face_project_json(project_json_path)

    output_dir = _prompt_path("请输入全局输出目录", PROJECT_ROOT / "output_global")
    output_dir = _make_absolute(output_dir)
    model = build_global_outputs(project_json_path, output_dir)

    print()
    print("全局模型生成完成。")
    print(f"节点数量：{len(model.nodes)}")
    print(f"杆件数量：{len(model.members)}")
    print(f"Warnings：{len(model.warnings)}")
    print()
    print(f"global_model.json：{output_dir / 'global_model.json'}")
    print(f"nodes.csv：{output_dir / 'nodes.csv'}")
    print(f"members.csv：{output_dir / 'members.csv'}")
    print(f"warnings.csv：{output_dir / 'warnings.csv'}")
    print(f"geometry.std：{output_dir / 'geometry.std'}")
    return 0


def _create_single_face_project_json(project_json_path: Path) -> None:
    name = _prompt_text("项目名称", "E-House Project")
    length = _prompt_float("E-House 长度 X", 12000.0)
    height = _prompt_float("E-House 高度 Y", 3000.0)
    width = _prompt_float("E-House 宽度 Z", 2400.0)
    face_id = _prompt_text("单面 ID", "base")
    plane_type = _prompt_text("平面类型 base/roof/left_wall/right_wall/front_wall/back_wall", "base")
    face_model_path = _prompt_path("face_model.json 路径", PROJECT_ROOT / "output" / "face_model.json")
    center_offset = _prompt_float("中心面偏移 center_offset", 0.0)

    face_model_path_text = _relative_or_absolute(face_model_path, project_json_path.parent)
    project = EHouseProject(
        name=name,
        dimensions=ProjectDimensions(length=length, height=height, width=width),
        faces=(
            ProjectFaceSpec(
                id=face_id,
                plane_type=plane_type,
                face_model_path=face_model_path_text,
                center_offset=center_offset,
            ),
        ),
        path=project_json_path,
    )
    write_project_json(project, project_json_path)
    print(f"已创建 project.json：{project_json_path}")


def _prompt_path(label: str, default: Path) -> Path:
    value = input(f"{label} [{default}]: ").strip().strip('"')
    return Path(value) if value else default


def _prompt_text(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


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


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    absolute = _make_absolute(path)
    try:
        return str(absolute.relative_to(base_dir))
    except ValueError:
        return str(absolute)


if __name__ == "__main__":
    raise SystemExit(main())
