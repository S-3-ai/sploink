"""Routing strategies — two-layer architecture.

Sploink routes each step in two layers:

  Layer 1: hardware-type policy.   workflow_step → hardware_type
           "classify is cheap → CPU." "reason needs low latency → LPU."
           This is sploink's strategic decision.

  Layer 2: substrate selection.    hardware_type → specific substrate instance
           "Need a CPU? Use Ollama (local) if available."
           "Need an LPU? Groq."
           This is an operational decision and may eventually depend on
           availability, cost, region, rate-limit headroom, etc.

The two layers compose: a strategy picks the policy, the selector resolves
to a specific provider+model. Adding a new substrate instance (e.g. Salad
for CPU) is a one-line config change in SUBSTRATE_INSTANCES; the policy
doesn't have to know.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError
from ollama import Client as OllamaClient

from bench.agent import StepResult
from sploink import router
from sploink.pricing import GROQ, OLLAMA, cost_usd


# Retry wrapper for Groq calls — handles free-tier rate limiting cleanly so
# bench runs don't silently drop examples. Honors Retry-After header when
# present, otherwise exponential backoff.
def _retry_groq(fn, *args, max_attempts: int = 6, **kwargs):
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except (RateLimitError, APIConnectionError, APITimeoutError) as e:
            if attempt == max_attempts - 1:
                raise
            wait = 2 ** attempt
            # Try to honor Retry-After if the server told us how long to wait.
            resp = getattr(e, "response", None)
            if resp is not None:
                ra = resp.headers.get("retry-after") if hasattr(resp, "headers") else None
                try:
                    if ra:
                        wait = max(wait, float(ra))
                except (TypeError, ValueError):
                    pass
            time.sleep(min(wait, 30))  # cap at 30s/attempt
    raise RuntimeError("retry loop exhausted unexpectedly")


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


# Same model on both hardware types — isolates hardware architecture as the
# only varying variable across the LPU/CPU comparison.
GROQ_MODEL = "llama-3.1-8b-instant"   # LPU instance of Llama 3.1 8B
OLLAMA_MODEL = "llama3.1:8b"          # CPU/GPU instance of Llama 3.1 8B


def _call_groq(step_label: str, prompt: str, max_tokens: int, model: str) -> StepResult:
    def _do_call():
        return _groq_client().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    t0 = time.perf_counter()
    resp = _retry_groq(_do_call)
    latency_ms = (time.perf_counter() - t0) * 1000
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return StepResult(
        label=step_label, text=text, latency_ms=latency_ms,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost_usd(model, tokens_in, tokens_out, GROQ),
        substrate="groq", model=model, hardware_type="lpu",
    )


def _call_ollama(step_label: str, prompt: str, max_tokens: int, model: str) -> StepResult:
    t0 = time.perf_counter()
    resp = _ollama_client().chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": max_tokens, "temperature": 0},
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    text = resp.message.content or ""
    tokens_in = getattr(resp, "prompt_eval_count", 0) or 0
    tokens_out = getattr(resp, "eval_count", 0) or 0
    return StepResult(
        label=step_label, text=text, latency_ms=latency_ms,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost_usd(model, tokens_in, tokens_out, OLLAMA),
        substrate="ollama", model=model, hardware_type="cpu",
    )


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 1: hardware-type policy — workflow_step → hardware_type
# ═════════════════════════════════════════════════════════════════════════════

CPU_POLICY: dict[str, str] = {
    "classify": "cpu", "rerank": "cpu", "extract": "cpu",
    "reason": "cpu",   "verify": "cpu",
}

LPU_POLICY: dict[str, str] = {
    "classify": "lpu", "rerank": "lpu", "extract": "lpu",
    "reason": "lpu",   "verify": "lpu",
}

# The sploink thesis: cheap steps on CPU, reasoning on LPU.
HW_ROUTED_POLICY: dict[str, str] = {
    "classify": "cpu",  # short input, short output — CPU sufficient
    "rerank":   "cpu",  # JSON scoring of paragraphs — CPU sufficient
    "extract":  "cpu",  # fact extraction from paragraphs — CPU sufficient
    "verify":   "cpu",  # yes/no answer-grounding check — CPU sufficient
    "reason":   "lpu",  # final synthesis — LPU's low-latency wins here
}

# Fallback hardware_type when a step_label isn't in the policy.
FALLBACK_HW_TYPE = "lpu"


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 2: substrate selection — hardware_type → specific substrate instance
# ═════════════════════════════════════════════════════════════════════════════

# Each hardware_type has an ordered list of substrate instances. The selector
# picks the first available. Today: just one instance per type. Future: filter
# by region, availability, current cost, rate-limit headroom, etc.

class SubstrateInstance(dict):
    """Just a typed dict for clarity. Keys: provider, model, [endpoint, ...]."""


SUBSTRATE_INSTANCES: dict[str, list[SubstrateInstance]] = {
    "cpu": [
        SubstrateInstance(provider="ollama", model=OLLAMA_MODEL),
        # future: SubstrateInstance(provider="salad", model="llama3.1:8b", ...)
    ],
    "lpu": [
        SubstrateInstance(provider="groq", model=GROQ_MODEL),
        # future: SubstrateInstance(provider="cerebras", model="llama-3.1-8b")
    ],
    "gpu": [
        # future: SubstrateInstance(provider="together", model="...")
    ],
    "frontier_api": [
        # future: SubstrateInstance(provider="anthropic", model="claude-sonnet-4-6")
    ],
}


def select_substrate(hardware_type: str) -> SubstrateInstance:
    """Layer 2 selector. Picks a substrate instance for the requested type.

    Today: first in the list. Tomorrow: filter on availability, pick by cost
    or latency. The choice algorithm is the selector's job; the policy doesn't
    know which instance gets picked.
    """
    candidates = SUBSTRATE_INSTANCES.get(hardware_type, [])
    if not candidates:
        raise ValueError(f"no substrate instance available for hardware_type {hardware_type!r}")
    return candidates[0]


# ═════════════════════════════════════════════════════════════════════════════
# Dispatch — translate a selected substrate into a concrete API call
# ═════════════════════════════════════════════════════════════════════════════

def _dispatch(substrate: SubstrateInstance, step_label: str, prompt: str, max_tokens: int) -> StepResult:
    provider = substrate["provider"]
    model = substrate["model"]
    if provider == "ollama":
        return _call_ollama(step_label, prompt, max_tokens, model)
    if provider == "groq":
        return _call_groq(step_label, prompt, max_tokens, model)
    raise ValueError(f"no dispatcher for provider {provider!r}")


# ═════════════════════════════════════════════════════════════════════════════
# Strategies — each one wires a hardware-type policy into the two-layer dispatch
# ═════════════════════════════════════════════════════════════════════════════

def _strategy_from_policy(policy: dict[str, str]) -> Callable[[str, str, int], StepResult]:
    """Build a Runner from a hardware-type policy table."""
    def runner(step_label: str, prompt: str, max_tokens: int) -> StepResult:
        hw_type = policy.get(step_label, FALLBACK_HW_TYPE)
        substrate = select_substrate(hw_type)
        return _dispatch(substrate, step_label, prompt, max_tokens)
    return runner


cpu_only   = _strategy_from_policy(CPU_POLICY)
lpu_only   = _strategy_from_policy(LPU_POLICY)
hw_routed  = _strategy_from_policy(HW_ROUTED_POLICY)


# Legacy SDK-router strategy — bypasses the two-layer model; uses sploink.router.
def router_v0(step_label: str, prompt: str, max_tokens: int) -> StepResult:
    route = router.choose(step_label)
    if route.substrate == "ollama":
        return _call_ollama(step_label, prompt, max_tokens, route.model)
    if route.substrate == "groq":
        return _call_groq(step_label, prompt, max_tokens, route.model)
    raise ValueError(f"router_v0 has no dispatcher for substrate {route.substrate!r}")


STRATEGIES: dict[str, Any] = {
    "cpu_only":  cpu_only,
    "lpu_only":  lpu_only,
    "hw_routed": hw_routed,
    "router_v0": router_v0,
}


# Policy tables exposed for the architecture viz so it can render Layer 1
# (workflow → hardware_type) bipartite edges directly from the source of truth.
HW_POLICIES: dict[str, dict[str, str]] = {
    "cpu_only":  CPU_POLICY,
    "lpu_only":  LPU_POLICY,
    "hw_routed": HW_ROUTED_POLICY,
}
