"""Async fan-out demo: three concurrent Groq calls, each routed independently.

Proves the Tier 1 plumbing works end-to-end:
  - AsyncGroq.chat.completions.create is intercepted
  - Each call's step_label is inferred from the prompt
  - The router decides edge vs cloud per call
  - asyncio.gather runs them concurrently
  - Records don't interleave (each workflow_id is isolated)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from groq import AsyncGroq

import sploink
from sploink import trace


MODEL = "llama-3.3-70b-versatile"

PROMPTS = [
    # classify — routes to ollama
    ("Classify this multi-hop question as exactly one word: 'bridge' or 'comparison'.\n\n"
     "Question: Which film starred Tim Robbins and Morgan Freeman?\nType:", 8),
    # rerank — routes to ollama
    ("Rate how relevant each paragraph is to answering the question, on a 0-10 scale. "
     "Return ONLY a JSON object mapping index to score.\n\n"
     "Question: When was The Shawshank Redemption released?\n\n"
     "[0] Released in 1994.\n[1] Won several Oscars.\n[2] Set in Maine.\n\n"
     'JSON (e.g. {"0": 7, "1": 2}):', 100),
    # reason — stays on groq (synth step)
    ("Answer the question using only the facts. Reply with the shortest possible answer. "
     "No explanation.\n\n"
     "Facts:\nThe Shawshank Redemption was released in 1994.\n\n"
     "Question: When was The Shawshank Redemption released?\nAnswer:", 30),
]


async def one_call(client: AsyncGroq, prompt: str, max_toks: int) -> tuple[str, bool]:
    resp = await client.chat.completions.create(
        model=MODEL,
        max_tokens=max_toks,
        messages=[{"role": "user", "content": prompt}],
    )
    text = (resp.choices[0].message.content or "").strip().split("\n")[0]
    routed = getattr(resp, "_sploink_routed", False)
    return text, routed


async def fan_out_workflow(client: AsyncGroq, workflow_id: str) -> dict:
    trace.set_workflow_id(workflow_id)
    t0 = time.perf_counter()
    # The three steps fire concurrently. Each is independently routed.
    results = await asyncio.gather(*[one_call(client, p, m) for p, m in PROMPTS])
    wall_ms = (time.perf_counter() - t0) * 1000
    summary = trace.summary(workflow_id)
    return {
        "workflow_id": workflow_id,
        "wall_ms": wall_ms,
        "results": results,
        "summary": summary,
    }


async def main() -> None:
    load_dotenv()
    if not os.environ.get("GROQ_API_KEY"):
        print("missing GROQ_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    sploink.wrap()
    sploink.enable_routing()
    client = AsyncGroq()

    # Run TWO workflows concurrently, each with three fan-out steps.
    # Six total calls. Records must stay separated by workflow_id.
    wf1_task = asyncio.create_task(fan_out_workflow(client, "demo-wf-1"))
    wf2_task = asyncio.create_task(fan_out_workflow(client, "demo-wf-2"))
    wf1, wf2 = await asyncio.gather(wf1_task, wf2_task)

    for wf in (wf1, wf2):
        print(f"\n=== workflow {wf['workflow_id']}  ({wf['wall_ms']:.0f}ms wall) ===")
        for i, (text, routed) in enumerate(wf["results"]):
            marker = "↳ ROUTED" if routed else "  groq  "
            print(f"  step {i+1}: {marker}  {text[:60]!r}")
        s = wf["summary"]
        print(f"  records in workflow: {s['calls']}  cost: ${s['totals']['cost_usd']:.6f}")
        print(f"  by hardware: {dict(s['by_hardware'])}")

    # Cross-check: records are properly isolated.
    print(f"\n=== isolation check ===")
    rec_1 = trace.all_records("demo-wf-1")
    rec_2 = trace.all_records("demo-wf-2")
    print(f"  workflow demo-wf-1: {len(rec_1)} records")
    print(f"  workflow demo-wf-2: {len(rec_2)} records")
    if len(rec_1) == 3 and len(rec_2) == 3:
        print(f"  PASS: no interleaving.")
    else:
        print(f"  FAIL: expected 3 each, got {len(rec_1)} and {len(rec_2)}")


if __name__ == "__main__":
    asyncio.run(main())
