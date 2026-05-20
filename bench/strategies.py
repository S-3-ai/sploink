"""Routing strategies — three Runners that dispatch agent steps differently.

A Runner is `(step_label, prompt, max_tokens) -> StepResult`. The three
strategies below all satisfy that contract; what differs is *which substrate*
each step lands on.
"""
from __future__ import annotations

import os
import time
from typing import Any

from groq import Groq
from ollama import Client as OllamaClient

from bench.agent import StepResult
from sploink import router
from sploink.pricing import GROQ, OLLAMA, cost_usd


# Lazy singletons to avoid reconnecting per call.
_groq: Groq | None = None
_ollama: OllamaClient | None = None


def _groq_client() -> Groq:
    global _groq
    if _groq is None:
        _groq = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq


def _ollama_client() -> OllamaClient:
    global _ollama
    if _ollama is None:
        _ollama = OllamaClient(host="http://localhost:11434")
    return _ollama


# Models held constant across compute tiers — the experimental design is:
# same model, different hardware. Llama-3.1-8B-Instruct runs on Ollama (edge)
# and on Groq (LPU) as `llama-3.1-8b-instant`. Only the compute architecture
# differs between tiers; the model is identical.
GROQ_MODEL = "llama-3.1-8b-instant"
OLLAMA_MODEL = "llama3.1:8b"


def _call_groq(step_label: str, prompt: str, max_tokens: int, model: str) -> StepResult:
    t0 = time.perf_counter()
    resp = _groq_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return StepResult(
        label=step_label,
        text=text,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd(model, tokens_in, tokens_out, GROQ),
        substrate="groq",
        model=model,
    )


def _call_ollama(step_label: str, prompt: str, max_tokens: int, model: str) -> StepResult:
    t0 = time.perf_counter()
    resp = _ollama_client().chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": max_tokens},
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    text = resp.message.content or ""
    tokens_in = getattr(resp, "prompt_eval_count", 0) or 0
    tokens_out = getattr(resp, "eval_count", 0) or 0
    return StepResult(
        label=step_label,
        text=text,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd(model, tokens_in, tokens_out, OLLAMA),
        substrate="ollama",
        model=model,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1: all_cloud — every step on Groq llama-3.1-8b-instant (LPU)
# ─────────────────────────────────────────────────────────────────────────────
def all_cloud(step_label: str, prompt: str, max_tokens: int) -> StepResult:
    return _call_groq(step_label, prompt, max_tokens, GROQ_MODEL)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2: ollama_only — every step on Ollama llama3.1:8b (local edge)
# Uniform local compute. Default for the graph-topology experiment — keeps the
# substrate constant so graph structure is the only varying variable.
# ─────────────────────────────────────────────────────────────────────────────
def ollama_only(step_label: str, prompt: str, max_tokens: int) -> StepResult:
    return _call_ollama(step_label, prompt, max_tokens, OLLAMA_MODEL)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 3: edge_routed — cheap steps run on Ollama (edge, local hardware);
# the reason step escalates to Groq (LPU, hosted). Same model on both tiers —
# only the compute architecture differs.
# ─────────────────────────────────────────────────────────────────────────────
_EDGE_TABLE: dict[str, tuple[str, str]] = {
    "classify": ("ollama", OLLAMA_MODEL),
    "rerank": ("ollama", OLLAMA_MODEL),
    "extract": ("ollama", OLLAMA_MODEL),
    "verify": ("ollama", OLLAMA_MODEL),
    "reason": ("groq", GROQ_MODEL),
}


def edge_routed(step_label: str, prompt: str, max_tokens: int) -> StepResult:
    substrate, model = _EDGE_TABLE.get(step_label, ("groq", GROQ_MODEL))
    if substrate == "ollama":
        return _call_ollama(step_label, prompt, max_tokens, model)
    return _call_groq(step_label, prompt, max_tokens, model)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 4: router_v0 — uses sploink.router.choose()
# ─────────────────────────────────────────────────────────────────────────────
def router_v0(step_label: str, prompt: str, max_tokens: int) -> StepResult:
    route = router.choose(step_label)
    if route.substrate == "ollama":
        return _call_ollama(step_label, prompt, max_tokens, route.model)
    if route.substrate == "groq":
        return _call_groq(step_label, prompt, max_tokens, route.model)
    raise ValueError(f"router_v0 has no dispatcher for substrate {route.substrate!r}")


STRATEGIES: dict[str, Any] = {
    "all_cloud": all_cloud,
    "ollama_only": ollama_only,
    "edge_routed": edge_routed,
    "router_v0": router_v0,
}
