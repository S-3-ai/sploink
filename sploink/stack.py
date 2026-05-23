"""Stack + Recommendation — composable (model x provider x hardware) units.

A Stack is sploink's unit of "what to call for an LLM step." It bundles three
independent composable axes:

  Stack = (model name, provider, hardware architecture) + cost metadata

A Recommendation pairs a Stack with a step_label and empirically-measured
quality + latency on that step type. Recommendations live in `sploink.index`
and are the curated knowledge sploink ships.

The scoring function pick_recommendation() applies the user's declared
optimization weights (cost / latency / quality) to rank Recommendations
within a step type and return the highest-scoring one. Pure-Python, no ML,
deterministic given the same inputs.

This module has no side effects. The Stack abstraction is also user-extensible:
customers can create their own Stack + Recommendation entries and add them to
the index at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# Hardware architecture categories — must match sploink.trace.HardwareType.
HARDWARE_TYPES = ("cpu", "gpu", "lpu", "tpu", "npu", "wafer_scale", "frontier_api")


@dataclass(frozen=True)
class Stack:
    """A composable (model, provider, hardware) unit.

    A Stack is reusable across step types — the same Stack can be cited by
    multiple Recommendations. Cost is stored on the Stack because it's
    intrinsic to the (model, provider) pair; quality is per-step (and lives
    on the Recommendation, not the Stack).
    """
    name: str                          # short stable identifier, e.g. "groq-llama8b-lpu"
    model: str                         # e.g. "llama-3.1-8b-instant"
    provider: str                      # e.g. "groq" / "ollama" / "anthropic" / "together"
    hardware_type: str                 # one of HARDWARE_TYPES
    cost_in_per_million: float = 0.0   # USD per 1M input tokens
    cost_out_per_million: float = 0.0  # USD per 1M output tokens
    notes: str = ""                    # human-readable context (quantization, license, etc.)

    def __post_init__(self) -> None:
        if self.hardware_type not in HARDWARE_TYPES:
            raise ValueError(
                f"hardware_type {self.hardware_type!r} not in {HARDWARE_TYPES}"
            )

    def expected_cost_usd(self, tokens_in: int, tokens_out: int) -> float:
        return (
            tokens_in  * self.cost_in_per_million  / 1_000_000
            + tokens_out * self.cost_out_per_million / 1_000_000
        )


@dataclass(frozen=True)
class Recommendation:
    """A curated entry: which Stack is good for which step type, with measured metrics.

    Each Recommendation should correspond to a real, validated benchmark run
    (or a trusted public benchmark). The notes + validated_on fields exist
    to make the provenance traceable.
    """
    step_label: str                    # which step type this entry recommends for
    stack: Stack
    median_latency_ms: int             # P50 wall-clock per call
    quality_score: float               # 0..1, normalized benchmark score (F1, accuracy, etc.)
    notes: str = ""                    # what was measured + any caveats
    validated_on: str = ""             # benchmark / dataset / date stamp


# Typical token-count assumption used when comparing per-call cost across
# Recommendations. Tuned to roughly match the bench's average step shape.
_DEFAULT_TYPICAL_TOKENS_IN = 500
_DEFAULT_TYPICAL_TOKENS_OUT = 100


def _normalize(value: float, lo: float, hi: float, invert: bool) -> float:
    """Map value in [lo, hi] to [0, 1]. If invert, lower-is-better → higher score."""
    if hi == lo:
        return 0.5
    score = (value - lo) / (hi - lo)
    return 1.0 - score if invert else score


def pick_recommendation(
    step_label: str,
    weights: dict[str, float] | None = None,
    recommendations: Iterable[Recommendation] | None = None,
    *,
    typical_tokens_in: int = _DEFAULT_TYPICAL_TOKENS_IN,
    typical_tokens_out: int = _DEFAULT_TYPICAL_TOKENS_OUT,
) -> Recommendation | None:
    """Pick the highest-scoring Recommendation for a step type.

    Args:
      step_label: e.g. "classify", "rerank", "extract", "reason", "verify"
      weights:   dict like {"cost": 0.6, "latency": 0.3, "quality": 0.1}.
                 Defaults to balanced (cost=latency=quality=1/3) when None.
                 Missing keys default to 0. Negative weights are allowed if
                 you want to discourage a dimension explicitly.
      recommendations: Iterable of Recommendation to choose from. Defaults to
                       sploink.index.RECOMMENDATIONS (the curated catalog).
      typical_tokens_in / typical_tokens_out: used to compute expected cost
                       per call (cost only matters comparatively, so the
                       absolute token counts don't affect the winner — only
                       their ratio across candidates does).

    Returns:
      The Recommendation with the highest weighted score, or None if no
      candidate exists for the given step_label.
    """
    if recommendations is None:
        # Late import so this module has no hard dependency on the index file.
        from sploink.index import RECOMMENDATIONS
        recommendations = RECOMMENDATIONS

    candidates = [r for r in recommendations if r.step_label == step_label]
    if not candidates:
        return None

    if weights is None:
        weights = {"cost": 1/3, "latency": 1/3, "quality": 1/3}

    costs   = [r.stack.expected_cost_usd(typical_tokens_in, typical_tokens_out) for r in candidates]
    lats    = [float(r.median_latency_ms) for r in candidates]
    quals   = [r.quality_score for r in candidates]

    cmin, cmax = min(costs), max(costs)
    lmin, lmax = min(lats), max(lats)
    qmin, qmax = min(quals), max(quals)

    def score(idx: int, r: Recommendation) -> float:
        c = _normalize(costs[idx], cmin, cmax, invert=True)   # lower cost  → higher score
        l = _normalize(lats[idx],  lmin, lmax, invert=True)   # lower lat   → higher score
        q = _normalize(quals[idx], qmin, qmax, invert=False)  # higher qual → higher score
        return (
            weights.get("cost",    0.0) * c
            + weights.get("latency", 0.0) * l
            + weights.get("quality", 0.0) * q
        )

    return max(enumerate(candidates), key=lambda iv: score(iv[0], iv[1]))[1]


def explain_pick(
    step_label: str,
    weights: dict[str, float] | None = None,
    recommendations: Iterable[Recommendation] | None = None,
) -> list[dict[str, Any]]:
    """Return per-candidate score breakdown for debugging / docs.

    Useful for: "why did sploink pick this Stack for my step?" — surfaces the
    cost/latency/quality scores and the weighted total per candidate.
    """
    if recommendations is None:
        from sploink.index import RECOMMENDATIONS
        recommendations = RECOMMENDATIONS

    candidates = [r for r in recommendations if r.step_label == step_label]
    if not candidates:
        return []

    if weights is None:
        weights = {"cost": 1/3, "latency": 1/3, "quality": 1/3}

    costs = [r.stack.expected_cost_usd(_DEFAULT_TYPICAL_TOKENS_IN, _DEFAULT_TYPICAL_TOKENS_OUT) for r in candidates]
    lats  = [float(r.median_latency_ms) for r in candidates]
    quals = [r.quality_score for r in candidates]

    cmin, cmax = min(costs), max(costs)
    lmin, lmax = min(lats), max(lats)
    qmin, qmax = min(quals), max(quals)

    out = []
    for i, r in enumerate(candidates):
        c_norm = _normalize(costs[i], cmin, cmax, invert=True)
        l_norm = _normalize(lats[i],  lmin, lmax, invert=True)
        q_norm = _normalize(quals[i], qmin, qmax, invert=False)
        total = (
            weights.get("cost",    0.0) * c_norm
            + weights.get("latency", 0.0) * l_norm
            + weights.get("quality", 0.0) * q_norm
        )
        out.append({
            "stack":      r.stack.name,
            "cost_usd":   round(costs[i], 8),
            "latency_ms": int(lats[i]),
            "quality":    round(quals[i], 3),
            "score":      round(total, 4),
        })
    out.sort(key=lambda d: -d["score"])
    return out
