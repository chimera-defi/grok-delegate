"""Pinned tests for the canonical estimated_tokens_saved derivation.

Byte-identical across delegate-extras/shared/ and every wrapper's scripts/ so that any
drift in one vendored copy fails that repo's CI. See
docs/workorder_standardize_tokens_saved_formula_20260701.md.
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_module():
    """Locate tokens_saved.py regardless of repo test layout (walks up a few levels)."""
    directory = _HERE
    for _ in range(4):
        for cand in (
            os.path.join(directory, "tokens_saved.py"),
            os.path.join(directory, "scripts", "tokens_saved.py"),
        ):
            if os.path.exists(cand):
                return cand
        directory = os.path.dirname(directory)
    raise FileNotFoundError("tokens_saved.py not found near " + _HERE)


_PATH = _find_module()
_spec = importlib.util.spec_from_file_location("tokens_saved_under_test", _PATH)
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)


def test_multiplier_is_three():
    assert ts.DEFAULT_MULTIPLIER == 3


def test_saved_basic():
    assert ts.estimated_tokens_saved(1000, 200) == 2800


def test_saved_clamps_at_zero():
    assert ts.estimated_tokens_saved(100, 500) == 0


def test_saved_tolerates_none_output():
    assert ts.estimated_tokens_saved(1000, None) == 3000


def test_saved_explicit_multiplier():
    assert ts.estimated_tokens_saved(1000, 0, 1) == 1000


def test_resolve_prefers_measured_parent_context():
    assert ts.resolve_parent_tokens({"metrics": {"parent_context_tokens": 1000}}, 200) == 1000


def test_resolve_falls_back_to_input_when_absent():
    assert ts.resolve_parent_tokens({"metrics": {}}, 200) == 200


def test_resolve_falls_back_when_metric_zero():
    assert ts.resolve_parent_tokens({"metrics": {"parent_context_tokens": 0}}, 350) == 350


def test_resolve_handles_missing_metrics_key():
    assert ts.resolve_parent_tokens({}, 42) == 42


def test_resolve_handles_non_dict_envelope():
    assert ts.resolve_parent_tokens(None, 7) == 7


def test_end_to_end_uses_measured_over_input():
    # measured parent context (1000) preferred over input (200): 1000*3 - 500
    pt = ts.resolve_parent_tokens({"metrics": {"parent_context_tokens": 1000}}, 200)
    assert ts.estimated_tokens_saved(pt, 500) == 2500
