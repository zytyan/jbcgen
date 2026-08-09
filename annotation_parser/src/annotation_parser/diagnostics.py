from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.column}"


class AnnotationError(ValueError):
    def __init__(self, message: str, location: SourceLocation | None = None):
        self.message = message
        self.location = location
        prefix = f"{location}: " if location is not None else ""
        super().__init__(prefix + message)


class FrontendError(RuntimeError):
    pass
