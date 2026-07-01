#!/usr/bin/env python3
"""Plan + delegate execution through Grok Build via OpenCode with fallback and telemetry."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import shutil
import re
import os
import sys
import threading
import uuid
from pathlib import Path


def script_root() -> Path:
    return Path(__file__).resolve().parent


def record_telemetry(
    repo_root: Path,
    status: str,
    task_class: str,
    model_used: str,
    fallback_used: bool,
    fallback_reason: str,
    parent_context_tokens: int,
    delegate_input_tokens: int,
    delegate_output_tokens: int,
    estimated_tokens_saved: int,
    latency_ms: float,
    estimated_cost_usd: float,
    estimated_savings_usd: float,
    meta: dict,
) -> None:
    """Record delegation event to telemetry."""
    try:
        telemetry_cmd = [
            str(script_root() / "grok_delegate_telemetry.py"),
            "record",
            "--repo-root",
            str(repo_root),
            "--event-uuid",
            uuid.uuid4().hex,
            "--event",
            "delegate_invocation",
            "--status",
            status,
            "--task-class",
            task_class,
            "--model-used",
            model_used,
            "--parent-context-tokens",
            str(parent_context_tokens),
            "--delegate-input-tokens",
            str(delegate_input_tokens),
            "--delegate-output-tokens",
            str(delegate_output_tokens),
            "--estimated-tokens-saved",
            str(estimated_tokens_saved),
            "--latency-ms",
            str(latency_ms),
            "--estimated-cost-usd",
            str(round(estimated_cost_usd, 6)),
            "--estimated-savings-usd",
            str(round(estimated_savings_usd, 6)),
            "--meta",
            json.dumps(meta),
        ]

        if fallback_used:
            telemetry_cmd += ["--fallback-used", "--fallback-reason", fallback_reason]

        subprocess.run(telemetry_cmd, capture_output=True, text=True, check=False)
    except Exception:
        # Telemetry failures should not break delegation
        pass


def skill_root() -> Path:
    return script_root().parent


def current_repo_root(default_root: Path | None = None) -> Path:
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
    if default_root is not None:
        return default_root.resolve()
    return Path.cwd()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing required config file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_repo_config(repo_root: Path, config: dict) -> dict:
    """Load per-repo overrides from .grok-delegate.json in repo root."""
    repo_config_path = repo_root / ".grok-delegate.json"
    if repo_config_path.exists():
        try:
            overrides = json.loads(repo_config_path.read_text(encoding="utf-8"))
            merged = dict(config)
            merged.update(overrides)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return config


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def call_opencode(task: str, timeout: int) -> tuple[int, str, str, float]:
    """Call OpenCode with Grok Build model."""
    start = time.perf_counter()
    env = os.environ.copy()
    env["GROK_DELEGATE_ACTIVE"] = "1"
    
    try:
        # Use OpenCode CLI with Grok Build
        cmd = ["opencode", "--task", task, "--model", "grok-build"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return proc.returncode, proc.stdout, proc.stderr, latency_ms
    except subprocess.TimeoutExpired:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return 124, "", f"timeout after {timeout}s", latency_ms
    except FileNotFoundError:
        return 127, "", "opencode binary not found - install via: curl -fsSL https://opencode.ai/install | bash", (time.perf_counter() - start) * 1000.0


def detect_auth_error(stderr: str) -> bool:
    """Detect authentication / session expiry patterns that require manual resume."""
    if not stderr:
        return False
    patterns = [
        r"auth",
        r"authentication",
        r"unauthorized",
        r"401",
        r"403",
        r"session",
        r"expired",
        r"token",
        r"credential",
        r"login",
        r"oauth",
        r"sign.in",
        r"resume",
        r"re-auth",
        r"connect",
        r"xai",
    ]
    lower = stderr.lower()
    return any(re.search(p, lower) for p in patterns)


def classify_error(rc: int, stderr: str, schema_valid: bool) -> str:
    """Categorize failure reason for telemetry and user guidance."""
    if rc == 124:
        return "timeout"
    if rc == 127:
        return "opencode_not_found"
    if detect_auth_error(stderr):
        return "auth_error"
    if rc != 0:
        return "provider_error"
    if not schema_valid:
        return "schema_invalid"
    return "unknown"


def load_templates() -> dict[str, dict]:
    """Load task templates from prompts/templates.json."""
    tpl_path = skill_root() / "prompts" / "templates.json"
    if not tpl_path.exists():
        return {}
    try:
        return json.loads(tpl_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def list_templates() -> None:
    """Print available task templates."""
    templates = load_templates()
    if not templates:
        print("No templates found.")
        return
    print("Available templates:")
    for name, info in sorted(templates.items()):
        print(f"  {name:20s}  {info.get('task_class', 'unknown'):15s}  {info.get('description', '')}")


def apply_template(name: str) -> tuple[str, str] | None:
    """Return (task_text, task_class) for a template name, or None if not found."""
    templates = load_templates()
    tpl = templates.get(name)
    if not tpl:
        return None
    return str(tpl.get("template", "")), str(tpl.get("task_class", "implement"))


def estimate_repo_scale(repo_root: Path) -> dict[str, float | int]:
    """Estimate repo size for timeout scaling. Fast, approximate."""
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {"files": 0, "mb": 0}
        files = len(proc.stdout.strip().splitlines())
        # Approximate size via git ls-files with du fallback
        du_proc = subprocess.run(
            ["du", "-sm", "."],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        mb = 0
        if du_proc.returncode == 0:
            parts = du_proc.stdout.strip().split()
            if parts:
                try:
                    mb = int(parts[0])
                except ValueError:
                    pass
        return {"files": files, "mb": mb}
    except Exception:
        return {"files": 0, "mb": 0}


_history_lock = threading.Lock()


def _redact_sensitive(text: str) -> str:
    """Strip likely tokens/secrets from stderr before persisting to telemetry."""
    patterns = [
        (r"(?i)(bearer\s+)[a-z0-9_\-]{20,}", r"\1<REDACTED>"),
        (r"(?i)(token[=:]\s*)[a-z0-9_\-]{20,}", r"\1<REDACTED>"),
        (r"(?i)(api[_\-]?key[=:]\s*)[a-z0-9_\-]{20,}", r"\1<REDACTED>"),
        (r"(?i)(session[=:]\s*)[a-z0-9_\-]{20,}", r"\1<REDACTED>"),
        (r"(?i)(signature[=:]\s*)0x[a-f0-9]{20,}", r"\1<REDACTED>"),
    ]
    for pat, repl in patterns:
        text = re.sub(pat, repl, text)
    return text


def _maybe_rotate(path: Path, max_bytes: int = 10_485_760) -> None:
    """Rotate a JSONL file if it exceeds max_bytes (default 10 MB)."""
    if not path.exists():
        return
    try:
        if path.stat().st_size <= max_bytes:
            return
    except OSError:
        return
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


def save_task_to_history(repo_root: Path, task: str) -> None:
    """Append task to local history file for --last support."""
    history_path = repo_root / "artifacts" / "grok-delegate" / "history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(history_path)
    entry = {"task": task, "timestamp": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}
    with _history_lock:
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def load_last_task(repo_root: Path) -> str:
    """Load the most recent task from history. Tolerates corrupted tail lines."""
    history_path = repo_root / "artifacts" / "grok-delegate" / "history.jsonl"
    if not history_path.exists():
        return ""
    try:
        lines = history_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        if not lines:
            return ""
        # Walk backwards from tail to find first valid JSON line
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
                return str(last.get("task", ""))
            except json.JSONDecodeError:
                continue
        return ""
    except (json.JSONDecodeError, OSError):
        return ""


def compute_timeout(
    base_timeout: int,
    task_class: str,
    config: dict,
    repo_scale: dict[str, float | int],
    override: int | None = None,
) -> int:
    """Scale timeout by repo size and task class. Capped at 300s unless overridden."""
    if override is not None and override > 0:
        return override

    # Grok Build is fast, but we still scale for large repos
    scale = 1.0
    if task_class == "implement":
        scale = 1.5
    elif task_class == "refactor":
        scale = 2.0
    elif task_class == "architecture":
        scale = 1.8

    files = int(repo_scale.get("files", 0))
    mb = int(repo_scale.get("mb", 0))

    large_files = int(config.get("large_repo_threshold_files", 10000))
    large_mb = int(config.get("large_repo_threshold_mb", 500))
    large_mult = float(config.get("large_repo_timeout_multiplier", 2.0))

    xlarge_files = int(config.get("xlarge_repo_threshold_files", 50000))
    xlarge_mb = int(config.get("xlarge_repo_threshold_mb", 1000))
    xlarge_mult = float(config.get("xlarge_repo_timeout_multiplier", 3.0))

    repo_mult = 1.0
    if files >= xlarge_files or mb >= xlarge_mb:
        repo_mult = xlarge_mult
    elif files >= large_files or mb >= large_mb:
        repo_mult = large_mult

    computed = int(base_timeout * scale * repo_mult)
    # Cap at configured max_timeout_seconds (default 300s for Grok)
    max_default = int(config.get("max_timeout_seconds", 300))
    return min(computed, max_default)


def output_is_valid(text: str, required_sections: list[str], output_format: str = "markdown") -> bool:
    if not text.strip():
        return False
    if output_format == "json":
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False
    for section in required_sections:
        section = section.strip()
        if not section:
            continue
        heading = re.compile(rf"(?im)^#{{1,6}}\s*{re.escape(section)}\s*$")
        if not heading.search(text):
            return False
    return True


def _safe_context_file(context_file: str | None, repo_root: Path) -> str | None:
    """Validate context-file path to prevent directory traversal outside repo."""
    if not context_file:
        return None
    try:
        path = (repo_root / context_file).resolve()
        # Ensure resolved path is inside repo_root
        path.relative_to(repo_root.resolve())
        return str(path)
    except (ValueError, RuntimeError):
        sys.stderr.write(f"[grok-delegate] context-file escapes repo boundary: {context_file}\n")
        return None


def build_envelope(task: str, task_class: str, context_file: str | None, workspace: str) -> dict:
    """Build delegation envelope with structured metadata."""
    envelope = {
        "goal": task,
        "task_class": task_class,
        "context_summary": f"Auto-generated envelope for task: {task[:100]}...",
        "constraints": {
            "max_output_tokens": 8000,
            "timeout_seconds": 120,
            "no_network": False
        },
        "acceptance": [
            "Answer stays within declared scope.",
            "Output is concise and directly actionable.",
            "Include concrete evidence with file/path and line references when analysis claims findings.",
            "If blocked, include exact missing input needed.",
        ],
        "output_schema": {
            "format": "markdown",
            "required_sections": ["Result", "Evidence", "Next steps"]
        },
        "write_scope": [workspace],
        "escalation_rules": [
            "If schema invalid twice, escalate to fallback.",
            "If timeout, run fallback immediately.",
            "If auth error, emit manual resume steps and do not fallback."
        ],
        "metrics": {
            "parent_context_tokens": estimate_tokens(task)
        }
    }
    
    if context_file:
        try:
            with open(context_file, 'r') as f:
                envelope["context"] = f.read()
        except Exception:
            pass
    
    return envelope


def health_check_quick(timeout: int = 15) -> tuple[bool, str]:
    """Fast health check: verify OpenCode is installed and accessible.
    Returns (ok, reason)."""
    if shutil.which("opencode") is None:
        return False, "opencode binary not found - install via: curl -fsSL https://opencode.ai/install | bash"
    
    env = os.environ.copy()
    env["GROK_DELEGATE_ACTIVE"] = "1"
    try:
        # Check if OpenCode can at least run help
        proc = subprocess.run(["opencode", "--help"], capture_output=True, text=True, timeout=timeout, check=False, env=env)
        if proc.returncode == 0:
            return True, ""
        return False, f"opencode error (rc={proc.returncode}): {proc.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return False, f"health check timed out after {timeout}s"
    except Exception as exc:
        return False, f"health check exception: {exc}"


def run_check(config: dict) -> int:
    """Pre-flight environment check."""
    checks: list[dict[str, str]] = []

    opencode_bin = shutil.which("opencode")
    codex_bin = shutil.which("codex")
    grok_delegate_bin = shutil.which("grok-delegate")

    checks.append({
        "name": "opencode",
        "status": "ok" if opencode_bin else "missing",
        "path": opencode_bin or "",
        "install_hint": "curl -fsSL https://opencode.ai/install | bash" if not opencode_bin else "",
    })
    checks.append({
        "name": "codex",
        "status": "ok" if codex_bin else "missing",
        "path": codex_bin or "",
    })
    checks.append({
        "name": "grok-delegate (shorthand)",
        "status": "ok" if grok_delegate_bin else "missing",
        "path": grok_delegate_bin or "",
    })

    # Fast health check
    health_ok, health_reason = health_check_quick(timeout=15)
    checks.append({
        "name": "opencode-health",
        "status": "ok" if health_ok else "error",
        "detail": health_reason,
    })

    all_ok = bool(opencode_bin) and bool(codex_bin) and health_ok

    result = {
        "all_ok": all_ok,
        "primary": "opencode",
        "fallback": "codex",
        "checks": checks,
        "config": {
            "model": config.get("model", "grok-build"),
            "fallback_model": config.get("fallback_model") or "default",
        },
    }
    print(json.dumps(result, indent=2))
    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Delegate tasks to Grok Build via OpenCode")
    parser.add_argument("--task", help="Task description")
    parser.add_argument("--task-class", choices=["implement", "refactor", "debug", "migrate", "architecture", "research"], default="implement")
    parser.add_argument("--workspace", help="Workspace path", default=".")
    parser.add_argument("--context-file", help="Additional context file")
    parser.add_argument("--timeout", type=int, help="Override timeout in seconds")
    parser.add_argument("--check", action="store_true", help="Run pre-flight checks")
    parser.add_argument("--templates", action="store_true", help="List available templates")
    parser.add_argument("--template", help="Use a task template")
    parser.add_argument("--last", action="store_true", help="Repeat last task")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    
    args = parser.parse_args()
    
    # Load config
    config_path = skill_root() / "config" / "default.json"
    try:
        config = load_json(config_path) if config_path.exists() else {}
    except FileNotFoundError:
        config = {}
    
    repo_root = current_repo_root()
    config = load_repo_config(repo_root, config)
    
    if args.check:
        return run_check(config)
    
    if args.templates:
        list_templates()
        return 0
    
    if args.last:
        task = load_last_task(repo_root)
        if not task:
            print("No previous task found in history.", file=sys.stderr)
            return 1
        args.task = task
    
    if args.template:
        result = apply_template(args.template)
        if not result:
            print(f"Template '{args.template}' not found.", file=sys.stderr)
            return 1
        task_text, task_class = result
        args.task = task_text
        args.task_class = task_class
    
    if not args.task:
        if args.interactive:
            args.task = input("Enter task: ")
        else:
            parser.print_help()
            return 1
    
    # Build envelope
    context_file = _safe_context_file(args.context_file, repo_root)
    envelope = build_envelope(args.task, args.task_class, context_file, args.workspace)
    
    # Save to history
    save_task_to_history(repo_root, args.task)
    
    # Compute timeout
    repo_scale = estimate_repo_scale(repo_root)
    timeout = compute_timeout(60, args.task_class, config, repo_scale, args.timeout)
    
    # Call OpenCode
    rc, stdout, stderr, latency = call_opencode(json.dumps(envelope), timeout)
    
    # Validate output
    required_sections = envelope.get("output_schema", {}).get("required_sections", ["Result", "Evidence", "Next steps"])
    output_format = envelope.get("output_schema", {}).get("format", "markdown")
    schema_valid = output_is_valid(stdout, required_sections, output_format)
    
    # Classify error
    error_type = classify_error(rc, stderr, schema_valid)
    
    # Record telemetry
    fallback_used = error_type != "unknown" and rc != 0
    fallback_reason = error_type if fallback_used else ""
    
    # Estimate tokens and costs
    parent_tokens = estimate_tokens(json.dumps(envelope))
    delegate_input_tokens = estimate_tokens(json.dumps(envelope))
    delegate_output_tokens = estimate_tokens(stdout) if stdout else 0
    estimated_tokens_saved = max(0, parent_tokens * 3 - delegate_output_tokens)
    
    # Simple cost estimation (Grokk Build pricing approximation)
    estimated_cost_usd = (delegate_input_tokens + delegate_output_tokens) * 0.000001  # $1 per 1M tokens
    estimated_savings_usd = estimated_tokens_saved * 0.000001
    
    telemetry_meta = {
        "repo_root": str(repo_root),
        "skill_root": str(skill_root()),
        "repo_scale": repo_scale,
        "timeout": timeout,
        "error_type": error_type,
        "schema_valid": schema_valid,
    }
    
    record_telemetry(
        repo_root=repo_root,
        status="ok" if rc == 0 and schema_valid else error_type,
        task_class=args.task_class,
        model_used="grok-build",
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        parent_context_tokens=parent_tokens,
        delegate_input_tokens=delegate_input_tokens,
        delegate_output_tokens=delegate_output_tokens,
        estimated_tokens_saved=estimated_tokens_saved,
        latency_ms=latency,
        estimated_cost_usd=estimated_cost_usd,
        estimated_savings_usd=estimated_savings_usd,
        meta=telemetry_meta,
    )
    
    # Handle auth errors with manual resume steps
    if error_type == "auth_error":
        print("[grok-delegate] Authentication error. Please run the following steps:", file=sys.stderr)
        print("1. Launch OpenCode: opencode", file=sys.stderr)
        print("2. Inside OpenCode, run: /connect", file=sys.stderr)
        print("3. Select 'xAI' as the service", file=sys.stderr)
        print("4. Choose your sign-in method:", file=sys.stderr)
        print("   - xAI Grok OAuth (SuperGrok Subscription) → opens browser")
        print("   - xAI Grok OAuth (Headless / Remote / VPS) → gives a code + URL", file=sys.stderr)
        print(file=sys.stderr)
        print("Once connected, retry your task.", file=sys.stderr)
        return 126
    
    # Handle OpenCode not found
    if error_type == "opencode_not_found":
        print("[grok-delegate] OpenCode is not installed.", file=sys.stderr)
        print("Install it with: curl -fsSL https://opencode.ai/install | bash", file=sys.stderr)
        return rc
    
    # Output result
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    
    # Fallback to Codex on failure
    if rc != 0 or not schema_valid:
        print(f"[grok-delegate] Grok Build failed ({error_type}), falling back to Codex...", file=sys.stderr)
        try:
            codex_cmd = ["codex", "exec"]
            _fb_model = config.get("fallback_model")
            if _fb_model and str(_fb_model).strip().lower() not in ("default", "spark", "null", "none"):
                codex_cmd += ["--model", str(_fb_model)]
            codex_cmd.append(args.task)
            codex_proc = subprocess.run(codex_cmd, capture_output=True, text=True, timeout=timeout * 2)
            print(codex_proc.stdout)
            if codex_proc.stderr:
                print(codex_proc.stderr, file=sys.stderr)
            return codex_proc.returncode
        except Exception as e:
            print(f"[grok-delegate] Fallback to Codex also failed: {e}", file=sys.stderr)
            return rc
    
    return 0


if __name__ == "__main__":
    sys.exit(main())