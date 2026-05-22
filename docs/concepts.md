# Concepts

The mental model in four pieces.

## 1. The workflow graph

A **workflow** is the logical agent — a set of steps with data dependencies. Each step is one LLM call. Edges represent "step B's input comes from step A's output."

A typical RAG agent:

```
classify ──► rerank ──► extract ──► reason ──► verify
```

Some workflows have parallelism. If two steps don't depend on each other, they can run concurrently:

```
classify ──┐
           ├──► extract ──► reason ──► verify
rerank   ──┘
```

Sploink doesn't author workflows. It consumes them — either explicit ones from a framework like LangGraph / DSPy, or implicit ones inferred from observed LLM calls.

## 2. The substrate graph

A **substrate** is a compute pool sploink can route to. Each has a different cost/latency profile and supports different models:

| Substrate type | Examples | Cost | Latency |
|---|---|---|---|
| Edge | Ollama on your laptop | $0 (electricity) | 5–15s/call |
| LPU | Groq | low | ~200ms/call |
| GPU | Together, Modal | medium | ~500ms/call |
| Frontier | Anthropic, OpenAI | high | ~1–3s/call |

The **substrate graph** is the set of substrates available in a given deployment. A single-laptop developer has 1–2 substrates; an enterprise customer might have all four.

## 3. The router

The **router** decides, for each workflow node, which substrate it should run on. Today this is a static rule table:

```python
# sploink/router.py
DEFAULT_RULES = {
    "classify": ("ollama", "qwen2.5:7b"),
    "rerank":   ("ollama", "qwen2.5:7b"),
    "extract":  ("ollama", "qwen2.5:7b"),
    "verify":   ("ollama", "qwen2.5:7b"),
    "reason":   ("groq",   "llama-3.3-70b-versatile"),
    # ...
}
```

The output of routing is an **execution plan** — the workflow with every node assigned to a specific substrate. This is the actual runnable artifact.

Future versions of the router will learn from observed telemetry (which routes preserved quality, which didn't) instead of using a static table.

## 4. The trace

Every LLM call produces a `CallRecord`:

```python
class CallRecord(BaseModel):
    call_id: str
    workflow_id: str
    step_index: int
    step_label: str          # 'classify', 'rerank', 'extract', ...
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    substrate: str           # 'ollama' / 'groq' / ...
    hardware_type: str       # 'edge' / 'lpu' / 'gpu' / 'frontier_api'
```

Records are scoped to the current workflow (via `contextvars.ContextVar`, so async tasks don't interleave), kept in memory for fast queries, and persisted to JSONL on disk for offline analysis.

## How they compose

```
Workflow IR (logical agent)         Substrate graph (available compute)
        │                                       │
        └───────────┬───────────────────────────┘
                    ▼
                Router
                    │
                    ▼
            Execution plan (workflow with per-node substrate assignment)
                    │
                    ▼
                Executor
                    │
                    ▼
            Trace (CallRecords per workflow)
```

The router is the only place sploink makes a decision. Everything else is plumbing.

## Visualizing the assignment

The bipartite mapping between workflow and substrate is sploink's central abstraction. The [architecture viewer](https://github.com/S-3-ai/sploink/blob/main/sploink/architecture.py) renders it directly:

```bash
python -m sploink.architecture
```

Workflow on the left, substrate on the right, solid blue edges in the middle showing which step is assigned to which substrate. Switch strategies to see how each one redirects the workload.
