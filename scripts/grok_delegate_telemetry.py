#!/usr/bin/env python3
"""Telemetry store and summaries for grok-delegate."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def repo_root_from_script() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path(__file__).resolve().parents[3]


def events_path(repo_root: Path) -> Path:
    return repo_root / "artifacts" / "grok-delegate" / "events.jsonl"


def _maybe_rotate(path: Path, max_bytes: int = 10_485_760) -> None:
    """Rotate a JSONL file if it exceeds max_bytes (default 10 MB)."""
    if not path.exists():
        return
    try:
        if path.stat().st_size <= max_bytes:
            return
    except OSError:
        return
    # Rotate: .3 -> .4, .2 -> .3, .1 -> .2, current -> .1
    for i in range(3, 0, -1):
        older = path.with_suffix(f".jsonl.{i}")
        newer = path.with_suffix(f".jsonl.{i + 1}")
        if older.exists():
            try:
                older.rename(newer)
            except OSError:
                pass
    try:
        path.rename(path.with_suffix(".jsonl.1"))
    except OSError:
        pass


def record_event(repo_root: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    path = events_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_events(repo_root: Path, days: int | None = None, task_class: str | None = None, status: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    path = events_path(repo_root)
    if not path.exists():
        return []

    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff is not None:
                raw_ts = event.get("timestamp")
                if isinstance(raw_ts, str):
                    try:
                        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    except ValueError:
                        ts = None
                    if ts is not None and ts < cutoff:
                        continue
            # Apply filters
            if task_class is not None and str(event.get("task_class", "")) != task_class:
                continue
            if status is not None and str(event.get("status", "")) != status:
                continue
            if model is not None and str(event.get("model_used", "")) != model:
                continue
            events.append(event)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter()
    by_task_class = Counter()
    by_model = Counter()
    fallback_reasons = Counter()
    error_categories = Counter()
    by_repo_scale = Counter()

    calls = 0
    fallback_count = 0
    total_latency = 0.0
    latency_count = 0
    total_saved = 0
    total_parent_tokens = 0
    total_cost_usd = 0.0
    total_savings_usd = 0.0
    auth_errors = 0
    timeouts = 0
    timeout_by_large_repo = 0

    for ev in events:
        if ev.get("event") != "delegate_invocation":
            continue
        calls += 1
        by_status[str(ev.get("status", "unknown"))] += 1
        by_task_class[str(ev.get("task_class", "unknown"))] += 1
        by_model[str(ev.get("model_used", "unknown"))] += 1

        if ev.get("fallback_used"):
            fallback_count += 1
            fallback_reasons[str(ev.get("fallback_reason", "unknown"))] += 1

        meta = ev.get("meta", {}) or {}
        ec = meta.get("error_category") if isinstance(meta, dict) else ""
        if ec:
            error_categories[str(ec)] += 1
        if str(ev.get("fallback_reason", "")) == "timeout":
            timeouts += 1
            repo_scale = meta.get("repo_scale") if isinstance(meta, dict) else {}
            if isinstance(repo_scale, dict):
                files = int(repo_scale.get("files", 0))
                mb = int(repo_scale.get("mb", 0))
                if files >= 10000 or mb >= 500:
                    timeout_by_large_repo += 1
        if str(ev.get("fallback_reason", "")) == "auth_error":
            auth_errors += 1

        repo_scale = meta.get("repo_scale") if isinstance(meta, dict) else {}
        if isinstance(repo_scale, dict):
            files = int(repo_scale.get("files", 0))
            if files >= 50000:
                by_repo_scale["xlarge"] += 1
            elif files >= 10000:
                by_repo_scale["large"] += 1
            else:
                by_repo_scale["normal"] += 1
        else:
            by_repo_scale["unknown"] += 1

        latency = ev.get("latency_ms")
        if isinstance(latency, (int, float)) and float(latency) >= 0:
            total_latency += float(latency)
            latency_count += 1

        saved = ev.get("estimated_tokens_saved")
        if isinstance(saved, int):
            total_saved += saved

        parent_tokens = ev.get("parent_context_tokens")
        if isinstance(parent_tokens, int) and parent_tokens > 0:
            total_parent_tokens += parent_tokens

        cost_usd = ev.get("estimated_cost_usd")
        if isinstance(cost_usd, (int, float)) and cost_usd >= 0:
            total_cost_usd += float(cost_usd)

        savings_usd = ev.get("estimated_savings_usd")
        if isinstance(savings_usd, (int, float)) and savings_usd >= 0:
            total_savings_usd += float(savings_usd)

    savings_pct = round((total_saved * 100.0 / total_parent_tokens), 2) if total_parent_tokens else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "delegate_calls": calls,
        "status": dict(by_status),
        "task_classes": dict(by_task_class),
        "models": dict(by_model),
        "fallback_rate_pct": round((fallback_count * 100.0 / calls), 2) if calls else 0.0,
        "fallback_reasons": dict(fallback_reasons),
        "error_categories": dict(error_categories),
        "auth_errors": auth_errors,
        "timeouts": timeouts,
        "timeouts_in_large_repos": timeout_by_large_repo,
        "repo_scale_distribution": dict(by_repo_scale),
        "avg_latency_ms": round(total_latency / latency_count, 2) if latency_count else 0.0,
        "estimated_tokens_saved": total_saved,
        "estimated_savings_pct": savings_pct,
        "total_cost_usd": round(total_cost_usd, 4),
        "total_savings_usd": round(total_savings_usd, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record")
    record.add_argument("--repo-root", type=Path, default=None)
    record.add_argument("--event-uuid", default="")
    record.add_argument("--event", default="delegate_invocation")
    record.add_argument("--status", default="ok")
    record.add_argument("--task-class", default="unknown")
    record.add_argument("--model-used", default="unknown")
    record.add_argument("--fallback-used", action="store_true")
    record.add_argument("--fallback-reason", default="")
    record.add_argument("--parent-context-tokens", type=int, default=0)
    record.add_argument("--delegate-input-tokens", type=int, default=0)
    record.add_argument("--delegate-output-tokens", type=int, default=0)
    record.add_argument("--estimated-tokens-saved", type=int, default=0)
    record.add_argument("--latency-ms", type=float, default=0.0)
    record.add_argument("--estimated-cost-usd", type=float, default=0.0)
    record.add_argument("--estimated-savings-usd", type=float, default=0.0)
    record.add_argument("--meta", default="")

    summary = sub.add_parser("summary")
    summary.add_argument("--repo-root", type=Path, default=None)
    summary.add_argument("--days", type=int, default=14)
    summary.add_argument("--task_class", type=str, default=None, help="Filter by task class (implement, debug, research, etc.)")
    summary.add_argument("--status", type=str, default=None, help="Filter by status (ok, error, timeout, etc.)")
    summary.add_argument("--model", type=str, default=None, help="Filter by model used")
    summary.add_argument("--alert", action="store_true", help="Exit non-zero if health thresholds exceeded")
    summary.add_argument("--fallback_threshold", type=float, default=15.0, help="Max acceptable fallback rate %")
    summary.add_argument("--auth_threshold", type=int, default=2, help="Max acceptable auth errors")

    args = parser.parse_args()
    root = args.repo_root if args.repo_root else repo_root_from_script()

    if args.command == "record":
        meta: dict[str, Any] = {}
        if args.meta:
            try:
                meta = json.loads(args.meta)
            except json.JSONDecodeError:
                meta = {"raw": args.meta}

        payload = {
            "uuid": args.event_uuid or uuid.uuid4().hex,
            "repo": root.name,
            "event": args.event,
            "status": args.status,
            "task_class": args.task_class,
            "model_used": args.model_used,
            "fallback_used": bool(args.fallback_used),
            "fallback_reason": args.fallback_reason,
            "parent_context_tokens": args.parent_context_tokens,
            "delegate_input_tokens": args.delegate_input_tokens,
            "delegate_output_tokens": args.delegate_output_tokens,
            "estimated_tokens_saved": args.estimated_tokens_saved,
            "latency_ms": args.latency_ms,
            "estimated_cost_usd": args.estimated_cost_usd,
            "estimated_savings_usd": args.estimated_savings_usd,
            "meta": meta,
        }
        record_event(root, payload)
        print(json.dumps({"ok": True, "path": str(events_path(root))}, indent=2))
        return 0

    events = load_events(root, days=args.days, task_class=args.task_class, status=args.status, model=args.model)
    data = summarize(events)
    print(json.dumps(data, indent=2))

    if args.alert:
        fallback_rate = data.get("fallback_rate_pct", 0.0)
        auth_errors = data.get("auth_errors", 0)
        if fallback_rate > args.fallback_threshold or auth_errors > args.auth_threshold:
            sys.stderr.write(
                f"ALERT: fallback_rate={fallback_rate}% (threshold={args.fallback_threshold}%), "
                f"auth_errors={auth_errors} (threshold={args.auth_threshold})\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())