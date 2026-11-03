#!/usr/bin/env python3
"""PreToolUse hook: block edits to secrets, raw payload storage, and applied migrations.

Reads the tool call JSON on stdin. Exit 2 blocks the call and sends stderr back to Claude.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "")
if not path:
    sys.exit(0)

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
p = Path(path).resolve()
try:
    rel = p.relative_to(root).as_posix()
except ValueError:
    sys.exit(0)

name = p.name

if name == ".env" or (name.startswith(".env.") and name != ".env.example") or rel.startswith("secrets/"):
    print(
        f"Blocked: {rel} holds secrets. Add new variables to .env.example and ask Cameron to set real values.",
        file=sys.stderr,
    )
    sys.exit(2)

if rel.startswith("data/raw/"):
    print(
        "Blocked: data/raw/ is immutable raw-first storage. Fix the parser and re-parse instead of editing payloads.",
        file=sys.stderr,
    )
    sys.exit(2)

# Migrations already committed to git are applied history: add a new migration instead.
if rel.startswith("migrations/versions/") and p.exists():
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", rel],
        capture_output=True,
    ).returncode == 0
    if tracked:
        print(
            f"Blocked: {rel} is a committed migration. Create a new Alembic revision instead of editing it.",
            file=sys.stderr,
        )
        sys.exit(2)

sys.exit(0)
