# Architecture

Sploink's central abstraction is the **bipartite mapping** between workflow steps and hardware types. This page explains the two-layer model and how to open the interactive viz.

## The two layers, named

```
WORKFLOW IR (customer)                     HARDWARE TYPES (sploink targets)
                                             ┌───── CPU ───────┐
classify ────────────────────────────────►   │ • Ollama        │
                                             │ ○ Salad         │
rerank ──────────────────────────────────►   │ ○ RunPod        │
                                             └─────────────────┘

extract ─────────────────────────────────►   ┌───── LPU ───────┐
                                             │ • Groq          │
reason ──────────────────────────────────►   │ ○ Cerebras      │
                                             └─────────────────┘

verify ──────────────────────────────────►   ┌──── GPU ────────┐
                                             │ ○ Together      │
                                             │ ○ RunPod        │
                                             └─────────────────┘

                                             ┌─ Frontier API ──┐
                                             │ ○ Anthropic     │
                                             │ ○ OpenAI        │
                                             └─────────────────┘
```

### Layer 1 — Hardware-type policy

The routing **decision**: which kind of hardware is best for this step type?

```python
HW_ROUTED_POLICY: dict[str, str] = {
    "classify": "cpu",
    "rerank":   "cpu",
    "extract":  "cpu",
    "verify":   "cpu",
    "reason":   "lpu",
}
```

This policy is the *strategic* layer. Sploink's job is to learn good policies from observed telemetry — which (step, hardware-type) pairs preserve quality at lower cost.

### Layer 2 — Substrate selection

The substrate **resolution**: given a hardware type, which provider instance serves it right now?

```python
SUBSTRATE_INSTANCES: dict[str, list[dict]] = {
    "cpu": [
        {"provider": "ollama", "model": "llama3.1:8b"},
        # future: {"provider": "salad", "model": "llama3.1:8b"},
    ],
    "lpu": [
        {"provider": "groq", "model": "llama-3.1-8b-instant"},
        # future: {"provider": "cerebras", "model": "llama-3.1-8b"},
    ],
    ...
}

def select_substrate(hardware_type: str) -> dict:
    """First-available today. Tomorrow: filter by availability, pick by cost."""
    return SUBSTRATE_INSTANCES[hardware_type][0]
```

This layer is *operational*. Adding a new provider for an existing hardware type is one line of config. Switching providers based on availability, region, or rate-limit headroom is the selector's job, invisible to the policy.

## Why decouple?

| | Together (today) | Decoupled (now) |
|---|---|---|
| Adding a new provider | Edit every routing rule that uses that hardware type | One line in `SUBSTRATE_INSTANCES` |
| Adding a new hardware type | Edit every strategy that should be aware of it | One line + a dispatcher branch |
| Switching providers by region | Hardcoded per strategy | Selector logic |
| Learned routing trains on... | Provider-specific decisions | Hardware-type decisions (transferable across providers) |

This mirrors how compilers work — instruction selection (which kind of op) is decoupled from instruction scheduling (which physical resource).

## Interactive diagram

Open the bipartite architecture viz in your browser:

```bash
python -m sploink.architecture
```

This generates `sploink_architecture.html` — a single-file SVG diagram with:

- Workflow IR (left) — read live from `bench.graphs.GRAPHS`
- Hardware types (right) — each containing nested substrate instances
- Bipartite edges — Layer 1 (workflow step → hardware type) for the selected strategy
- Active instance dots inside each hardware box — Layer 2 (which provider serves this type)

Strategy switcher in the header shows how Layer 1 changes between `cpu_only` / `lpu_only` / `hw_routed`.

```bash
# Switch the default workflow or strategy shown:
python -m sploink.architecture --workflow parallel_dag --strategy hw_routed
python -m sploink.architecture --workflow linear     --strategy cpu_only
```

## How it relates to the rest of sploink

| Layer | Owned by | Code location |
|---|---|---|
| Workflow IR | Customer (their framework — LangGraph, DSPy, plain Python) | their code, observed via `sploink.wrap()` |
| Workflow Graph data structure | Sploink | [`sploink/graph.py`](https://github.com/S-3-ai/sploink/blob/main/sploink/graph.py) |
| Hardware-type policy (Layer 1) | Sploink (and configurable by customer) | [`bench/strategies.py`](https://github.com/S-3-ai/sploink/blob/main/bench/strategies.py) HW_POLICIES |
| Substrate instances (Layer 2 catalog) | Sploink + customer's available providers | [`bench/strategies.py`](https://github.com/S-3-ai/sploink/blob/main/bench/strategies.py) SUBSTRATE_INSTANCES |
| Dispatch | Sploink (substrate-specific call adapters) | [`bench/strategies.py`](https://github.com/S-3-ai/sploink/blob/main/bench/strategies.py) `_dispatch` |
| Trace | Sploink | [`sploink/trace.py`](https://github.com/S-3-ai/sploink/blob/main/sploink/trace.py) |

The customer brings the IR. Sploink brings everything from policy down.
