"""Monkey-patch SDK clients so every LLM call is observed and traced."""
from __future__ import annotations

import time
from typing import Any

from sploink import trace
from sploink.classify import classify_step
from sploink.pricing import ANTHROPIC, GROQ, OLLAMA, TOGETHER, cost_usd

_WRAPPED = False


def wrap() -> None:
    """Idempotently install observation hooks on installed LLM client SDKs.

    Today: anthropic, groq, together. Tomorrow: openai.
    """
    global _WRAPPED
    if _WRAPPED:
        return
    _wrap_anthropic()
    _wrap_anthropic_async()
    _wrap_groq()
    _wrap_groq_async()
    _wrap_openai()
    _wrap_openai_async()
    _wrap_together()
    _wrap_ollama()
    _wrap_ollama_async()
    _WRAPPED = True


def _wrap_anthropic() -> None:
    try:
        from anthropic.resources.messages import Messages
    except ImportError:
        return

    from sploink import route as route_mod

    original_create = Messages.create

    def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []
        system = kwargs.get("system")

        # Routing first: if redirected, call never reaches Anthropic.
        routed = route_mod.maybe_route_anthropic_call(
            model=model, messages=messages, system=system, kwargs=kwargs,
        )
        if routed is not None:
            response, _step_label = routed
            return response

        # Otherwise: original observation behavior.
        t0 = time.perf_counter()
        response = original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        tokens_in = getattr(response.usage, "input_tokens", None) if hasattr(response, "usage") else None
        tokens_out = getattr(response.usage, "output_tokens", None) if hasattr(response, "usage") else None
        output_structure = _detect_anthropic_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(
            route_mod._anthropic_messages_to_flat(messages, system)
        ) or classify_step(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_structure=output_structure,
        )

        trace.record(
            trace.CallRecord(
                workflow_id=trace.current_workflow_id(),
                step_index=trace.next_step_index(),
                step_label=step_label,  # type: ignore[arg-type]
                is_llm=True,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                output_structure=output_structure,
                latency_ms=latency_ms,
                cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, ANTHROPIC),
                substrate="anthropic",
                hardware_type="frontier_api",
            )
        )
        return response

    Messages.create = wrapped_create  # type: ignore[method-assign]


def _wrap_groq() -> None:
    try:
        from groq.resources.chat.completions import Completions
    except ImportError:
        return

    from sploink import route as route_mod

    original_create = Completions.create

    def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []

        # Routing first: if enabled and the router says redirect, the call
        # never goes to Groq — the routed substrate's response is returned
        # in Groq's shape, and the call is recorded by route.py itself.
        routed = route_mod.maybe_route_groq_call(model=model, messages=messages, kwargs=kwargs)
        if routed is not None:
            response, _step_label = routed
            return response

        # Otherwise: original observation behavior.
        t0 = time.perf_counter()
        response = original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        output_structure = _detect_openai_style_output_structure(response)
        # Prefer the pre-call label inferred from the prompt (or forced via
        # sploink.step("...")) so labels stay consistent with the router.
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_structure=output_structure,
        )

        trace.record(
            trace.CallRecord(
                workflow_id=trace.current_workflow_id(),
                step_index=trace.next_step_index(),
                step_label=step_label,  # type: ignore[arg-type]
                is_llm=True,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                output_structure=output_structure,
                latency_ms=latency_ms,
                cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, GROQ),
                substrate="groq",
                hardware_type="lpu",
            )
        )
        return response

    Completions.create = wrapped_create  # type: ignore[method-assign]


def _wrap_openai() -> None:
    try:
        from openai.resources.chat.completions import Completions
    except ImportError:
        return

    from sploink import route as route_mod

    original_create = Completions.create

    def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []

        routed = route_mod.maybe_route_openai_call(model=model, messages=messages, kwargs=kwargs)
        if routed is not None:
            response, _step_label = routed
            return response

        t0 = time.perf_counter()
        response = original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        output_structure = _detect_openai_style_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_structure=output_structure,
        )

        # OpenAI doesn't have its own pricing table in Sploink yet; record cost=0.
        # When pricing.OPENAI is added, swap to cost_usd(model, ..., OPENAI).
        trace.record(
            trace.CallRecord(
                workflow_id=trace.current_workflow_id(),
                step_index=trace.next_step_index(),
                step_label=step_label,  # type: ignore[arg-type]
                is_llm=True,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                output_structure=output_structure,
                latency_ms=latency_ms,
                cost_usd=0.0,
                substrate="openai",
                hardware_type="frontier_api",
            )
        )
        return response

    Completions.create = wrapped_create  # type: ignore[method-assign]


def _wrap_together() -> None:
    try:
        from together.resources.chat.completions import CompletionsResource
    except ImportError:
        return

    original_create = CompletionsResource.create

    def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        t0 = time.perf_counter()
        response = original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        output_structure = _detect_openai_style_output_structure(response)
        step_label = classify_step(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_structure=output_structure,
        )

        trace.record(
            trace.CallRecord(
                workflow_id=trace.current_workflow_id(),
                step_index=trace.next_step_index(),
                step_label=step_label,
                is_llm=True,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                output_structure=output_structure,
                latency_ms=latency_ms,
                cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, TOGETHER),
                substrate="together",
                hardware_type="gpu",
            )
        )
        return response

    CompletionsResource.create = wrapped_create  # type: ignore[method-assign]


def _wrap_anthropic_async() -> None:
    try:
        from anthropic.resources.messages import AsyncMessages
    except ImportError:
        return
    from sploink import route as route_mod

    original_create = AsyncMessages.create

    async def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []
        system = kwargs.get("system")

        routed = await route_mod.maybe_route_anthropic_call_async(
            model=model, messages=messages, system=system, kwargs=kwargs,
        )
        if routed is not None:
            response, _step_label = routed
            return response

        t0 = time.perf_counter()
        response = await original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        tokens_in = getattr(response.usage, "input_tokens", None) if hasattr(response, "usage") else None
        tokens_out = getattr(response.usage, "output_tokens", None) if hasattr(response, "usage") else None
        output_structure = _detect_anthropic_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(
            route_mod._anthropic_messages_to_flat(messages, system)
        ) or classify_step(tokens_in=tokens_in, tokens_out=tokens_out, output_structure=output_structure)

        trace.record(trace.CallRecord(
            workflow_id=trace.current_workflow_id(),
            step_index=trace.next_step_index(),
            step_label=step_label,  # type: ignore[arg-type]
            is_llm=True, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            output_structure=output_structure, latency_ms=latency_ms,
            cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, ANTHROPIC),
            substrate="anthropic", hardware_type="frontier_api",
        ))
        return response

    AsyncMessages.create = wrapped_create  # type: ignore[method-assign]


def _wrap_groq_async() -> None:
    try:
        from groq.resources.chat.completions import AsyncCompletions
    except ImportError:
        return
    from sploink import route as route_mod

    original_create = AsyncCompletions.create

    async def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []

        routed = await route_mod.maybe_route_groq_call_async(model=model, messages=messages, kwargs=kwargs)
        if routed is not None:
            response, _step_label = routed
            return response

        t0 = time.perf_counter()
        response = await original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        output_structure = _detect_openai_style_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in, tokens_out=tokens_out, output_structure=output_structure,
        )

        trace.record(trace.CallRecord(
            workflow_id=trace.current_workflow_id(),
            step_index=trace.next_step_index(),
            step_label=step_label,  # type: ignore[arg-type]
            is_llm=True, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            output_structure=output_structure, latency_ms=latency_ms,
            cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, GROQ),
            substrate="groq", hardware_type="lpu",
        ))
        return response

    AsyncCompletions.create = wrapped_create  # type: ignore[method-assign]


def _wrap_openai_async() -> None:
    try:
        from openai.resources.chat.completions import AsyncCompletions
    except ImportError:
        return
    from sploink import route as route_mod

    original_create = AsyncCompletions.create

    async def wrapped_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", []) or []

        routed = await route_mod.maybe_route_openai_call_async(model=model, messages=messages, kwargs=kwargs)
        if routed is not None:
            response, _step_label = routed
            return response

        t0 = time.perf_counter()
        response = await original_create(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None) if usage else None
        tokens_out = getattr(usage, "completion_tokens", None) if usage else None
        output_structure = _detect_openai_style_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in, tokens_out=tokens_out, output_structure=output_structure,
        )

        trace.record(trace.CallRecord(
            workflow_id=trace.current_workflow_id(),
            step_index=trace.next_step_index(),
            step_label=step_label,  # type: ignore[arg-type]
            is_llm=True, model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            output_structure=output_structure, latency_ms=latency_ms,
            cost_usd=0.0,  # OpenAI pricing table not yet in pricing.py
            substrate="openai", hardware_type="frontier_api",
        ))
        return response

    AsyncCompletions.create = wrapped_create  # type: ignore[method-assign]


def _wrap_ollama_async() -> None:
    try:
        import ollama
        from ollama import AsyncClient
    except ImportError:
        return

    from sploink import route as route_mod

    original_chat = AsyncClient.chat

    async def wrapped_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages") or []
        t0 = time.perf_counter()
        response = await original_chat(self, *args, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        tokens_in = getattr(response, "prompt_eval_count", None)
        tokens_out = getattr(response, "eval_count", None)
        output_structure = _detect_ollama_output_structure(response)
        # Honor a forced label set by route.step(...) (used when this call is
        # an internal redirect from another substrate). Else fall back to the
        # post-call heuristic.
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in, tokens_out=tokens_out, output_structure=output_structure,
        )

        trace.record(trace.CallRecord(
            workflow_id=trace.current_workflow_id(),
            step_index=trace.next_step_index(),
            step_label=step_label,  # type: ignore[arg-type]
            is_llm=True, model=model,
            tokens_in=tokens_in, tokens_out=tokens_out,
            output_structure=output_structure, latency_ms=latency_ms,
            cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, OLLAMA),
            substrate="ollama", hardware_type="edge",
        ))
        return response

    AsyncClient.chat = wrapped_chat  # type: ignore[method-assign]


def _wrap_ollama() -> None:
    try:
        import ollama
        from ollama import Client
    except ImportError:
        return

    from sploink import route as route_mod

    original_client_chat = Client.chat
    original_module_chat = ollama.chat

    def _record(model: str, messages: list, response: Any, latency_ms: float) -> None:
        tokens_in = getattr(response, "prompt_eval_count", None)
        tokens_out = getattr(response, "eval_count", None)
        output_structure = _detect_ollama_output_structure(response)
        step_label = route_mod.infer_step_label_from_prompt(messages) or classify_step(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_structure=output_structure,
        )
        trace.record(
            trace.CallRecord(
                workflow_id=trace.current_workflow_id(),
                step_index=trace.next_step_index(),
                step_label=step_label,  # type: ignore[arg-type]
                is_llm=True,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                output_structure=output_structure,
                latency_ms=latency_ms,
                cost_usd=cost_usd(model, tokens_in or 0, tokens_out or 0, OLLAMA),
                substrate="ollama",
                hardware_type="edge",
            )
        )

    def wrapped_client_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages") or []
        t0 = time.perf_counter()
        response = original_client_chat(self, *args, **kwargs)
        _record(model, messages, response, (time.perf_counter() - t0) * 1000)
        return response

    def wrapped_module_chat(*args: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages") or []
        t0 = time.perf_counter()
        response = original_module_chat(*args, **kwargs)
        _record(model, messages, response, (time.perf_counter() - t0) * 1000)
        return response

    Client.chat = wrapped_client_chat  # type: ignore[method-assign]
    ollama.chat = wrapped_module_chat  # type: ignore[assignment]


def _detect_ollama_output_structure(response: Any) -> Any:
    msg = getattr(response, "message", None)
    if msg is None:
        return "freeform"
    if getattr(msg, "tool_calls", None):
        return "tool_call"
    return _classify_text_shape(getattr(msg, "content", "") or "")


def _detect_anthropic_output_structure(response: Any) -> Any:
    content = getattr(response, "content", None)
    if not content:
        return "freeform"
    for block in content:
        if getattr(block, "type", None) == "tool_use":
            return "tool_call"
    first_text = next((getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text"), "")
    return _classify_text_shape(first_text)


def _detect_openai_style_output_structure(response: Any) -> Any:
    choices = getattr(response, "choices", None)
    if not choices:
        return "freeform"
    msg = getattr(choices[0], "message", None)
    if msg is None:
        return "freeform"
    if getattr(msg, "tool_calls", None):
        return "tool_call"
    return _classify_text_shape(getattr(msg, "content", "") or "")


def _classify_text_shape(text: str) -> Any:
    stripped = (text or "").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "freeform"
