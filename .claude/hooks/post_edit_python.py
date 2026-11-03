#!/usr/bin/env python3
"""PostToolUse hook: after a Python file changes, format it with ruff and check invariants.

Formatting is silent. Invariant violations exit 2 so Claude sees them and fixes them.
If ruff or uv is not installed yet, the formatting step is skipped.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "")
if not path.endswith(".py"):
    sys.exit(0)

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()

ruff = shutil.which("ruff")
if ruff:
    subprocess.run([ruff, "format", "--quiet", path], cwd=root)
    subprocess.run([ruff, "check", "--fix", "--quiet", path], cwd=root)

checker = root / "scripts" / "check_invariants.py"
if checker.exists():
    result = subprocess.run(
        [sys.executable, str(checker), path], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        sys.exit(2)

sys.exit(0)
