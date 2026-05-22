"""Pricing tables for substrates. $/M tokens. Snapshot — update as needed.

Trimmed to only the models actually exercised by the bench, SDK demos, and
router defaults. Models without pricing entries get cost_usd=0.0 via the
fallback in cost_usd(), so the file can stay small until we genuinely need
more entries.
"""
from __future__ import annotations

# Anthropic. $ per 1M tokens (input, output).
ANTHROPIC: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
}

# Groq (LPU). $ per 1M tokens.
GROQ: dict[str, tuple[float, float]] = {
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
}

# Together AI. Empty until we actually route to a Together model.
TOGETHER: dict[str, tuple[float, float]] = {}

# Ollama runs locally — no $ cost per token. Tokens still tracked for latency/throughput.
OLLAMA: dict[str, tuple[float, float]] = {
    "llama3.1:8b": (0.0, 0.0),
    "qwen2.5:7b": (0.0, 0.0),
}


def cost_usd(model: str, tokens_in: int, tokens_out: int, table: dict[str, tuple[float, float]]) -> float:
    """Compute USD cost from a model name + token counts against a pricing table.

    Returns 0.0 for unknown models — keeps the SDK from crashing when it observes
    a model we haven't priced yet. Add an entry above when you need accuracy.
    """
    rate = table.get(model)
    if rate is None:
        for key, val in table.items():
            if model.startswith(key) or key.startswith(model):
                rate = val
                break
    if rate is None:
        return 0.0
    in_rate, out_rate = rate
    return (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate
