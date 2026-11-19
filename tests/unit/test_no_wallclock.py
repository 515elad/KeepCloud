"""Hard rule 9: no wall clock or unseeded randomness outside clock.py and rng.py."""

import ast
from pathlib import Path

import pytest

from keepair.config import REPO_ROOT

pytestmark = pytest.mark.req("v1.4 Section 2.3 (injected clock and seed)", "SEC-35")

SRC = REPO_ROOT / "src" / "keepair"
ALLOWED = {SRC / "clock.py", SRC / "rng.py"}
FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "time_ns"}
FORBIDDEN_MODULES = {"random", "secrets", "time"}


def violations(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [f"import {a.name}" for a in node.names if a.name in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
            found.append(f"from {node.module} import ...")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in FORBIDDEN_CALLS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"datetime", "date", "time"}
        ):
            found.append(f"{node.func.value.id}.{node.func.attr}()")
    return found


def test_wall_clock_and_random_only_in_injected_modules():
    bad = {
        str(p.relative_to(REPO_ROOT)): v
        for p in SRC.rglob("*.py")
        if p not in ALLOWED and (v := violations(p))
    }
    assert bad == {}


def test_the_scanner_catches_a_violation(tmp_path):
    sample = tmp_path / "bad.py"
    sample.write_text("import random\nfrom datetime import datetime\nx = datetime.now()\n")
    assert violations(sample) == ["import random", "datetime.now()"]
