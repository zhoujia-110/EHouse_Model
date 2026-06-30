"""Core geometry helpers for the E-House model pipeline."""

from ehouse_model.domain import (
    Member2D,
    Member3D,
    Node2D,
    Node3D,
    PlaneSpec,
    StitchRule,
)
from ehouse_model.base_processing import (
    BaseProcessingOptions,
    export_base_staad,
    extract_base_face,
    face_model_to_base_global_model,
    normalize_base_coordinates,
    prune_base_terminal_stubs,
    snap_extend_centerlines,
)
from ehouse_model.centerline_cleanup import (
    CenterlineCleanupOptions,
    CenterlineCleanupResult,
    CenterlineSpecialFixResult,
    cleanup_centerline_candidates,
    merge_collinear_centerlines,
    realign_centerline_cluster_near_points,
    supplement_short_member_centerlines,
)
from ehouse_model.face_model import CenterlineCandidate, WarningRecord
from ehouse_model.face_extractor import FaceExtractionOptions, FaceModel, extract_face
from ehouse_model.global_model import GlobalModel, build_global_model, build_global_outputs
from ehouse_model.global_stitching import StitchOptions, stitch_global_model
from ehouse_model.mapping import map_2d_to_3d
from ehouse_model.project import ProjectSpec, load_project
from ehouse_model.project_model import (
    EHouseProject,
    ProjectDimensions,
    ProjectFaceSpec,
    ProjectPartSpec,
    load_project_json,
)
from ehouse_model.roof_processing import (
    RoofBoundaryOffsets,
    RoofExtractionResult,
    export_roof_staad,
    extract_roof_face,
    face_model_to_roof_global_model,
)
from ehouse_model.side_wall_plan_processing import (
    SectionMarkerCentroid,
    SideWallFacePlanSpec,
    SideWallPlanOptions,
    extract_section_marker_centroids,
    extract_side_wall_plan,
)
from ehouse_model.part_assembly import (
    build_global_model_from_parts,
    build_part_assembly_outputs,
    stitch_part_geometries,
)
from ehouse_model.part_builders import (
    build_base_part_from_face_model,
    build_part_from_face_model,
    build_roof_part_from_face_model,
    build_vertical_wall_part_from_plan_points,
    build_wall_part_from_face_model,
)
from ehouse_model.part_geometry import (
    PartGeometry,
    PartGeometrySource,
    load_part_geometry_json,
    write_part_geometry_json,
)
from ehouse_model.staad_import import export_part_staad_geometry, import_staad_part_geometry

__all__ = [
    "BaseProcessingOptions",
    "CenterlineCleanupOptions",
    "CenterlineCleanupResult",
    "CenterlineSpecialFixResult",
    "FaceExtractionOptions",
    "FaceModel",
    "GlobalModel",
    "EHouseProject",
    "CenterlineCandidate",
    "Member2D",
    "Member3D",
    "Node2D",
    "Node3D",
    "PartGeometry",
    "PartGeometrySource",
    "PlaneSpec",
    "ProjectDimensions",
    "ProjectFaceSpec",
    "ProjectPartSpec",
    "RoofBoundaryOffsets",
    "RoofExtractionResult",
    "SectionMarkerCentroid",
    "SideWallFacePlanSpec",
    "SideWallPlanOptions",
    "ProjectSpec",
    "StitchRule",
    "StitchOptions",
    "WarningRecord",
    "build_base_part_from_face_model",
    "build_global_model_from_parts",
    "build_global_outputs",
    "build_global_model",
    "build_part_assembly_outputs",
    "build_part_from_face_model",
    "build_roof_part_from_face_model",
    "build_vertical_wall_part_from_plan_points",
    "build_wall_part_from_face_model",
    "cleanup_centerline_candidates",
    "export_base_staad",
    "export_roof_staad",
    "export_part_staad_geometry",
    "extract_base_face",
    "extract_roof_face",
    "extract_section_marker_centroids",
    "extract_side_wall_plan",
    "extract_face",
    "face_model_to_base_global_model",
    "face_model_to_roof_global_model",
    "import_staad_part_geometry",
    "load_part_geometry_json",
    "load_project",
    "load_project_json",
    "map_2d_to_3d",
    "merge_collinear_centerlines",
    "realign_centerline_cluster_near_points",
    "normalize_base_coordinates",
    "prune_base_terminal_stubs",
    "snap_extend_centerlines",
    "stitch_part_geometries",
    "stitch_global_model",
    "supplement_short_member_centerlines",
    "write_part_geometry_json",
]
