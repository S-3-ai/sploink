"""Heuristic step-type classification from observed call shape.

This is the cold-start labeler. Once enough calls have been observed for a
given (workflow, prompt-hash) pair, the router can use learned fingerprints
instead. For piece 1 we only need the heuristic.
"""
from __future__ import annotations

from sploink.trace import OutputStructure, StepLabel


def classify_step(
    *,
    tokens_in: int | None,
    tokens_out: int | None,
    output_structure: OutputStructure,
) -> StepLabel:
    ti = tokens_in or 0
    to = tokens_out or 0

    if output_structure == "tool_call":
        return "tool_call_decision"

    if ti > 50_000:
        return "summarize_long"

    if ti <= 200 and to <= 20:
        return "classify"

    if output_structure == "json" and to <= 500:
        return "extract"

    if ti > 1_000 and to >= 200 and output_structure == "freeform":
        return "summarize_short"

    if to > 500 and output_structure == "freeform":
        return "reason"

    if to <= 50:
        return "verify"

    return "unknown"
