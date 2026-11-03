"""Tests for scripts/check_invariants.py so the guardrails themselves stay honest."""

from pathlib import Path

import pytest
from scripts.check_invariants import SRC, check_file


@pytest.fixture
def module_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def make(rel: str, body: str) -> Path:
        p = SRC / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p

    created: list[Path] = []

    def wrapper(rel: str, body: str) -> Path:
        p = make(rel, body)
        created.append(p)
        return p

    yield wrapper
    for p in created:
        p.unlink(missing_ok=True)


def test_module_cannot_import_other_module(module_file):
    p = module_file("stockiq/modules/exposure/_t_bad.py", "from stockiq.modules.news import x\n")
    assert any("INV-BOUNDARY" in e for e in check_file(p))


def test_module_cannot_import_alerts(module_file):
    p = module_file("stockiq/modules/exposure/_t_bad2.py", "import stockiq.alerts.delivery\n")
    errs = check_file(p)
    assert any("INV-BOUNDARY" in e for e in errs)
    assert any("INV-DELIVERY" in e for e in errs)


def test_module_wall_clock_flagged(module_file):
    p = module_file(
        "stockiq/modules/timeline/_t_clock.py",
        "from datetime import datetime\ndef f():\n    return datetime.now()\n",
    )
    assert any("INV-PIT" in e for e in check_file(p))


def test_allow_comment_suppresses(module_file):
    p = module_file(
        "stockiq/modules/timeline/_t_ok.py",
        "from datetime import datetime\n"
        "def f():\n    return datetime.now()  # invariant: allow INV-PIT scheduler entrypoint\n",
    )
    assert check_file(p) == []


def test_own_submodule_import_ok(module_file):
    p = module_file(
        "stockiq/modules/exposure/_t_own.py", "from stockiq.modules.exposure import propagation\n"
    )
    assert check_file(p) == []


def test_secret_flagged(module_file):
    # Built at runtime so secret scanners don't flag this test fixture.
    fake = "x" * 32
    p = module_file("stockiq/core/_t_secret.py", "api" + "_key = " + repr(fake) + "\n")
    assert any("INV-SECRET" in e for e in check_file(p))
