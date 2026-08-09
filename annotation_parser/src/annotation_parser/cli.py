from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence, TextIO

from .c_generator import generate_c
from .clang_frontend import ClangFrontend
from .diagnostics import AnnotationError, FrontendError
from .plan_ir import build_decode_plan, build_release_plan, format_decode_plan, format_release_plan
from .schema_ir import build_schema_ir, format_schema_ir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="annotation-parser",
        description="Generate C JSON decoder and cleanup functions from annotated C declarations.",
    )
    parser.add_argument("input", type=Path, help="annotated C header")
    parser.add_argument("-o", "--output", required=True, type=Path, help="generated C source")
    parser.add_argument("--clang", default="clang", help="clang executable")
    parser.add_argument("--include", dest="include", help="header spelling emitted in generated C")
    parser.add_argument(
        "--dump-ir",
        choices=("schema", "decode", "release", "all"),
        help="print a human-readable IR dump to stderr",
    )
    return parser


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def run(argv: Sequence[str] | None = None, stderr: TextIO | None = None) -> int:
    stderr = stderr or sys.stderr
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--" in arguments:
        separator = arguments.index("--")
        tool_arguments = arguments[:separator]
        clang_arguments = arguments[separator + 1 :]
    else:
        tool_arguments = arguments
        clang_arguments = []
    options = _parser().parse_args(tool_arguments)
    try:
        unit = ClangFrontend(options.clang).parse(options.input, clang_arguments)
        schema = build_schema_ir(unit)
        decode = build_decode_plan(schema)
        release = build_release_plan(schema)
        source = generate_c(schema, decode, release, options.include or str(options.input))
        if options.dump_ir in {"schema", "all"}:
            print(format_schema_ir(schema), file=stderr)
        if options.dump_ir in {"decode", "all"}:
            print(format_decode_plan(decode), file=stderr)
        if options.dump_ir in {"release", "all"}:
            print(format_release_plan(release), file=stderr)
        _atomic_write(options.output, source)
        return 0
    except (AnnotationError, FrontendError, OSError) as error:
        print(f"annotation-parser: error: {error}", file=stderr)
        return 1


def main() -> None:
    raise SystemExit(run())
