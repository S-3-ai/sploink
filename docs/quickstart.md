# Quickstart

## Install

```bash
# Core install (just the routing/observability layer)
pip install sploink

# With specific substrate SDKs:
pip install "sploink[anthropic]"
pip install "sploink[groq]"
pip install "sploink[ollama]"

# Everything:
pip install "sploink[all]"
```

Sploink core has only one dependency (Pydantic). The substrate SDKs are optional — install only the ones you actually use.

## Mode 1 — observability only

The simplest thing sploink does is observe every LLM call your agent makes and record a structured trace. You don't change any of your agent code — just call `sploink.wrap()` once at startup.

```python
import sploink
from anthropic import Anthropic

sploink.wrap()   # one line — patches every supported SDK

client = Anthropic()
client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=20,
    messages=[{"role": "user", "content": "is this spam?"}],
)
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=300,
    messages=[{"role": "user", "content": "explain why in detail"}],
)

sploink.trace.print_summary()
```

You get:

```
workflow 9f2c... | 2 calls | $0.0034 | 2400 ms
  tokens: in=80 out=420
  by step:
    classify   1x  $0.0001   200ms
    reason     1x  $0.0033  2200ms
  by hardware:
    frontier_api   2x  $0.0034
```

Every call is also persisted to `~/.sploink/traces/<workflow_id>.jsonl`. You can render the trace as HTML later:

```bash
python -m sploink.report                  # latest trace
python -m sploink.canvas                  # force-directed view
```

## Mode 2 — routing

Once you've observed your traces and confirmed step types look right, flip on routing to redirect cheap steps to a cheaper substrate:

```python
import sploink

sploink.wrap()
sploink.enable_routing()
```

The default v0 rules ([source](https://github.com/S-3-ai/sploink/blob/main/sploink/router.py)) send classify / rerank / extract / verify to Ollama (free, local) and reasoning steps to Groq (LPU, low-latency). Override the rules for your workflow as needed.

If sploink's prompt-content heuristic can't tell what kind of step a call is, mark it explicitly:

```python
with sploink.step("classify"):
    client.chat.completions.create(...)
```

## Mode 3 — visualize the routing

```bash
python -m sploink.architecture
```

Opens a self-contained HTML showing the workflow ↔ substrate bipartite assignment for the current routing strategy. Use the dropdown to compare strategies.

## Run the bench

If you want to verify the routing thesis on a real benchmark (HotpotQA, multi-hop QA), install the bench extras and run:

```bash
pip install "sploink[bench]"
ollama pull llama3.1:8b
python -m bench.run --n 30 --graphs parallel_dag --strategy edge_routed
```

See [Bench](bench.md) for methodology and current findings.

## Concurrent workflows

Sploink's trace is scoped per-asyncio-task (via `contextvars.ContextVar`) and per-thread. Running many requests concurrently produces correctly-isolated traces with no extra effort:

```python
import asyncio, sploink
sploink.wrap()

async def one_request(question):
    # ... LLM calls here ...
    return sploink.trace.summary()

results = await asyncio.gather(*[one_request(q) for q in questions])
```

Each task gets its own `workflow_id`. The traces don't interleave.

## Common issues

- **`sploink.wrap()` doesn't patch a substrate I'm using.** Make sure the SDK is installed (`pip install sploink[groq]` etc.). Sploink silently skips wrappers for SDKs it can't import — by design, so it doesn't crash on missing optional deps.
- **No traces showing up.** Check `~/.sploink/traces/` — files appear there as calls happen.
- **Routed call fails.** If the routed substrate (e.g. Ollama) is down, sploink currently lets the exception propagate. Graceful fallback to the original substrate is on the roadmap.
