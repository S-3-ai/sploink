# sploink

**Heterogeneous compute routing for AI agent workflows.**

Sploink intercepts LLM calls inside your agent code, classifies each call by step type
(classify, rerank, extract, reason, verify, ...), and routes each call to the most
appropriate compute substrate — edge (Ollama), LPU (Groq), GPU (Together), or
frontier API (Anthropic/OpenAI). Same agent code, different per-step compute placement.

> **Status:** Pre-MVP. The interception/observability layer works for Anthropic, Groq,
> OpenAI, Together, and Ollama. The router currently uses a static rule table; learned
> routing is on the roadmap. See [`PRD.md`](./PRD.md) for the full thesis.

---

## Why

A multi-step agent workflow (e.g. RAG, multi-hop QA, document analysis) has 5–20
distinct LLM calls per request. Each step has a different compute profile: a
50-token classification doesn't need a frontier model — but the final reasoning
step might. Today, most agents route every call to a single closed-API model and
overpay 3–10× on the cheap steps.

Sploink fixes that by routing **per step** based on the step's actual demands.

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

## Quickstart — observability mode

The simplest thing sploink does is observe every LLM call your agent makes and
record a structured trace.

```python
import sploink
from anthropic import Anthropic

sploink.wrap()   # one line — patches every supported SDK

client = Anthropic()
# ... your existing agent code, unchanged ...
client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=20,
    messages=[{"role": "user", "content": "is this spam? 'You won!'"}],
)
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=300,
    messages=[{"role": "user", "content": "explain why in detail"}],
)

sploink.trace.print_summary()
```

Output:

```
workflow 9f2c... | 2 calls | $0.0034 | 2400 ms
  tokens: in=80 out=420
  by step:
    classify   1x  $0.0001   200ms
    reason     1x  $0.0033  2200ms
  by hardware:
    frontier_api   2x  $0.0034
```

Every call is also persisted to `~/.sploink/traces/<workflow_id>.jsonl` for offline
analysis with `python -m sploink.report` or `python -m sploink.canvas`.

## Quickstart — routing mode

Once you've observed your traces and confirmed step types look right, flip on
routing to redirect cheap steps to local Ollama (or any substrate you configure):

```python
import sploink

sploink.wrap()
sploink.enable_routing()
```

The default v0 rules (in [`sploink/router.py`](./sploink/router.py)) route
classify/rerank/extract/verify to Ollama and reasoning/synthesis steps to Groq
(LPU). Override the table for your workflow.

For cases where the heuristic prompt-content labeler can't tell what kind of
step a call is, mark it explicitly:

```python
with sploink.step("classify"):
    client.chat.completions.create(...)
```

## What's in the box

| Module | What it does |
|---|---|
| `sploink.wrap()` | Monkey-patches Anthropic, Groq, OpenAI, Together, Ollama SDK clients |
| `sploink.trace` | Per-workflow `CallRecord`s, JSONL persistence, summary aggregations |
| `sploink.classify` | Heuristic step-type labeler from observed call shape (no LLM) |
| `sploink.router` | Static rule table mapping `step_label → (substrate, model)` |
| `sploink.route.step` | Context manager for explicit step labels |
| `sploink.workflow` | Detects RAG / extraction / tool-agent / coding shapes from a trace |
| `sploink.graph` | DAG data structure for execution graphs |
| `sploink.architecture` | Visualizes the workflow ↔ substrate bipartite assignment |
| `sploink.report` | Static HTML report from a JSONL trace |
| `sploink.canvas` | Force-directed graph visualization of a trace |

## Architecture viewer

```bash
python -m sploink.architecture
```

Opens a self-contained HTML showing your workflow IR (left), available substrates
(right), and the bipartite routing assignment (blue edges in the middle). Switch
strategies in the dropdown to see how each one redirects the workload.

## What works, what doesn't

| | Status |
|---|---|
| Observability via `sploink.wrap()` | ✅ Works |
| Per-step classification (heuristic) | ✅ Works |
| Static routing table | ✅ Works |
| Concurrent-workflow isolation (asyncio, threading) | ✅ Works |
| Trace persistence + visualization | ✅ Works |
| Learned routing from telemetry | ❌ Roadmap |
| Substrate graph as first-class data | ❌ Roadmap |
| `Graph.from_trace()` (infer topology from observation) | ❌ Roadmap |
| Hot-swap routing on customer-supplied DAGs (LangGraph, DSPy) | ❌ Roadmap |
| Confidential-compute / privacy primitives | ❌ Roadmap |

## Bench

We validated the routing thesis on **HotpotQA** (multi-hop QA). 4-step workflow,
same model (Llama 3.1 8B) on both substrates, varying only the routing strategy.
30 examples per run, all completed cleanly.

| Strategy | Cost / query | F1 | Latency |
|---|---|---|---|
| `cpu_only` (all on Ollama CPU) | $0 | 0.594 | 13.2s |
| `lpu_only` (all on Groq LPU) | $0.000115 | **0.721** | 20.5s |
| `hw_routed` (cheap → CPU, reason → LPU) | **$0.000009** | 0.589 | 10.5s |

**Headline (`hw_routed` vs `lpu_only`)**: **92.5% cost reduction**, with an F1
trade-off of -0.132 under the current routing policy. The cost half of the
thesis is strongly supported; the "preserved quality" half is a tunable
trade-off (more on this in [docs/bench.md](./docs/bench.md)).

To reproduce:

```bash
pip install "sploink[bench]"
ollama pull llama3.1:8b
python -m bench.run --n 30 --graphs parallel_dag --strategy hw_routed
python -m bench.compare bench/results/v2_*.csv
python -m sploink.dashboard   # opens an interactive results dashboard
```

## Documentation

Full docs: **https://s-3-ai.github.io/sploink** (coming soon)

In the repo:
- [`PRD.md`](./PRD.md) — Product requirements / thesis
- [`docs/`](./docs/) — Concept guides
- [`examples/`](./examples/) — Runnable demos (mocked + real-API)

## Contributing

This is pre-MVP solo work right now. Issues and discussion welcome at the
[GitHub repo](https://github.com/S-3-ai/sploink/issues). Pull requests likewise,
though the API surface is still evolving.

## License

[MIT](./LICENSE)
