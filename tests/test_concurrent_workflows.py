"""Verify two concurrent workflows don't interleave records."""
from __future__ import annotations

import asyncio
import sys

from sploink import trace


async def make_calls(wid: str, n: int) -> dict:
    trace.set_workflow_id(wid)
    # Simulate N calls by writing CallRecords directly.
    for i in range(n):
        await asyncio.sleep(0)  # yield to scheduler so workflows interleave
        trace.record(trace.CallRecord(
            workflow_id=trace.current_workflow_id(),
            step_index=trace.next_step_index(),
            step_label="classify",
            is_llm=True,
            model=f"model-for-{wid}",
            tokens_in=10, tokens_out=2,
            output_structure="freeform",
            latency_ms=1.0,
            cost_usd=0.001,
            substrate="ollama",
            hardware_type="edge",
        ))
    return trace.summary(wid)


async def main() -> int:
    trace.reset_all()
    # Run two workflows concurrently. They should not see each other's calls.
    a_task = asyncio.create_task(make_calls("wf-A", 5))
    b_task = asyncio.create_task(make_calls("wf-B", 3))
    a, b = await asyncio.gather(a_task, b_task)

    ok = True
    if a["calls"] != 5 or a["workflow_id"] != "wf-A":
        print(f"FAIL wf-A: got {a['calls']} calls, wid={a['workflow_id']}", file=sys.stderr)
        ok = False
    if b["calls"] != 3 or b["workflow_id"] != "wf-B":
        print(f"FAIL wf-B: got {b['calls']} calls, wid={b['workflow_id']}", file=sys.stderr)
        ok = False

    # Check step_index didn't bleed across workflows.
    a_records = trace.all_records("wf-A")
    b_records = trace.all_records("wf-B")
    a_idxs = [r.step_index for r in a_records]
    b_idxs = [r.step_index for r in b_records]
    if a_idxs != [0, 1, 2, 3, 4]:
        print(f"FAIL wf-A step indices: {a_idxs}", file=sys.stderr)
        ok = False
    if b_idxs != [0, 1, 2]:
        print(f"FAIL wf-B step indices: {b_idxs}", file=sys.stderr)
        ok = False

    if ok:
        print("OK: concurrent workflows are isolated.")
        print(f"  wf-A: {a['calls']} calls, step indices {a_idxs}")
        print(f"  wf-B: {b['calls']} calls, step indices {b_idxs}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
