"""End-to-end demo of the wrap → router bridge.

Runs the SAME customer-style code twice:
  1. With routing disabled — every step hits Groq.
  2. With routing enabled  — cheap steps redirect to Ollama transparently.

The customer code never imports anything from sploink except the one-line
enable_routing() call. The Groq SDK calls are identical in both runs.

Prereqs:
  - GROQ_API_KEY in .env
  - ollama serve running, qwen2.5:7b pulled
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from groq import Groq

import sploink
from sploink import trace, workflow


# Five canonical RAG-shaped prompts. Each is what an agent harness might
# send to its LLM provider — Sploink doesn't see the workflow, only the calls.
PROMPTS = [
    # classify
    ("Classify this multi-hop question as exactly one word: 'bridge' (requires finding an "
     "intermediate entity) or 'comparison' (compares two entities directly).\n\n"
     "Question: Which film, released in 1994, starred both Tim Robbins and Morgan Freeman?\n\nType:", 8),
    # rerank
    ("Rate how relevant each paragraph is to answering the question, on a 0-10 scale. "
     "Return ONLY a JSON object mapping paragraph index (string) to score (int).\n\n"
     "Question: Which film, released in 1994, starred both Tim Robbins and Morgan Freeman?\n\n"
     "[0] [The Shawshank Redemption] The Shawshank Redemption is a 1994 American drama film starring "
     "Tim Robbins and Morgan Freeman.\n"
     "[1] [Pulp Fiction] Pulp Fiction is a 1994 American crime film by Quentin Tarantino.\n"
     "[2] [Forrest Gump] Forrest Gump is a 1994 American comedy-drama film starring Tom Hanks.\n\n"
     'JSON (e.g. {"0": 7, "1": 2, ...}):', 200),
    # extract
    ("From the paragraphs below, list the key facts that help answer the question. "
     "One short fact per line. No numbering, no commentary.\n\n"
     "Question: Which film, released in 1994, starred both Tim Robbins and Morgan Freeman?\n\n"
     "Paragraphs:\n[The Shawshank Redemption] The Shawshank Redemption is a 1994 American drama "
     "film starring Tim Robbins and Morgan Freeman.\n\nFacts:", 200),
    # reason / synthesize
    ("Answer the question using only the facts. Reply with the shortest possible answer "
     "(a name, date, number, or phrase). No explanation.\n\n"
     "Facts:\nThe Shawshank Redemption was released in 1994.\nIt starred Tim Robbins and "
     "Morgan Freeman.\n\nQuestion: Which film, released in 1994, starred both Tim Robbins "
     "and Morgan Freeman?\nAnswer:", 50),
    # verify
    ("Does the answer follow from the facts? Reply with exactly 'yes' or 'no'.\n\n"
     "Facts:\nThe Shawshank Redemption was released in 1994.\nIt starred Tim Robbins and "
     "Morgan Freeman.\n\nAnswer: The Shawshank Redemption\n\nVerdict:", 6),
]

MODEL = "llama-3.3-70b-versatile"


def run_workflow(client: Groq, label: str) -> None:
    print(f"\n--- {label} ---")
    trace.reset()
    for i, (prompt, max_toks) in enumerate(PROMPTS):
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=max_toks,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip().split("\n")[0]
        routed = getattr(resp, "_sploink_routed", False)
        route_marker = "↳ ROUTED" if routed else "  groq  "
        print(f"  step {i+1}: {route_marker}  {text[:60]!r}")

    s = trace.summary()
    print(f"\n  total: {s['calls']} calls  ${s['totals']['cost_usd']:.6f}  "
          f"{s['totals']['latency_ms']:.0f} ms")
    wf = workflow.detect_from_trace(trace.all_records())
    print(f"  detected workflow shape: {wf}")


def main() -> None:
    load_dotenv()
    if not os.environ.get("GROQ_API_KEY"):
        print("missing GROQ_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    # One-line install. Observation is on by default; routing is opt-in.
    sploink.wrap()
    client = Groq()

    # Pass 1: routing off → every step hits Groq.
    sploink.disable_routing()
    run_workflow(client, "PASS 1: routing OFF (every step → Groq)")

    cost_off = trace.summary()["totals"]["cost_usd"]

    # Pass 2: routing on → cheap steps redirect to Ollama transparently.
    sploink.enable_routing()
    run_workflow(client, "PASS 2: routing ON  (per-step → Ollama / Groq via sploink.router)")
    cost_on = trace.summary()["totals"]["cost_usd"]

    if cost_off > 0:
        delta = 1 - (cost_on / cost_off)
        print(f"\n=== cost reduction with routing: {delta * 100:.1f}% "
              f"(${cost_off:.6f} → ${cost_on:.6f}) ===")


if __name__ == "__main__":
    main()
