"""Takopi command plugin for grok-delegate."""
from __future__ import annotations

import subprocess
from pathlib import Path

from takopi.api import CommandContext, CommandResult


class GrokCommand:
    id = "grok"
    description = "Delegate tasks to Grok Build via grok-delegate"

    async def handle(self, ctx: CommandContext) -> CommandResult | None:
        # Extract task from args
        if not ctx.args:
            return CommandResult(
                text="Usage: /grok <task description>\nExample: /grok Implement a new feature for user authentication"
            )

        task = " ".join(ctx.args)
        
        # Determine workspace path
        workspace = ctx.config_path.parent if ctx.config_path else Path.cwd()
        
        try:
            # Run grok-delegate with the task
            result = subprocess.run(
                [
                    "grok-delegate",
                    "--task", task,
                    "--workspace", str(workspace),
                    "--task-class", "implement"
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            if result.returncode == 0:
                return CommandResult(text=result.stdout)
            else:
                return CommandResult(
                    text=f"Grok delegate failed:\n{result.stderr}\n{result.stdout}"
                )
        except subprocess.TimeoutExpired:
            return CommandResult(text="Grok delegate timed out after 300 seconds")
        except Exception as e:
            return CommandResult(text=f"Error running grok-delegate: {e}")


BACKEND = GrokCommand()