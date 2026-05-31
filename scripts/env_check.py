#!/usr/bin/env python3
"""Environment check for Grok delegate setup."""
import subprocess
import sys
import shutil
from pathlib import Path


def check_opencode():
    """Check if OpenCode is installed."""
    opencode = shutil.which("opencode")
    if opencode:
        return True, opencode
    return False, "OpenCode not found. Install with: curl -fsSL https://opencode.ai/install | bash"


def check_codex():
    """Check if Codex fallback is available."""
    codex = shutil.which("codex")
    if codex:
        return True, codex
    return False, "Codex not found (fallback unavailable)"


def check_git():
    """Check if git is available."""
    git = shutil.which("git")
    if git:
        return True, git
    return False, "Git not found"


def check_repo_root():
    """Check if we're in a git repository."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, "Not in a git repository"
    except Exception:
        return False, "Git check failed"


def main():
    checks = [
        ("OpenCode", check_opencode),
        ("Codex (fallback)", check_codex),
        ("Git", check_git),
        ("Git Repository", check_repo_root),
    ]
    
    all_ok = True
    for name, check_fn in checks:
        ok, details = check_fn()
        status = "✓" if ok else "✗"
        print(f"{status} {name}: {details}")
        if not ok:
            all_ok = False
    
    if all_ok:
        print("\n✓ All checks passed!")
        return 0
    else:
        print("\n✗ Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())