"""Pricing tables for substrates. $/M tokens. Snapshot — update as needed."""
from __future__ import annotations

# Anthropic public pricing. $ per 1M tokens (input, output). Cache pricing ignored for piece 1.
ANTHROPIC: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-3-5-haiku-latest": (0.80, 4.00),
    "claude-3-opus-latest": (15.00, 75.00),
}

# Groq published pricing for open-weight models on LPU. $ per 1M tokens (input, output).
GROQ: dict[str, tuple[float, float]] = {
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-70b-versatile": (0.59, 0.79),
    "mixtral-8x7b-32768": (0.24, 0.24),
    "gemma2-9b-it": (0.20, 0.20),
}

# Together AI published pricing for open-weight models on NVIDIA GPU. $ per 1M tokens.
# Turbo variants are FP8-quantized; Reference variants are full precision.
TOGETHER: dict[str, tuple[float, float]] = {
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": (0.18, 0.18),
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Reference": (0.20, 0.20),
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": (0.88, 0.88),
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Reference": (0.90, 0.90),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88, 0.88),
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": (3.50, 3.50),
    "mistralai/Mixtral-8x7B-Instruct-v0.1": (0.60, 0.60),
    "Qwen/Qwen2.5-72B-Instruct-Turbo": (1.20, 1.20),
}


# Ollama runs locally on the user's machine — no marginal $ cost per token.
# We still track tokens for latency / throughput comparison.
OLLAMA: dict[str, tuple[float, float]] = {
    "qwen2.5:7b": (0.0, 0.0),
    "qwen2.5:3b": (0.0, 0.0),
    "qwen2.5:14b": (0.0, 0.0),
    "llama3.2:3b": (0.0, 0.0),
    "llama3.1:8b": (0.0, 0.0),
    "phi4": (0.0, 0.0),
}


def cost_usd(model: str, tokens_in: int, tokens_out: int, table: dict[str, tuple[float, float]]) -> float:
    """Compute USD cost from a model name + token counts against a pricing table.

    Falls back to a (model-prefix) match if the exact key is unknown.
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
