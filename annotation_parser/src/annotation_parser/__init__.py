from .annotations import Annotation, AnnotationArgument, parse_annotations
from .clang_frontend import ClangFrontend, TranslationUnit

__all__ = [
    "Annotation",
    "AnnotationArgument",
    "ClangFrontend",
    "TranslationUnit",
    "parse_annotations",
]


def main() -> None:
    raise SystemExit("code generation is not available until the remaining implementation stages")
