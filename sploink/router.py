"""Router v0 — static rule table mapping step label → (substrate, model).

This is intentionally not optimization-driven yet. The bench measures whether
the static rules below produce a real cost reduction at parity quality.
Once the bench has telemetry, the table is the training signal for v1.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    substrate: str  # 'ollama' | 'groq' | 'together' | 'anthropic'
    model: str


# Default v0 rules. Edge for everything bounded; cloud-large for synthesis.
DEFAULT_RULES: dict[str, Route] = {
    "classify": Route("ollama", "qwen2.5:7b"),
    "rerank": Route("ollama", "qwen2.5:7b"),
    "extract": Route("ollama", "qwen2.5:7b"),
    "verify": Route("ollama", "qwen2.5:7b"),
    "reason": Route("groq", "llama-3.3-70b-versatile"),
    "summarize_short": Route("ollama", "qwen2.5:7b"),
    "summarize_long": Route("groq", "llama-3.3-70b-versatile"),
    "code_gen": Route("groq", "llama-3.3-70b-versatile"),
    "tool_call_decision": Route("ollama", "qwen2.5:7b"),
}

# Fallback when a step label is missing from the table.
FALLBACK = Route("groq", "llama-3.3-70b-versatile")


def choose(step_label: str, rules: dict[str, Route] | None = None) -> Route:
    table = rules if rules is not None else DEFAULT_RULES
    return table.get(step_label, FALLBACK)
