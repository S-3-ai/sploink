---
title: Tools
---

# Tools

Two interactive visualizations of sploink's architecture and bench results. Both are self-contained HTML — no JS frameworks, no external dependencies, white theme.

## Architecture viewer

**[Open the architecture viewer →](architecture.html){ .md-button .md-button--primary }**

Shows the **workflow ↔ hardware bipartite assignment**. Left column: the workflow IR (logical agent steps with data dependencies). Right column: available hardware types (CPU / LPU / GPU / Frontier), each containing the substrate instances (Ollama / Groq / Together / Anthropic) that serve them. Solid blue edges show the routing decision for the selected strategy.

Use it to:

- Understand the two-layer routing model visually
- Compare how `cpu_only` / `lpu_only` / `hw_routed` strategies redirect the workload
- See which substrate instances are active vs planned

Regenerate locally: `python -m sploink.architecture`

## Dashboard

**[Open the bench dashboard →](dashboard.html){ .md-button .md-button--primary }**

Aggregates the latest bench results into a savings hero + bar charts + run history. Reads from `bench/results/*.csv` (CSVs produced by `python -m bench.run`).

The published dashboard above shows the n=30 HotpotQA run with the validated headline:

- **92.5% cost reduction** (`hw_routed` vs `lpu_only`)
- F1 trade-off of -0.132 with the current default policy (tunable; see [Bench](bench.md))

Regenerate locally with your own bench data: `python -m sploink.dashboard`

## Switching between them

Both viewers include a pill in their header — click **Architecture** or **Dashboard** to switch instantly. The **← Docs** link returns to this page.

## How to embed these in your own docs

The HTML files are generated from a single `python -m` invocation each — no build pipeline required. Drop them anywhere your static site is served from:

```bash
python -m sploink.architecture --out public/architecture.html
python -m sploink.dashboard --out public/dashboard.html
```

They self-link assuming they're served from the same directory (the switcher pill uses relative URLs like `dashboard.html`).
