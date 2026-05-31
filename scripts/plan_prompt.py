#!/usr/bin/env python3
"""Generate structured delegation envelopes for Grok Build."""
import argparse
import json
import sys
from pathlib import Path


def script_root() -> Path:
    return Path(__file__).resolve().parent


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def build_envelope(task: str, task_class: str = "implement") -> dict:
    """Build a structured delegation envelope."""
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
            "For browser tasks, include screenshot paths or URL states as evidence."
        ],
        "output_schema": {
            "format": "markdown",
            "required_sections": ["Result", "Evidence", "Next steps"]
        },
        "write_scope": ["."],
        "escalation_rules": [
            "If schema invalid twice, escalate to fallback.",
            "If timeout, run fallback immediately.",
            "If auth error, emit manual resume steps and do not fallback."
        ],
        "metrics": {
            "parent_context_tokens": estimate_tokens(task)
        }
    }
    return envelope


def main():
    parser = argparse.ArgumentParser(description="Generate delegation envelope")
    parser.add_argument("--task", required=True, help="Task description")
    parser.add_argument("--task-class", choices=["implement", "refactor", "debug", "migrate", "architecture", "research"], default="implement")
    parser.add_argument("--context-file", help="Additional context file to include")
    
    args = parser.parse_args()
    
    envelope = build_envelope(args.task, args.task_class)
    
    if args.context_file:
        try:
            with open(args.context_file, 'r') as f:
                envelope["context"] = f.read()
        except Exception as e:
            print(f"Warning: Could not read context file: {e}", file=sys.stderr)
    
    print(json.dumps(envelope, indent=2))


if __name__ == "__main__":
    main()