from .annotations import Annotation, AnnotationArgument, parse_annotations
from .clang_frontend import ClangFrontend, TranslationUnit
from .schema_ir import SchemaIR, build_schema_ir, format_schema_ir

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "ClangFrontend",
    "TranslationUnit",
    "SchemaIR",
    "build_schema_ir",
    "format_schema_ir",
    "parse_annotations",
]


def main() -> None:
    raise SystemExit("code generation is not available until the remaining implementation stages")
