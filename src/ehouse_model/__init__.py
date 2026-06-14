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
from ehouse_model.project_model import EHouseProject, ProjectDimensions, ProjectFaceSpec, load_project_json

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
    "PlaneSpec",
    "ProjectDimensions",
    "ProjectFaceSpec",
    "ProjectSpec",
    "StitchRule",
    "StitchOptions",
    "WarningRecord",
    "build_global_outputs",
    "build_global_model",
    "cleanup_centerline_candidates",
    "export_base_staad",
    "extract_base_face",
    "extract_face",
    "face_model_to_base_global_model",
    "load_project",
    "load_project_json",
    "map_2d_to_3d",
    "merge_collinear_centerlines",
    "realign_centerline_cluster_near_points",
    "normalize_base_coordinates",
    "prune_base_terminal_stubs",
    "snap_extend_centerlines",
    "stitch_global_model",
    "supplement_short_member_centerlines",
]
