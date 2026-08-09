from .annotations import Annotation, AnnotationArgument, parse_annotations
from .clang_frontend import ClangFrontend, TranslationUnit
from .schema_ir import SchemaIR, build_schema_ir, format_schema_ir
from .plan_ir import (
    DecodePlan,
    ReleasePlan,
    build_decode_plan,
    build_release_plan,
    format_decode_plan,
    format_release_plan,
)

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "ClangFrontend",
    "TranslationUnit",
    "SchemaIR",
    "build_schema_ir",
    "format_schema_ir",
    "DecodePlan",
    "ReleasePlan",
    "build_decode_plan",
    "build_release_plan",
    "format_decode_plan",
    "format_release_plan",
    "parse_annotations",
]


def main() -> None:
    raise SystemExit("code generation is not available until the remaining implementation stages")
