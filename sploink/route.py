"""Routing bridge — sits between the wrap layer and the router.

When routing is enabled, intercepted LLM calls are:
  1. Labeled pre-call (heuristic, from prompt text)
  2. Looked up in the router (sploink.router.choose)
  3. Either passed through to the original substrate, or redirected
     (to Ollama today) — the response is translated back to the
     original SDK's response shape so customer code is unchanged.

The current bridge handles Groq → Ollama redirection. Anthropic, OpenAI,
and Together can be added with the same pattern.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any

from sploink import router as router_mod
from sploink import trace
from sploink.pricing import OLLAMA, cost_usd


_ROUTING_ENABLED: ContextVar[bool] = ContextVar("_sploink_routing_enabled", default=False)
_FORCED_LABEL: ContextVar[str | None] = ContextVar("_sploink_forced_label", default=None)


def enable_routing() -> None:
    """Turn on per-step routing. Intercepted calls will be redirected per the router rules."""
    _ROUTING_ENABLED.set(True)


def disable_routing() -> None:
    _ROUTING_ENABLED.set(False)


def is_routing_enabled() -> bool:
    return _ROUTING_ENABLED.get()


class step:
    """Context manager to force a specific step label for any LLM calls inside it.

    Usage:
        with sploink.step("classify"):
            client.chat.completions.create(...)   # treated as classify by router
    """

    def __init__(self, label: str):
        self.label = label
        self._token: Any = None

    def __enter__(self) -> "step":
        self._token = _FORCED_LABEL.set(self.label)
        return self

    def __exit__(self, *exc: Any) -> None:
        _FORCED_LABEL.reset(self._token)


def infer_step_label_from_prompt(messages: list[dict] | None) -> str:
    """Cheap pre-call labeler. Looks at message text for telltale patterns.

    This is intentionally crude — it works for prompts shaped like the bench
    agent. Customer prompts will need their own heuristics or explicit labels
    via `sploink.step(...)`.
    """
    forced = _FORCED_LABEL.get()
    if forced is not None:
        return forced

    if not messages:
        return "reason"

    text = " ".join(
        (m.get("content") or "") if isinstance(m, dict) else getattr(m, "content", "") or ""
        for m in messages
    ).lower()

    if "verdict:" in text or ("'yes' or 'no'" in text and "reply" in text):
        return "verify"
    if "rate how relevant" in text or ('json' in text and '0-10' in text):
        return "rerank"
    if "classify" in text and ("one word" in text or "exactly one word" in text):
        return "classify"
    if "list the key facts" in text or "facts (one per line" in text or "no commentary" in text:
        return "extract"
    if "shortest possible answer" in text or text.rstrip().endswith("answer:"):
        return "reason"

    # Length-based fallback.
    if len(text) > 6000:
        return "summarize_long"
    if len(text) < 200:
        return "classify"
    return "reason"


def maybe_route_groq_call(
    *,
    model: str,
    messages: list[dict],
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    """If routing is enabled and the router says redirect, do it.

    Returns (response_object_groq_shaped, step_label) on redirect.
    Returns None to indicate the caller should pass through to Groq.
    On routed-call failure, returns None so the caller falls back to Groq.
    """
    if not _ROUTING_ENABLED.get():
        return None

    step_label = infer_step_label_from_prompt(messages)
    route = router_mod.choose(step_label)

    # If router says keep it on Groq, pass through.
    if route.substrate == "groq":
        return None

    if route.substrate == "ollama":
        try:
            return _call_ollama_as_groq(
                step_label=step_label,
                model=route.model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens"),
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "groq", step_label, str(e))
            return None  # Caller will pass through to Groq.

    return None


def maybe_route_anthropic_call(
    *,
    model: str,
    messages: list[dict],
    system: str | list | None,
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    """Anthropic analog of maybe_route_groq_call.

    Returns (response_object_anthropic_shaped, step_label) on redirect.
    Returns None to indicate the caller should pass through to Anthropic.
    """
    if not _ROUTING_ENABLED.get():
        return None

    # System prompt + messages contribute to step labeling.
    labelable = _anthropic_messages_to_flat(messages, system)
    step_label = infer_step_label_from_prompt(labelable)
    route = router_mod.choose(step_label)

    if route.substrate == "anthropic":
        return None

    if route.substrate == "ollama":
        try:
            return _call_ollama_as_anthropic(
                step_label=step_label,
                model=route.model,
                messages=messages,
                system=system,
                max_tokens=kwargs.get("max_tokens"),
                requested_model=model,
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "anthropic", step_label, str(e))
            return None  # Caller will pass through to Anthropic.

    return None


def maybe_route_openai_call(
    *,
    model: str,
    messages: list[dict],
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    """OpenAI analog. OpenAI response shape ≈ Groq response shape, so reuse the
    Groq-shaped Ollama translator."""
    if not _ROUTING_ENABLED.get():
        return None

    step_label = infer_step_label_from_prompt(messages)
    route = router_mod.choose(step_label)

    if route.substrate == "openai":
        return None

    if route.substrate == "ollama":
        try:
            return _call_ollama_as_groq(  # OpenAI-shaped response works for OpenAI too
                step_label=step_label,
                model=route.model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens"),
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "openai", step_label, str(e))
            return None

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Async variants — same logic as sync, but use ollama.AsyncClient.
# ─────────────────────────────────────────────────────────────────────────────

async def maybe_route_anthropic_call_async(
    *,
    model: str,
    messages: list[dict],
    system: Any,
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    if not _ROUTING_ENABLED.get():
        return None
    labelable = _anthropic_messages_to_flat(messages, system)
    step_label = infer_step_label_from_prompt(labelable)
    route = router_mod.choose(step_label)
    if route.substrate == "anthropic":
        return None
    if route.substrate == "ollama":
        try:
            return await _call_ollama_as_anthropic_async(
                step_label=step_label, model=route.model, messages=messages,
                system=system, max_tokens=kwargs.get("max_tokens"),
                requested_model=model,
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "anthropic", step_label, str(e))
            return None
    return None


async def maybe_route_groq_call_async(
    *,
    model: str,
    messages: list[dict],
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    if not _ROUTING_ENABLED.get():
        return None
    step_label = infer_step_label_from_prompt(messages)
    route = router_mod.choose(step_label)
    if route.substrate == "groq":
        return None
    if route.substrate == "ollama":
        try:
            return await _call_ollama_as_groq_async(
                step_label=step_label, model=route.model, messages=messages,
                max_tokens=kwargs.get("max_tokens"),
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "groq", step_label, str(e))
            return None
    return None


async def maybe_route_openai_call_async(
    *,
    model: str,
    messages: list[dict],
    kwargs: dict[str, Any],
) -> tuple[Any, str] | None:
    if not _ROUTING_ENABLED.get():
        return None
    step_label = infer_step_label_from_prompt(messages)
    route = router_mod.choose(step_label)
    if route.substrate == "openai":
        return None
    if route.substrate == "ollama":
        try:
            return await _call_ollama_as_groq_async(
                step_label=step_label, model=route.model, messages=messages,
                max_tokens=kwargs.get("max_tokens"),
            ), step_label
        except Exception as e:
            _record_fallback("ollama", "openai", step_label, str(e))
            return None
    return None


async def _call_ollama_as_anthropic_async(
    *, step_label: str, model: str, messages: list[dict], system: Any,
    max_tokens: int | None, requested_model: str,
) -> Any:
    from ollama import AsyncClient

    client = AsyncClient(host="http://localhost:11434")
    flat = _anthropic_messages_to_flat(messages, system)
    options: dict[str, Any] = {}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    # The Ollama wrap layer records this call. We force the step_label via
    # `step(...)` so the recorded label matches what the router decided.
    with step(step_label):
        raw = await client.chat(model=model, messages=flat, options=options or None)

    text = (raw.message.content or "") if getattr(raw, "message", None) else ""
    tokens_in = getattr(raw, "prompt_eval_count", 0) or 0
    tokens_out = getattr(raw, "eval_count", 0) or 0
    done_reason = getattr(raw, "done_reason", "stop") or "stop"
    stop_reason = "max_tokens" if done_reason == "length" else "end_turn"

    return SimpleNamespace(
        id=f"sploink-routed-{int(time.time()*1000)}",
        type="message", role="assistant", model=requested_model,
        stop_reason=stop_reason, stop_sequence=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=tokens_in, output_tokens=tokens_out,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ),
        _sploink_routed=True, _sploink_step_label=step_label,
    )


async def _call_ollama_as_groq_async(
    *, step_label: str, model: str, messages: list[dict], max_tokens: int | None,
) -> Any:
    from ollama import AsyncClient

    client = AsyncClient(host="http://localhost:11434")
    options: dict[str, Any] = {}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    with step(step_label):
        raw = await client.chat(model=model, messages=list(messages), options=options or None)

    content = (raw.message.content or "") if getattr(raw, "message", None) else ""
    tokens_in = getattr(raw, "prompt_eval_count", 0) or 0
    tokens_out = getattr(raw, "eval_count", 0) or 0
    finish = getattr(raw, "done_reason", "stop") or "stop"

    return SimpleNamespace(
        id=f"sploink-routed-{int(time.time()*1000)}", model=model,
        object="chat.completion",
        choices=[SimpleNamespace(
            index=0, finish_reason=finish,
            message=SimpleNamespace(role="assistant", content=content, tool_calls=None),
        )],
        usage=SimpleNamespace(
            prompt_tokens=tokens_in, completion_tokens=tokens_out,
            total_tokens=tokens_in + tokens_out,
        ),
        _sploink_routed=True, _sploink_step_label=step_label,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _anthropic_messages_to_flat(messages: list[dict] | None, system: Any) -> list[dict]:
    """Convert Anthropic's (system, messages) into a flat list for the labeler/Ollama."""
    out: list[dict] = []
    if system:
        sys_text = system if isinstance(system, str) else " ".join(
            (b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "") or "")
            for b in (system if isinstance(system, list) else [])
        )
        if sys_text:
            out.append({"role": "system", "content": sys_text})
    for m in messages or []:
        if isinstance(m, dict):
            role = m.get("role", "user")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", "user")
            content = getattr(m, "content", "")
        if isinstance(content, list):
            text = " ".join(
                (c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "") or "")
                for c in content
                if (c.get("type") if isinstance(c, dict) else getattr(c, "type", None)) == "text"
            )
        else:
            text = content
        out.append({"role": role, "content": text or ""})
    return out


def _record_fallback(from_sub: str, to_sub: str, step_label: str, reason: str) -> None:
    """Log a fallback event into the trace so dashboards see it."""
    import sys
    print(
        f"[sploink] fallback: {from_sub} → {to_sub} for step '{step_label}': {reason[:120]}",
        file=sys.stderr,
    )


def _call_ollama_as_anthropic(
    *,
    step_label: str,
    model: str,  # Ollama model
    messages: list[dict],
    system: Any,
    max_tokens: int | None,
    requested_model: str,  # the model the customer originally asked for
) -> Any:
    """Invoke Ollama, return an Anthropic-shaped Message object.

    Anthropic response shape we mimic:
      resp.id
      resp.type            = "message"
      resp.role            = "assistant"
      resp.model           = (original requested model, so customer logging is preserved)
      resp.content         = [SimpleNamespace(type="text", text=...)]
      resp.stop_reason     = "end_turn" | "max_tokens" | ...
      resp.usage           = SimpleNamespace(input_tokens=..., output_tokens=...)
    """
    from ollama import Client as OllamaClient

    client = OllamaClient(host="http://localhost:11434")
    flat = _anthropic_messages_to_flat(messages, system)

    options: dict[str, Any] = {}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    with step(step_label):
        raw = client.chat(model=model, messages=flat, options=options or None)

    text = (raw.message.content or "") if getattr(raw, "message", None) else ""
    tokens_in = getattr(raw, "prompt_eval_count", 0) or 0
    tokens_out = getattr(raw, "eval_count", 0) or 0
    done_reason = getattr(raw, "done_reason", "stop") or "stop"
    stop_reason = "max_tokens" if done_reason == "length" else "end_turn"

    return SimpleNamespace(
        id=f"sploink-routed-{int(time.time()*1000)}",
        type="message",
        role="assistant",
        model=requested_model,
        stop_reason=stop_reason,
        stop_sequence=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        _sploink_routed=True,
        _sploink_step_label=step_label,
    )


def _call_ollama_as_groq(
    *,
    step_label: str,
    model: str,
    messages: list[dict],
    max_tokens: int | None,
) -> Any:
    """Invoke Ollama, return a Groq-shaped response object.

    Groq/OpenAI response shape we mimic:
      resp.choices[0].message.content
      resp.usage.prompt_tokens
      resp.usage.completion_tokens
      resp.choices[0].finish_reason
      resp.model
    """
    from ollama import Client as OllamaClient

    client = OllamaClient(host="http://localhost:11434")
    options: dict[str, Any] = {}
    if max_tokens is not None:
        options["num_predict"] = max_tokens

    # The Ollama wrap layer records this call. We force the step_label via
    # step() so the recorded label matches what the router decided.
    with step(step_label):
        raw = client.chat(model=model, messages=list(messages), options=options or None)

    content = (raw.message.content or "") if getattr(raw, "message", None) else ""
    tokens_in = getattr(raw, "prompt_eval_count", 0) or 0
    tokens_out = getattr(raw, "eval_count", 0) or 0
    finish = getattr(raw, "done_reason", "stop") or "stop"

    return SimpleNamespace(
        id=f"sploink-routed-{int(time.time()*1000)}",
        model=model,
        object="chat.completion",
        choices=[
            SimpleNamespace(
                index=0,
                finish_reason=finish,
                message=SimpleNamespace(role="assistant", content=content, tool_calls=None),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=tokens_in,
            completion_tokens=tokens_out,
            total_tokens=tokens_in + tokens_out,
        ),
        _sploink_routed=True,
        _sploink_step_label=step_label,
    )
