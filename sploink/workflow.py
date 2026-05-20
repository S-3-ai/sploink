"""Workflow-shape detection from a step-label sequence.

Given the ordered list of step labels produced by classify.py (or the
pre-call labeler in route.py), guess which canonical workflow shape this
run matches. Used downstream to pick a workflow-specific routing table
instead of falling back to per-step rules.

This is retrospective by design — it looks at a completed trace. For
live routing on the *first* invocation, the customer should declare the
workflow explicitly via `sploink.wrap(agent, workflow="rag")`.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Literal


WorkflowType = Literal["rag", "extraction", "tool_agent", "coding", "qa", "unknown"]


def detect(step_labels: Iterable[str]) -> WorkflowType:
    labels = [str(s) for s in step_labels]
    if not labels:
        return "unknown"

    counts = Counter(labels)
    seq = " ".join(labels)

    # RAG signature: rerank present, then extract, then reason, optionally verify.
    if counts.get("rerank", 0) >= 1 and counts.get("extract", 0) >= 1 and counts.get("reason", 0) >= 1:
        return "rag"

    # Extraction signature: dominated by extract / classify, no reasoning step.
    if counts.get("extract", 0) >= 2 and counts.get("reason", 0) == 0:
        return "extraction"

    # Tool-using agent: tool calls dominate.
    if counts.get("tool_call_decision", 0) >= 1 or counts.get("tool_execute", 0) >= 1:
        return "tool_agent"

    # Coding workflow: code_gen present, possibly code_execute.
    if counts.get("code_gen", 0) >= 1:
        return "coding"

    # Plain QA: single reason call.
    if counts.get("reason", 0) >= 1 and len(labels) <= 2:
        return "qa"

    return "unknown"


def detect_from_trace(records: Iterable) -> WorkflowType:
    """Convenience overload — take CallRecord objects, pull step_label."""
    return detect(r.step_label for r in records)
