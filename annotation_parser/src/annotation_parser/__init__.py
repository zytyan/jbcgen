from .annotations import Annotation, AnnotationArgument, parse_annotations
from .c_generator import generate_c
from .clang_frontend import AstType, AstTypeKind, ClangFrontend, TranslationUnit
from .generate_plan import GeneratePlan, build_generate_plan, format_generate_plan
from .schema import Schema, build_schema, format_schema

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "AstType",
    "AstTypeKind",
    "ClangFrontend",
    "GeneratePlan",
    "Schema",
    "TranslationUnit",
    "build_generate_plan",
    "build_schema",
    "format_generate_plan",
    "format_schema",
    "generate_c",
    "parse_annotations",
]


def main() -> None:
    from .cli import main as cli_main

    cli_main()
