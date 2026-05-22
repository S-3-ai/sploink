# Examples

Runnable demos in [`examples/`](https://github.com/S-3-ai/sploink/tree/main/examples). Each is self-contained.

## 1. Observe-only (mocked APIs, no keys needed)

[`examples/observe_only.py`](https://github.com/S-3-ai/sploink/blob/main/examples/observe_only.py) — uses `httpx.MockTransport` to fake Anthropic and Groq responses, then runs `sploink.wrap()` over a 5-call sequence and prints the trace.

```bash
python examples/observe_only.py
```

Shows:

- One line of integration (`sploink.wrap()`)
- Trace summary aggregated by step type and by hardware
- The raw JSONL records written to `~/.sploink/traces/`

This is the canonical "hello sploink" — read it first.

## 2. Observe with real APIs

[`examples/observe_real.py`](https://github.com/S-3-ai/sploink/blob/main/examples/observe_real.py) — same as #1 but hits real Anthropic + Groq endpoints (needs API keys in `.env`).

```bash
cp .env.example .env  # add your ANTHROPIC_API_KEY, GROQ_API_KEY
python examples/observe_real.py
```

## 3. Routing demo

[`examples/route_demo.py`](https://github.com/S-3-ai/sploink/blob/main/examples/route_demo.py) — turns on `sploink.enable_routing()` so calls get redirected per the static rule table. Demonstrates that customer code is unchanged but the substrate underneath is different.

## 4. Concurrent workflows (asyncio fan-out)

[`examples/async_fanout_demo.py`](https://github.com/S-3-ai/sploink/blob/main/examples/async_fanout_demo.py) — runs many agent workflows concurrently via `asyncio.gather`. Verifies that each workflow gets its own isolated trace (via `ContextVar`), no interleaving.

## 5. The bench

The bench in [`bench/`](https://github.com/S-3-ai/sploink/tree/main/bench) is itself the most complete example — a real 4-step RAG agent over HotpotQA, with three routing strategies, scoring, and CSV output. To run it:

```bash
pip install "sploink[bench]"
ollama pull llama3.1:8b
python -m bench.run --n 30 --graphs parallel_dag --strategy hw_routed
```

Compare three strategies on the intersection of completed examples:

```bash
python -m bench.compare bench/results/v2_*.csv
```

See [Bench](bench.md) for methodology and current numbers.

## 6. Architecture viewer

[`sploink/architecture.py`](https://github.com/S-3-ai/sploink/blob/main/sploink/architecture.py) — generates a single-file HTML showing the workflow ↔ hardware bipartite assignment for any of the bench's workflows.

```bash
python -m sploink.architecture --workflow parallel_dag
```

Opens in your default browser. Strategy switcher in the header. White theme.

---

## Patterns

A few common usage patterns sploink supports:

### Pattern 1: pure observability (no routing)

Use sploink just to see what your agent is doing. Don't change behavior. Good for diagnostics, cost attribution, and understanding step distribution before deciding what to optimize.

```python
import sploink
from groq import Groq

sploink.wrap()                       # idempotent; safe to call multiple times
# (intentionally NOT calling sploink.enable_routing() — observation only)

client = Groq()                      # needs GROQ_API_KEY in env
client.chat.completions.create(
    model="llama-3.1-8b-instant",
    max_tokens=20,
    messages=[{"role": "user", "content": "is this spam?"}],
)
client.chat.completions.create(
    model="llama-3.1-8b-instant",
    max_tokens=200,
    messages=[{"role": "user", "content": "explain why in 3 bullets"}],
)

sploink.trace.print_summary()
# → workflow ... | 2 calls | $... | ...ms  (with per-step + per-hardware breakdown)
```

Both calls are recorded as `CallRecord`s, classified by step type (heuristic based on token counts + output structure), and persisted to `~/.sploink/traces/`. **The customer code path is unchanged** — the only added line is `sploink.wrap()`.

### Pattern 2: gradual routing rollout

Turn on routing for a subset of step types first. Edit `sploink/router.py:DEFAULT_RULES` or define your own table:

```python
import sploink
from sploink import router

custom_rules = {
    "classify": router.Route("ollama", "qwen2.5:7b"),  # try local
    # other steps absent → fall through to FALLBACK (frontier)
}

sploink.wrap()
sploink.enable_routing()
# router.choose() picks from custom_rules; missing labels use FALLBACK
```

### Pattern 3: explicit step labels

When sploink's prompt-content heuristic can't tell what kind of step a call is, mark it explicitly:

```python
with sploink.step("classify"):
    response = client.chat.completions.create(
        model="claude-haiku-4-5",
        messages=[{"role": "user", "content": "spam or ham?"}],
    )
# Any LLM call inside this block is labeled "classify" regardless of heuristics.
```

### Pattern 4: per-workflow trace isolation

Concurrent workflows automatically get isolated traces because `trace.current_workflow_id()` reads from a `ContextVar`. For FastAPI-style request scoping:

```python
import sploink
from fastapi import FastAPI, Request

app = FastAPI()
sploink.wrap()

@app.post("/agent")
async def run_agent(req: Request):
    sploink.trace.set_workflow_id(req.headers.get("X-Request-Id"))
    # ... agent code ...
    return sploink.trace.summary()
```
