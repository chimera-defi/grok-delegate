#!/usr/bin/env bash
# Install grok-delegate wrappers, links, and run environment verification.
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$SKILL_ROOT/scripts"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$BIN_DIR" "$HOME/.agents/skills" "$HOME/.openclaw/skills" "${CODEX_HOME:-$HOME/.codex}/skills"

# Enable local hooks for attribution/commit format checks.
if [ -d "$SKILL_ROOT/.githooks" ]; then
  git -C "$SKILL_ROOT" config core.hooksPath .githooks || true
fi

# Install canonical skill links used by agent runtimes.
ln -sfn "$SKILL_ROOT" "$HOME/.agents/skills/grok-delegate"
ln -sfn "$HOME/.agents/skills/grok-delegate" "$HOME/.openclaw/skills/grok-delegate"
ln -sfn "$SKILL_ROOT" "${CODEX_HOME:-$HOME/.codex}/skills/grok-delegate"

# Install grok-delegate binary wrapper.
cat > "$BIN_DIR/grok-delegate" <<WRAP
#!/usr/bin/env bash
exec "$SCRIPTS/delegate.py" "\$@"
WRAP
chmod +x "$BIN_DIR/grok-delegate"

echo "Linked grok-delegate -> $SCRIPTS/delegate.py"

# Run environment check to confirm everything is wired.
echo ""
echo "Running env_check..."
python3 "$SCRIPTS/env_check.py" && echo "env_check: OK" || echo "env_check: WARNINGS (see above)"
