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

---

## Configuration — explicit inputs

Everything described above has sensible defaults; you can also configure each layer explicitly at runtime. **Sploink is configured in Python, not in a config file or UI** (a UI lives in the future hosted product, not the open-source SDK).

### Wire sploink in (always)

```python
import sploink

sploink.wrap()              # idempotent — patches every supported SDK at import time
sploink.enable_routing()    # opt into Layer-1 routing; without this it's observe-only
sploink.disable_routing()   # turn routing back off (observations still recorded)
sploink.is_routing_enabled()
```

### Scope a workflow

```python
with sploink.workflow() as wf:
    # ... any number of LLM calls ...
    pass

records = wf.records()              # list[CallRecord]
graph   = wf.graph(method="overlap")  # sploink.Graph inferred from trace
summary = wf.summary()              # cost / latency / per-step aggregates
```

Pin a specific `workflow_id` (e.g. for FastAPI request-scoping):

```python
sploink.trace.set_workflow_id(request.headers["X-Request-Id"])
# ... calls inside this context now belong to that workflow_id
```

### Force a step label when the heuristic misclassifies

```python
with sploink.step("classify"):
    client.chat.completions.create(...)   # forced label, regardless of prompt content
```

### Customize the routing table (Layer 1)

The defaults are in `sploink.router.DEFAULT_RULES`. Mutate them, or pass a custom rules dict per call.

```python
from sploink.router import Route, DEFAULT_RULES

# Mutate the global table — affects every subsequent call
DEFAULT_RULES["classify"] = Route(substrate="ollama", model="qwen2.5:7b")
DEFAULT_RULES["reason"]   = Route(substrate="groq",   model="llama-3.3-70b-versatile")

# Or use a custom dict for one specific lookup, without touching globals
my_rules = {
    "classify": Route("ollama", "llama3.1:8b"),
    "reason":   Route("groq",   "llama-3.1-8b-instant"),
}
route = sploink.router.choose("classify", rules=my_rules)
```

Any step label not present in your rules dict falls through to `sploink.router.FALLBACK`.

### Customize substrate instances (Layer 2 — bench-side today)

The `SUBSTRATE_INSTANCES` catalog in `bench/strategies.py` maps each `hardware_type` to a list of provider instances. Today this is edited in source code; a runtime API is planned.

```python
# bench/strategies.py — edit this dict to add providers
SUBSTRATE_INSTANCES = {
    "cpu": [
        SubstrateInstance(provider="ollama", model="llama3.1:8b"),
        # add a second CPU provider here when you want fallback:
        # SubstrateInstance(provider="salad", model="llama3.1:8b"),
    ],
    "lpu": [
        SubstrateInstance(provider="groq", model="llama-3.1-8b-instant"),
    ],
}
```

`select_substrate(hardware_type)` currently picks the first instance. Future selection logic (availability-aware, cost-aware, region-aware) will live behind that same function.

### Trace storage location

Traces persist to `~/.sploink/traces/<workflow_id>.jsonl` by default. Override via env var:

```bash
export SPLOINK_TRACE_DIR=/path/to/my/traces
# or to suppress persistence in CI/tests:
export SPLOINK_TRACE_DIR=/dev/null
```

### Build a Graph by hand

Useful when you're authoring an experimental workflow or want to inspect topology before running:

```python
from sploink.graph import Graph, Node

g = Graph(
    nodes=(
        Node(id="classify", step="classify", max_tokens=8,  build_prompt=lambda ex, st: ...),
        Node(id="rerank",   step="rerank",   max_tokens=400, build_prompt=lambda ex, st: ...),
        # ...
    ),
    edges=(("classify", "rerank"), ...),
    answer_node="rerank",
)
print(g.topological_layers())   # the parallelism structure of your DAG
```

`Graph.from_trace(records, method="overlap")` produces the inverse — observed calls → inferred Graph — for analysis (the inferred Graph can be visualized but isn't re-executable; the original `build_prompt` closures aren't recoverable from the trace).

### The one rule of thumb

> If you can write it as Python, sploink can be configured with it. There's no separate config file, no YAML, no UI. The configuration surface is `sploink.*` and `sploink.router.*`.

A hosted dashboard for routing-rule editing, multi-tenant policy management, and managed substrate catalogs lives in the (private) `sploink-cloud` repo and isn't built yet — that's the future product surface, not v0.1.
