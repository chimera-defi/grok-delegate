#!/usr/bin/env python3
"""Configure git to use .githooks for grok-delegate."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    hooks_dir = repo_root / ".githooks"
    if not hooks_dir.is_dir():
        print(f"ERROR: .githooks directory not found at {hooks_dir}", file=sys.stderr)
        return 1
    result = subprocess.run(
        ["git", "-C", str(repo_root), "config", "core.hooksPath", ".githooks"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode
    print(f"git hooks configured: {hooks_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
