"""The CI secret scanner must actually catch a planted secret (SEC-44 seeded defect)."""

import subprocess
import sys
from pathlib import Path

import pytest

from keepair.config import REPO_ROOT

pytestmark = pytest.mark.req("SEC-44", "ISO 27001 A.8.28")

HOOK = Path(sys.executable).parent / "detect-secrets-hook"


def scan(path: Path) -> int:
    baseline = REPO_ROOT / ".secrets.baseline"
    return subprocess.run(  # noqa: S603
        [HOOK, "--baseline", baseline, path], capture_output=True, cwd=REPO_ROOT
    ).returncode


def test_scanner_flags_a_planted_key(tmp_path):
    # Assembled at run time so this repository never contains the pattern itself.
    planted = "-----BEGIN " + "RSA PRIVATE KEY" + "-----\nMIIEow\n"
    sample = tmp_path / "leak.txt"
    sample.write_text(planted)
    assert scan(sample) != 0


def test_scanner_passes_a_clean_file(tmp_path):
    sample = tmp_path / "clean.txt"
    sample.write_text("nothing to see here\n")
    assert scan(sample) == 0


def test_baseline_has_no_accepted_findings():
    import json

    assert json.loads((REPO_ROOT / ".secrets.baseline").read_text())["results"] == {}


@pytest.mark.req("SEC-22", "S-36")
def test_token_format_detected_by_secret_scanner(tmp_path):
    from keepair.gateway.tokens import generate_token
    from keepair.rng import seeded_rng

    sample = tmp_path / "config.env"
    sample.write_text(f"GATEWAY_TOKEN={generate_token(seeded_rng(3))}\n")  # built at run time
    assert scan(sample) != 0
    sample.write_text("GATEWAY_TOKEN=kair_not_a_token\n")
    assert scan(sample) == 0
