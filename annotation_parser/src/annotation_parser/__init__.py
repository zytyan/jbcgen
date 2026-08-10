from .annotations import Annotation, AnnotationArgument, parse_annotations
from .clang_frontend import AstType, AstTypeKind, ClangFrontend, TranslationUnit
from .generate_plan import GeneratePlan, build_generate_plan, format_generate_plan
from .schema import Schema, build_schema, format_schema
from .c_generator import generate_c

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "ClangFrontend",
    "AstType",
    "AstTypeKind",
    "TranslationUnit",
    "Schema",
    "build_schema",
    "format_schema",
    "GeneratePlan",
    "build_generate_plan",
    "format_generate_plan",
    "generate_c",
    "parse_annotations",
]


def main() -> None:
    from .cli import main as cli_main

    cli_main()
