"""Real-API smoke test: same Llama 3.1 8B running on Groq LPU and Together GPU.

This is the thesis demo. Same prompt → same model weights → two hardware types
→ measurably different cost and latency. Run this with real API keys in .env:

    GROQ_API_KEY=gsk_...
    TOGETHER_API_KEY=tgp_...

Then:
    uv run python examples/observe_real.py
    uv run python -m sploink.canvas
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from groq import Groq
from together import Together

import sploink
from sploink import trace


# Same model weights, different runtimes/hardware.
# Groq's "instant" and Together's "Turbo" variants are both quantized for speed.
GROQ_MODEL = "llama-3.1-8b-instant"
TOGETHER_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

# Prompts span step-type shapes so the classifier exercises multiple branches.
PROMPTS: list[tuple[str, int]] = [
    # (prompt, max_tokens)
    ("Reply with only 'spam' or 'ham'. Subject: 'WIN A FREE IPHONE NOW'", 5),
    ("List three popular programming languages. One word each, comma-separated.", 30),
    ("In two short sentences, explain what attention is in a transformer.", 120),
]


def main() -> None:
    load_dotenv()

    if not os.environ.get("GROQ_API_KEY"):
        print("missing GROQ_API_KEY in environment (.env)", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("TOGETHER_API_KEY"):
        print("missing TOGETHER_API_KEY in environment (.env)", file=sys.stderr)
        sys.exit(1)

    trace.reset()
    sploink.wrap()

    groq_client = Groq()
    together_client = Together()

    print(f"running {len(PROMPTS)} prompts × 2 substrates ({GROQ_MODEL} on LPU vs GPU)...\n")

    substrate_errors: dict[str, str] = {}

    for prompt, max_tokens in PROMPTS:
        # LPU (Groq)
        try:
            groq_client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            substrate_errors["groq"] = str(e)[:200]

        # NVIDIA GPU (Together)
        try:
            together_client.chat.completions.create(
                model=TOGETHER_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            substrate_errors["together"] = str(e)[:200]

    if substrate_errors:
        print("=== substrate errors (calls that failed are absent from trace) ===")
        for k, v in substrate_errors.items():
            print(f"  {k}: {v}")
        print()

    print("=== observation summary ===")
    trace.print_summary()

    # side-by-side comparison per prompt pair — only when both substrates succeeded
    records = trace.all_records()
    if len(records) == 2 * len(PROMPTS):
        print("\n=== same-prompt comparison (LPU vs GPU) ===")
        print(f"  {'prompt':<60} {'LPU $':>10} {'GPU $':>10} {'LPU ms':>8} {'GPU ms':>8}")
        for i, (prompt, _) in enumerate(PROMPTS):
            lpu = records[2 * i]
            gpu = records[2 * i + 1]
            label = (prompt[:57] + "...") if len(prompt) > 60 else prompt
            print(f"  {label:<60} ${lpu.cost_usd:>9.6f} ${gpu.cost_usd:>9.6f} {lpu.latency_ms:>8.0f} {gpu.latency_ms:>8.0f}")
    else:
        print(f"\n(only {len(records)} of {2 * len(PROMPTS)} expected calls succeeded — side-by-side comparison skipped)")

    print(f"\nrender:  uv run python -m sploink.canvas\nor:      uv run python -m sploink.report")


if __name__ == "__main__":
    main()
