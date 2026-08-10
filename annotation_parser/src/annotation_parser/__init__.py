from .annotations import Annotation, AnnotationArgument, parse_annotations
from .clang_frontend import AstType, AstTypeKind, ClangFrontend, TranslationUnit
from .schema_core import CoreSchemaIR
from .schema_ir import SchemaIR, build_schema_ir, builtin_plugins, format_schema_ir
from .schema_plugins import PluginKey, PluginSet, SchemaPlugin
from .plan_ir import (
    DecodePlan,
    ReleasePlan,
    build_decode_plan,
    build_release_plan,
    format_decode_plan,
    format_release_plan,
)
from .c_generator import generate_c

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "ClangFrontend",
    "AstType",
    "AstTypeKind",
    "TranslationUnit",
    "SchemaIR",
    "CoreSchemaIR",
    "PluginKey",
    "PluginSet",
    "SchemaPlugin",
    "build_schema_ir",
    "builtin_plugins",
    "format_schema_ir",
    "DecodePlan",
    "ReleasePlan",
    "build_decode_plan",
    "build_release_plan",
    "format_decode_plan",
    "format_release_plan",
    "generate_c",
    "parse_annotations",
]


def main() -> None:
    from .cli import main as cli_main

    cli_main()
