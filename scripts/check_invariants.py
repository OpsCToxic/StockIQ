#!/usr/bin/env python3
"""Static checks for StockIQ's architecture invariants (see AGENTS.md).

Usage:
    python scripts/check_invariants.py            # check all of src/
    python scripts/check_invariants.py FILE ...   # check specific files

Rules:
  INV-BOUNDARY  analytics modules (stockiq.modules.<x>) may not import another module,
                the alerts service, or the API. They only write signals.
  INV-CONNECTOR connectors may not import modules, alerts, or api.
  INV-DELIVERY  only stockiq.alerts may import stockiq.alerts.delivery.
  INV-PIT       analytics modules may not read the wall clock (datetime.now, date.today,
                time.time, utcnow). Take an explicit `as_of` / known-time argument instead.
  INV-SECRET    no hard-coded API keys or tokens.

Suppress a single line with a trailing comment: `# invariant: allow INV-XXX <reason>`.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*=\s*['\"][A-Za-z0-9_\-\.]{16,}['\"]"),
]
CLOCK_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("date", "today"), ("time", "time")}


def module_name(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(SRC)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_names(tree: ast.AST, current: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    pkg = current.rsplit(".", 1)[0] if "." in current else current
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            out.append((node.lineno, mod))
            out += [(node.lineno, f"{mod}.{a.name}") for a in node.names]
    return out


def allowed(lines: list[str], lineno: int, rule: str) -> bool:
    line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
    return f"invariant: allow {rule}" in line


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    errors: list[str] = []
    rel = path.resolve().relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path

    for i, line in enumerate(lines, 1):
        if any(p.search(line) for p in SECRET_PATTERNS) and not allowed(lines, i, "INV-SECRET"):
            errors.append(f"{rel}:{i}: INV-SECRET hard-coded credential; read it from settings/env")

    mod = module_name(path)
    if not mod or not mod.startswith("stockiq."):
        return errors

    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return errors + [f"{rel}:{e.lineno}: syntax error: {e.msg}"]

    parts = mod.split(".")
    is_module = len(parts) >= 3 and parts[1] == "modules"
    own = ".".join(parts[:3]) if is_module else None

    for lineno, name in imported_names(tree, mod):
        if not name.startswith("stockiq."):
            continue
        if is_module:
            if (
                name.startswith("stockiq.modules.")
                and not name.startswith(own + ".")
                and name != own
            ):
                if not allowed(lines, lineno, "INV-BOUNDARY"):
                    errors.append(
                        f"{rel}:{lineno}: INV-BOUNDARY {mod} imports another module ({name}); communicate via the signal table"
                    )
            if name.startswith(("stockiq.alerts", "stockiq.api")) and not allowed(
                lines, lineno, "INV-BOUNDARY"
            ):
                errors.append(
                    f"{rel}:{lineno}: INV-BOUNDARY {mod} imports {name}; modules write signals and never notify"
                )
        if parts[1] == "connectors" and name.startswith(
            ("stockiq.modules", "stockiq.alerts", "stockiq.api")
        ):
            if not allowed(lines, lineno, "INV-CONNECTOR"):
                errors.append(f"{rel}:{lineno}: INV-CONNECTOR connector imports {name}")
        if name.startswith("stockiq.alerts.delivery") and parts[1] != "alerts":
            if not allowed(lines, lineno, "INV-DELIVERY"):
                errors.append(
                    f"{rel}:{lineno}: INV-DELIVERY only the alerts service may use delivery adapters"
                )

    if is_module:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func.value
                base = (
                    target.id
                    if isinstance(target, ast.Name)
                    else (target.attr if isinstance(target, ast.Attribute) else None)
                )
                if (base, node.func.attr) in CLOCK_CALLS and not allowed(
                    lines, node.lineno, "INV-PIT"
                ):
                    errors.append(
                        f"{rel}:{node.lineno}: INV-PIT {base}.{node.func.attr}() in an analytics module; "
                        "take an explicit as_of argument and query by known-time"
                    )
    return errors


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] if argv else sorted(SRC.rglob("*.py"))
    errors: list[str] = []
    for f in files:
        if f.suffix == ".py" and f.exists():
            errors += check_file(f)
    for e in errors:
        print(e)
    if errors:
        print(f"\n{len(errors)} invariant violation(s). See AGENTS.md 'Non-negotiable invariants'.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
