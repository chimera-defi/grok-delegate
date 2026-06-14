---
name: grok-delegate
preamble-tier: 4
version: 0.1.1
description: "Delegate bounded coding tasks to Grok Build model via OpenCode integration with envelope/fallback telemetry."
triggers:
  - delegate to Grok
  - grok-delegate
  - use Grok for a bounded task
  - multi-file refactor via Grok
  - large codebase implementation
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
---

# Grok Delegate

Use when the task benefits from Grok Build's exceptional speed and large codebase intelligence. Ideal for non-trivial coding tasks, multi-file refactoring, and repository-wide understanding.

## Required Commands

```bash
./scripts/env_check.py
./scripts/plan_prompt.py --task "..."
./scripts/delegate.py --task "..." --context-file /tmp/context.txt
```

Do not call OpenCode directly; wrapper usage is required for envelope, fallback, and telemetry.

## Envelope Requirements

Include goal, task class (`implement`, `refactor`, `debug`, `migrate`, `architecture`), scope, constraints, acceptance checks, and output schema.

## Failure Policy

- Timeout/provider/schema issues: retry once where supported, then Codex fallback.
- Auth/session failure: print resume steps, exit code 126, no blind fallback.
- Always record telemetry: model, latency, fallback reason, estimated token savings.

## Support Commands

```bash
./scripts/env_check.py --repo-root .
./scripts/detect_bypass.py --nudge
./scripts/grok_delegate_telemetry.py summary --days 14
```

Use `devin-delegate` for browser/sandbox-heavy tasks. Use `kimi-delegate` for cheap bounded research. Details: `references/architecture.md`.