#!/usr/bin/env python3
"""Detect raw OpenCode calls that bypass the grok-delegate skill wrapper."""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from repo_scan import iter_workspace_repos, repo_label
except ModuleNotFoundError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parent))
    from repo_scan import iter_workspace_repos, repo_label

# Pattern matching legitimate grok-delegate wrapper invocations.
DELEGATE_CMD_RE = re.compile(
    r"(?:^|\s)(?:\./)?(?:skills/grok-delegate/scripts/delegate\.py|grok-delegate)(?:\s|$)",
    re.IGNORECASE,
)

# Pattern matching raw opencode calls — only when actually invoked, not when
# the name appears as a path argument or inside a string literal.
GROK_SUBAGENT_RE = re.compile(
    r"(?:^|\s)opencode\b",
)


def is_false_positive_command(command: str) -> bool:
    """Return True if the command is an install/check, not a delegation bypass."""
    fp_patterns = [
        r"opencode\s+--version",
        r"opencode\s+--help",
        r"which\s+opencode",
        r"command\s+-v\s+opencode",
        r"#.*opencode",
        r"echo.*opencode",
    ]
    return any(re.search(p, command) for p in fp_patterns)


def collect_session_files(base: Path, cutoff_ts: float) -> list[Path]:
    files: list[Path] = []
    for path in base.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff_ts:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def parse_bypasses_claude(path: Path) -> list[dict[str, Any]]:
    """Parse a Claude session JSONL file for raw opencode bypass calls."""
    bypasses: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return bypasses
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message", {})
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "tool_use" or item.get("name") != "Bash":
                continue
            command = item.get("input", {}).get("command", "")
            if not isinstance(command, str):
                continue
            if is_false_positive_command(command):
                continue
            if GROK_SUBAGENT_RE.search(command) and not DELEGATE_CMD_RE.search(command):
                ts = event.get("timestamp", "")
                bypasses.append({
                    "source": "claude",
                    "session_file": str(path),
                    "command": command,
                    "timestamp": ts,
                })
    return bypasses


def detect_bypasses(
    workspace_root: Path,
    days: int,
    repo_filter: Path | None = None,
) -> dict[str, Any]:
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff_dt.timestamp()

    if repo_filter is not None:
        repo_paths = [repo_filter]
    else:
        repo_paths = iter_workspace_repos(workspace_root, include_worktrees=True)

    claude_sessions_root = Path.home() / ".claude" / "projects"
    session_files = collect_session_files(claude_sessions_root, cutoff_ts) if claude_sessions_root.exists() else []

    all_bypasses: list[dict[str, Any]] = []
    for session_file in session_files:
        hits = parse_bypasses_claude(session_file)
        all_bypasses.extend(hits)

    total_sessions = len(session_files)
    bypass_count = len(all_bypasses)
    bypass_rate = round(bypass_count / total_sessions * 100, 1) if total_sessions else 0.0

    return {
        "days": days,
        "total_sessions_scanned": total_sessions,
        "bypass_count": bypass_count,
        "bypass_rate_pct": bypass_rate,
        "bypasses": all_bypasses,
    }


def nudge_report(report: dict[str, Any]) -> str:
    count = report["bypass_count"]
    rate = report["bypass_rate_pct"]
    if count == 0:
        return "[grok-delegate] No bypass calls detected. Good hygiene!"
    lines = [
        f"[grok-delegate] BYPASS ALERT: {count} raw opencode call(s) detected ({rate}% of sessions).",
        "Use grok-delegate wrapper instead of calling opencode directly.",
        "Bypasses skip envelope, fallback, and telemetry.",
        "",
    ]
    for b in report["bypasses"][:5]:
        lines.append(f"  {b['timestamp']}: {b['command'][:80]}")
    if count > 5:
        lines.append(f"  ... and {count - 5} more")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect raw opencode calls bypassing grok-delegate.")
    parser.add_argument("--workspace-root", default=str(Path.home() / "workspace"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--nudge", action="store_true", help="Print human-readable nudge report")
    parser.add_argument("--watch", action="store_true", help="Continuously watch for bypasses")
    parser.add_argument("--watch-interval", type=int, default=60)
    parser.add_argument("--output", help="Write JSON report to file")
    parser.add_argument("--repo", help="Limit scan to a single repo path")
    args = parser.parse_args()

    repo_filter = Path(args.repo).resolve() if args.repo else None

    if args.watch:
        print("[grok-delegate] Watching for bypass calls (Ctrl+C to stop)...")
        prev = 0
        while True:
            report = detect_bypasses(Path(args.workspace_root).resolve(), args.days, repo_filter=repo_filter)
            current = report["bypass_count"]
            if current != prev:
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] bypasses={current} rate={report['bypass_rate_pct']}%")
                if current > 0:
                    print(nudge_report(report))
                prev = current
            try:
                time.sleep(args.watch_interval)
            except KeyboardInterrupt:
                print("\nWatch stopped.")
                return 0

    report = detect_bypasses(Path(args.workspace_root).resolve(), args.days, repo_filter=repo_filter)

    if args.nudge:
        print(nudge_report(report))
        return 0

    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
