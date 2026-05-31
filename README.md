# Grok Delegate

Delegate bounded coding tasks to Grok Build model via OpenCode integration with envelope/fallback telemetry.

## Overview

Grok Delegate provides a structured wrapper around xAI's Grok Build model through the OpenCode CLI. It ensures proper task delegation with telemetry, fallback mechanisms, and authentication handling.

## Installation

1. **Install OpenCode** (one-time):
   ```bash
   curl -fsSL https://opencode.ai/install | bash
   ```

2. **Connect to xAI**:
   ```bash
   opencode
   /connect
   # Select "xAI" as the service
   # Choose your sign-in method:
   # - xAI Grok OAuth (SuperGrok Subscription) → opens browser
   # - xAI Grok OAuth (Headless / Remote / VPS) → gives a code + URL
   ```

3. **Install this skill**:
   ```bash
   # Link to your skills directory
   ln -s /home/agents/workspace/grok-delegate /home/agents/.agents/skills/grok-delegate
   ```

## Usage

### Basic delegation
```bash
grok-delegate --task "Implement a new feature for user authentication"
```

### With task class
```bash
grok-delegate --task "Refactor the user service" --task-class refactor
```

### Using templates
```bash
grok-delegate --template fix-bug --task "Login fails when password contains special characters"
```

### Interactive mode
```bash
grok-delegate --interactive
```

### Environment check
```bash
grok-delegate --check
```

## Task Classes

- `implement` - New feature implementation
- `refactor` - Code restructuring and improvement  
- `debug` - Bug investigation and fixing
- `migrate` - Code migration and upgrades
- `architecture` - Architectural analysis and suggestions
- `research` - Codebase exploration and analysis

## Configuration

Create a `.grok-delegate.json` file in your repo root for per-repo settings:

```json
{
  "base_timeout_seconds": 90,
  "max_timeout_seconds": 600,
  "large_repo_threshold_files": 20000
}
```

## Authentication

If you encounter authentication errors:

1. Launch OpenCode: `opencode`
2. Run: `/connect`
3. Select "xAI" as the service
4. Choose your sign-in method
5. After connecting, retry your task

## Fallback

If Grok Build is unavailable, the delegate automatically falls back to Codex for task completion.

## Telemetry

Task history and telemetry are stored in `artifacts/grok-delegate/` in your repository.

## License

MIT