"""Canonical estimated_tokens_saved derivation, shared by all delegate wrappers.

Standardized 2026-07-01 per
docs/workorder_standardize_tokens_saved_formula_20260701.md (delegate-skill repo).

Single formula for all three wrappers so cross-delegate tokens_saved is comparable:

    parent_tokens = measured envelope.metrics.parent_context_tokens,
                    falling back to the delegate input size when absent/zero
    estimated_tokens_saved = max(0, parent_tokens * K - delegate_output_tokens)   # K = 3

K=3 is the ratified multiplier (a parent re-reading/reasoning over its context spends
~3x the raw tokens a delegate consumes). Forward-only: this changes how NEW telemetry
events compute the field; historical events are never rewritten, so each delegate's
tokens_saved series has a one-time step at the cutover.

Canonical home: delegate-extras/shared/tokens_saved.py. Every wrapper vendors a
byte-identical copy at scripts/tokens_saved.py (the core --task path must not depend on
the index repo being installed). Keep all copies identical; the pinned unit tests in
each repo enforce it.
"""

DEFAULT_MULTIPLIER = 3


def resolve_parent_tokens(envelope, delegate_input_tokens):
    """Measured parent context if present, else fall back to the delegate input size."""
    metrics = envelope.get("metrics") or {} if isinstance(envelope, dict) else {}
    parent_tokens = int(metrics.get("parent_context_tokens", 0) or 0)
    if parent_tokens > 0:
        return parent_tokens
    return max(0, int(delegate_input_tokens or 0))


def estimated_tokens_saved(parent_tokens, delegate_output_tokens, multiplier=DEFAULT_MULTIPLIER):
    """max(0, parent_tokens * K - delegate_output_tokens)."""
    return max(0, int(parent_tokens or 0) * int(multiplier) - int(delegate_output_tokens or 0))
