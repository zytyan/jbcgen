import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
GOLDEN = Path(__file__).with_name("golden") / "reflection_model.c"

DIRECT_HEAP_CALL = re.compile(
    r"(?<!->)(?<!\.)\b(?:"
    r"malloc|calloc|realloc|free|aligned_alloc|strdup|strndup|"
    r"mmap|munmap|sbrk|brk"
    r")\s*\("
)


class AllocatorPolicyTest(unittest.TestCase):
    def test_production_c_uses_only_json_allocator_for_dynamic_memory(self) -> None:
        sources = sorted(RUNTIME.glob("*.c")) + sorted(RUNTIME.glob("*.h"))
        sources.append(GOLDEN)
        violations: list[str] = []
        for path in sources:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if DIRECT_HEAP_CALL.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{line_number}: {line}")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
