# Eraser.io architecture diagram

Two ways to use this file with [eraser.io](https://app.eraser.io):

1. **Diagram-as-Code (recommended)** — copy the code block under "## Diagram source" below directly into eraser.io's diagram-as-code panel. It produces a clean, deterministic layout.
2. **AI-generated** — paste the natural-language prompt under "## AI prompt" into eraser's AI Generator. Tweak the result.

---

## Diagram source (paste into eraser.io)

```eraser
title Sploink — Per-Step Hardware-Aware Routing

// ─────────────────────────────────────────────────────
// Customer-facing layer
// ─────────────────────────────────────────────────────
Customer Agent Code [icon: code, color: slategray] {
  LLM Call [label: "client.chat.create(...)", icon: terminal]
  Workflow Wrapper [label: "with sploink.workflow():", icon: brackets]
}

// ─────────────────────────────────────────────────────
// Sploink SDK (the open-source layer)
// ─────────────────────────────────────────────────────
Sploink SDK [icon: package, color: blue] {
  Wrap Layer [label: "sploink.wrap()\n(monkey-patches every SDK client)", icon: layer-group]
  Trace [label: "CallRecord stream", icon: list]

  Layer 1 Routing Policy [label: "LAYER 1\nworkflow step → hardware type", icon: branch, color: indigo]
  Layer 2 Substrate Selector [label: "LAYER 2\nhardware type → provider instance", icon: filter, color: indigo]

  Graph IR [label: "Graph.from_trace()\n(inferred workflow DAG)", icon: graph]
}

// ─────────────────────────────────────────────────────
// Substrates — hardware types with provider instances
// ─────────────────────────────────────────────────────
CPU Substrate [icon: laptop, color: blue] {
  Ollama [label: "Ollama\nllama.cpp engine\nllama3.1:8b", icon: server]
}

LPU Substrate [icon: chip, color: amber] {
  Groq [label: "Groq\nproprietary LPU engine\nllama-3.1-8b-instant", icon: server]
}

GPU Substrate [icon: gpu, color: emerald] {
  Together [label: "Together\nvLLM engine\nllama-3.1-70b", icon: server]
}

Frontier API Substrate [icon: cloud, color: red] {
  Anthropic [label: "Anthropic\nproprietary engine\nclaude-sonnet-4-6", icon: server]
}

// ─────────────────────────────────────────────────────
// Observability outputs
// ─────────────────────────────────────────────────────
Outputs [icon: chart, color: emerald] {
  JSONL Traces [label: "~/.sploink/traces/*.jsonl", icon: file]
  Dashboard [label: "sploink.dashboard\n(savings + bar charts)", icon: dashboard]
  Architecture Viewer [label: "sploink.architecture\n(bipartite viz)", icon: diagram]
}

// ─────────────────────────────────────────────────────
// Edges — the routing flow
// ─────────────────────────────────────────────────────
LLM Call > Wrap Layer
Workflow Wrapper > Wrap Layer
Wrap Layer > Layer 1 Routing Policy
Layer 1 Routing Policy > Layer 2 Substrate Selector

Layer 2 Substrate Selector > Ollama: "if cpu"
Layer 2 Substrate Selector > Groq: "if lpu"
Layer 2 Substrate Selector > Together: "if gpu"
Layer 2 Substrate Selector > Anthropic: "if frontier"

// Observability — parallel to routing
Wrap Layer > Trace
Trace > JSONL Traces
Trace > Graph IR
JSONL Traces > Dashboard
JSONL Traces > Architecture Viewer
Graph IR > Architecture Viewer
```

### What the diagram shows

- **Top**: customer's agent code. Either calls an LLM SDK directly, or wraps in `sploink.workflow()` for explicit boundaries.
- **Middle**: the Sploink SDK. The `wrap` layer intercepts calls; Layer 1 picks a hardware type per step; Layer 2 picks a specific provider for that hardware type.
- **Bottom-left**: the four substrate categories, each containing its provider + inference engine. CPU (Ollama / llama.cpp), LPU (Groq), GPU (Together / vLLM), Frontier (Anthropic).
- **Bottom-right**: observability outputs. The trace fans out to JSONL files, the dashboard, the architecture viewer, and the inferred Graph IR.

The dotted-line "if cpu / if lpu / ..." edges from Layer 2 show that exactly one substrate gets the call per step. The routing decision is dynamic per step type — the *same workflow* can have classify on CPU and reason on LPU.

---

## AI prompt (alternative — paste into eraser.io's AI generator)

> Generate a cloud-architecture diagram for "Sploink," a Python library that routes AI agent workflows across heterogeneous compute hardware.
>
> Components, grouped:
>
> **Customer side (top, gray):**
> - "Customer Agent Code" containing two boxes: "LLM Call (client.chat.create)" and "with sploink.workflow():".
>
> **Sploink SDK (middle, blue), the open-source library:**
> - "Wrap Layer (sploink.wrap)" — monkey-patches LLM SDK clients (Anthropic, Groq, OpenAI, Together, Ollama).
> - "CallRecord stream" — observability trace.
> - "Layer 1: Routing Policy" — maps workflow step → hardware type.
> - "Layer 2: Substrate Selector" — maps hardware type → specific provider instance.
> - "Graph.from_trace()" — infers a workflow DAG from observed calls.
>
> **Substrates (bottom-left), four hardware types each containing its provider + inference engine:**
> - CPU substrate (blue): Ollama with llama.cpp engine, running llama3.1:8b
> - LPU substrate (amber): Groq with its proprietary LPU engine, running llama-3.1-8b-instant
> - GPU substrate (emerald): Together with vLLM engine, running llama-3.1-70b
> - Frontier API substrate (red): Anthropic with its proprietary engine, running claude-sonnet-4-6
>
> **Outputs (bottom-right, green):**
> - JSONL traces at ~/.sploink/traces/
> - Dashboard (sploink.dashboard) showing savings + bar charts
> - Architecture Viewer (sploink.architecture) showing the bipartite workflow ↔ hardware mapping
>
> **Edges to draw:**
>
> 1. LLM Call → Wrap Layer
> 2. Workflow Wrapper → Wrap Layer
> 3. Wrap Layer → Layer 1 Routing Policy
> 4. Layer 1 → Layer 2 Substrate Selector
> 5. Layer 2 → each of the four substrates with a labeled edge ("if cpu", "if lpu", "if gpu", "if frontier")
> 6. Wrap Layer → CallRecord stream (observability, parallel to routing)
> 7. CallRecord stream → JSONL Traces, Graph IR
> 8. JSONL Traces → Dashboard, Architecture Viewer
> 9. Graph IR → Architecture Viewer
>
> The visual story: customer's agent code goes through sploink's two-layer router, which dispatches each step to a substrate based on hardware type, while observability records every call to outputs. Layer 1 is the strategic policy; Layer 2 is the operational provider selection.

---

## Tips for using the rendered diagram

- **For a slide deck**: export from eraser as SVG. Lossless at any zoom level.
- **For the README**: export PNG. GitHub renders PNGs inline.
- **For the docs site**: export SVG and drop it in `docs/assets/`. Reference it in markdown as `![Architecture](assets/architecture-diagram.svg)`.

You can also commit the source code block above into the repo so the diagram is version-controlled and regeneratable.
