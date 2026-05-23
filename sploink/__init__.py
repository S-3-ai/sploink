from sploink.wrap import wrap
from sploink import trace, index
from sploink.trace import workflow
from sploink.route import enable_routing, disable_routing, is_routing_enabled, step
from sploink.graph import Graph
from sploink.stack import Stack, Recommendation, pick_recommendation, explain_pick

# ─────────────────────────────────────────────────────────────────────────────
# Module-level configuration (the user's optimization preferences).
# Set via sploink.configure(optimize_for=...).
# ─────────────────────────────────────────────────────────────────────────────

_WEIGHTS: dict[str, float] = {"cost": 1/3, "latency": 1/3, "quality": 1/3}
_USER_CONFIGURED: bool = False  # flips to True on first configure() call

_ALIASES = {
    "cost":     {"cost": 1.0, "latency": 0.0, "quality": 0.0},
    "latency":  {"cost": 0.0, "latency": 1.0, "quality": 0.0},
    "quality":  {"cost": 0.0, "latency": 0.0, "quality": 1.0},
    "balanced": {"cost": 1/3, "latency": 1/3, "quality": 1/3},
    # Useful real-world presets:
    "cheap":     {"cost": 0.7, "latency": 0.2, "quality": 0.1},
    "fast":      {"cost": 0.1, "latency": 0.7, "quality": 0.2},
    "accurate":  {"cost": 0.1, "latency": 0.2, "quality": 0.7},
}


def configure(*, optimize_for: str | dict[str, float] = "balanced") -> None:
    """Declare what to optimize for. Affects pick_for(step_label) decisions.

    Args:
      optimize_for: Either a preset name (string) or a weights dict.
        Presets: "cost", "latency", "quality", "balanced", "cheap", "fast", "accurate".
        Dict: e.g. {"cost": 0.6, "latency": 0.3, "quality": 0.1}.
          Missing keys default to 0. Weights need not sum to 1 (scoring is
          a weighted sum; relative weights are what matter).
    """
    global _WEIGHTS, _USER_CONFIGURED
    if isinstance(optimize_for, str):
        if optimize_for not in _ALIASES:
            raise ValueError(
                f"unknown preset {optimize_for!r}. Use one of {list(_ALIASES)} "
                "or pass a weights dict."
            )
        _WEIGHTS = dict(_ALIASES[optimize_for])
    elif isinstance(optimize_for, dict):
        _WEIGHTS = dict(optimize_for)
    else:
        raise TypeError("optimize_for must be a string preset or a weights dict")
    _USER_CONFIGURED = True


def _has_user_configured() -> bool:
    """Internal: has the user explicitly called configure()?

    sploink.route uses this to decide whether to consult the curated index
    (pick_for) or fall back to the legacy static router rules. Keeps v0.1.4
    upgrades behavior-preserving until the user opts in.
    """
    return _USER_CONFIGURED


def get_weights() -> dict[str, float]:
    """Return the current optimization weights."""
    return dict(_WEIGHTS)


def pick_for(step_label: str) -> Recommendation | None:
    """Pick the highest-scoring Recommendation for a step under current weights.

    Convenience wrapper around sploink.stack.pick_recommendation that uses
    the module-level weights set via sploink.configure().
    """
    return pick_recommendation(step_label, weights=_WEIGHTS)


__all__ = [
    # Core observability + routing
    "wrap",
    "trace",
    "workflow",
    "enable_routing",
    "disable_routing",
    "is_routing_enabled",
    "step",
    # Graph IR
    "Graph",
    # Composable AI — Stacks, Recommendations, the curated index
    "Stack",
    "Recommendation",
    "index",
    "configure",
    "get_weights",
    "pick_for",
    "pick_recommendation",
    "explain_pick",
]
