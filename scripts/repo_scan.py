#!/usr/bin/env python3
"""Shared workspace repository discovery helpers."""
from __future__ import annotations

from pathlib import Path


def is_repo_root(path: Path) -> bool:
    return (path / ".git").exists()


def iter_workspace_repos(workspace_root: Path, include_worktrees: bool = True) -> list[Path]:
    repos: list[Path] = []
    seen: set[str] = set()
    root = workspace_root.resolve()

    def add_repo(path: Path) -> None:
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(root)
        except ValueError:
            return
        resolved = str(resolved_path)
        if resolved in seen:
            return
        seen.add(resolved)
        repos.append(path)

    for child in sorted(workspace_root.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        if is_repo_root(child):
            add_repo(child)
        if not include_worktrees:
            continue
        worktrees_root = child / ".worktrees"
        if not worktrees_root.is_dir():
            continue
        for worktree in sorted(worktrees_root.iterdir()):
            if worktree.is_dir() and not worktree.is_symlink() and is_repo_root(worktree):
                add_repo(worktree)
    return repos


def repo_label(repo: Path, workspace_root: Path) -> str:
    try:
        return repo.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return repo.name
