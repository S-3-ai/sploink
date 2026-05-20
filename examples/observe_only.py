"""Piece 1 smoke test: wrap() observes a multi-substrate agent.

Uses httpx MockTransport for both Anthropic and Groq so no real API keys are
needed. Demonstrates:
  1. wrap() patches both anthropic + groq SDKs at import time
  2. Each .messages.create() / .chat.completions.create() call is captured
  3. trace.print_summary() shows per-step / per-hardware aggregates
  4. The JSONL is ready to render with `python -m sploink.report` or
     `python -m sploink.canvas`.
"""
from __future__ import annotations

import json

import httpx
from anthropic import Anthropic
from groq import Groq

import sploink
from sploink import trace


# --- mock response factories ----------------------------------------------

def _anthropic_response(input_tokens: int, output_tokens: int, text: str, model: str) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _groq_response(input_tokens: int, output_tokens: int, text: str, model: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


# --- scripted calls -------------------------------------------------------

ANTHROPIC_SCRIPT = [
    # (input_tokens, output_tokens, text, model)
    (80, 3, "spam", "claude-haiku-4-5"),                            # → classify
    (400, 800, "Let me think step by step. " * 60, "claude-sonnet-4-6"),  # → reason
]

GROQ_SCRIPT = [
    (80, 3, "spam", "llama-3.1-8b-instant"),                        # → classify on LPU
    (1200, 220, "Three paragraphs of summary text " * 30, "llama-3.3-70b-versatile"),  # → summarize_short on LPU
    (300, 60, "verified", "llama-3.1-8b-instant"),                  # → verify
]

_anthropic_idx = 0
_groq_idx = 0


def anthropic_mock_handler(request: httpx.Request) -> httpx.Response:
    global _anthropic_idx
    ti, to, text, model = ANTHROPIC_SCRIPT[_anthropic_idx]
    _anthropic_idx += 1
    return httpx.Response(200, json=_anthropic_response(ti, to, text, model))


def groq_mock_handler(request: httpx.Request) -> httpx.Response:
    global _groq_idx
    ti, to, text, model = GROQ_SCRIPT[_groq_idx]
    _groq_idx += 1
    return httpx.Response(200, json=_groq_response(ti, to, text, model))


def main() -> None:
    trace.reset()
    sploink.wrap()

    anthropic_client = Anthropic(
        api_key="not-needed-for-mock",
        http_client=httpx.Client(transport=httpx.MockTransport(anthropic_mock_handler)),
    )
    groq_client = Groq(
        api_key="not-needed-for-mock",
        http_client=httpx.Client(transport=httpx.MockTransport(groq_mock_handler)),
    )

    # Step 0: classify on Anthropic (frontier)
    anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=10,
        messages=[{"role": "user", "content": "is this spam?"}],
    )
    # Step 1: same classify on Groq LPU — direct hardware comparison
    groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=10,
        messages=[{"role": "user", "content": "is this spam?"}],
    )
    # Step 2: summarize_short on Groq LPU
    groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=400,
        messages=[{"role": "user", "content": "summarize this long doc: ..."}],
    )
    # Step 3: reason on Anthropic frontier
    anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "explain attention from first principles"}],
    )
    # Step 4: verify on Groq LPU
    groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=80,
        messages=[{"role": "user", "content": "does the answer mention QKV?"}],
    )

    print("\n=== observation summary ===")
    trace.print_summary()
    print("\n=== raw records ===")
    for r in trace.all_records():
        print(json.dumps(r.model_dump(), indent=2))


if __name__ == "__main__":
    main()
