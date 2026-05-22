---
title: Sploink
hide:
  - navigation
  - toc
---

# Sploink

<p style="font-size: 1.2em; color: var(--md-default-fg-color--light); margin-top: -8px;">
<strong>Heterogeneous compute routing for AI agent workflows.</strong>
</p>

Sploink intercepts each LLM call in your agent code, classifies it by step type, and routes it to the hardware architecture (CPU, LPU, GPU, NPU, frontier API) where it's most cost-effective. Same agent code, different per-step compute placement, 60-80% inference cost savings on multi-step workloads.

[Get started in 30 seconds →](quickstart.md){ .md-button .md-button--primary }
[View on GitHub →](https://github.com/S-3-ai/sploink){ .md-button }

---

## Why per-step hardware routing?

A typical agent workflow has 5–20 distinct LLM calls per request — classification, reranking, extraction, reasoning, verification. Each step has a wildly different compute profile, but most stacks route every step to the same frontier API and overpay on the easy ones.

The cost gap between **hardware architectures** for the same model is huge:

| Hardware | $ / M input tokens (Llama 8B) | Speed | vs Frontier |
|---|---|---|---|
| Frontier API (Anthropic Sonnet) | $3.00 | medium | 1× |
| GPU rental (Together) | $0.18 | medium | 17× cheaper |
| LPU (Groq) | $0.05 | fast | **60× cheaper** |
| CPU (Ollama local) | $0 | slow | ∞× cheaper |

Sploink routes the cheap steps to cheap hardware, keeps the hard steps on capable hardware. The cost compounds across every step of every query.

---

## In 30 seconds

```bash
pip install "sploink[anthropic]"   # or [groq], [ollama], [all]
export ANTHROPIC_API_KEY="sk-ant-..."   # your provider's key, not sploink-specific
```

```python
import sploink
from anthropic import Anthropic   # or groq, openai, ollama, together

sploink.wrap()                    # patch every supported SDK
sploink.enable_routing()          # opt into per-step routing

client = Anthropic()
# ... your existing agent code, unchanged ...

sploink.trace.print_summary()     # see per-step cost / latency / hardware
```

That's it. The interception is transparent — no agent-code changes needed.

[Full quickstart →](quickstart.md)

---

## Two-layer architecture

Sploink routes in two decoupled layers:

**Layer 1 — Routing policy.** Workflow step → hardware type. *"Classify is cheap → CPU. Reasoning needs low latency → LPU."* This is sploink's strategic decision.

**Layer 2 — Substrate selection.** Hardware type → specific provider instance. *"Need a CPU? Ollama if available. Need an LPU? Groq."* This is operational; eventually load-balancing across providers.

Adding a new provider (Salad for CPU, Cerebras for LPU) is a one-line config change. Adding a new hardware type is a config change plus a dispatcher.

[Open the interactive architecture diagram →](architecture.md)

---

## Bench results

We ran HotpotQA (multi-hop QA) on a 4-step workflow (rerank → extract → reason → verify), Llama 3.1 8B on both substrates, n=30. Clean run — no rate-limit failures.

| Strategy | Cost / query | F1 | Latency |
|---|---|---|---|
| `cpu_only` (Ollama local) | $0 | 0.594 | 13.2s |
| `lpu_only` (Groq LPU) | $0.000115 | **0.721** | 20.5s |
| `hw_routed` (cheap → CPU, reason → LPU) | **$0.000009** | 0.589 | 10.5s |

**Headline (`hw_routed` vs `lpu_only`)**: 92.5% cost reduction, F1 delta -0.132.

The cost half of the thesis is strongly supported. The F1 trade-off with the *current* routing policy is real but tunable — the next iteration sweeps over which steps get routed to which hardware, and characterizes the full cost-quality curve.

[Full bench methodology + caveats →](bench.md)

---

## What's in the box

| Module | What it does |
|---|---|
| `sploink.wrap()` | Monkey-patches Anthropic, Groq, OpenAI, Together, Ollama clients |
| `sploink.trace` | Per-workflow `CallRecord`s, JSONL persistence, summary tables |
| `sploink.router` | Static rule table mapping step type → hardware type |
| `sploink.graph` | DAG data structure for execution graphs |
| `sploink.architecture` | Single-file HTML viz of workflow ↔ hardware bipartite |

---

## Composes with what you already use

Sploink doesn't replace your agent framework — it routes whatever you already have:

- Using **LangGraph** or **DSPy**? Sploink wraps the LLM calls those frameworks emit.
- Using plain Python? Sploink's wrap layer works on any of the major LLM SDKs.
- Using **OpenRouter** for model-level routing? Sploink sits one layer below: substrate routing.

The model layer can stay yours; sploink owns the hardware decision.

---

## Where we are

| | Status |
|---|---|
| Observability (`sploink.wrap()`) | ✅ Works |
| Static rule-based routing | ✅ Works |
| Two-layer architecture (policy + selection) | ✅ Works |
| Trace visualization | ✅ Works |
| Bench against HotpotQA | ✅ Methodology stable, numbers refreshing |
| Learned routing from telemetry | 🔜 Roadmap |
| Graph inference from trace | 🔜 Roadmap |
| Hot-swap LangGraph / DSPy graphs | 🔜 Roadmap |

[Full roadmap →](roadmap.md)

---

## License

Sploink is [MIT licensed](https://github.com/S-3-ai/sploink/blob/main/LICENSE). The SDK, bench, examples, and docs are all open source. Future enterprise features (hosted dashboard, learned routing models, managed substrate marketplace) will live in a separate proprietary product; the open-source library will stay open.

<br>

<p style="text-align: center; color: var(--md-default-fg-color--light); margin-top: 40px;">
Built by <a href="https://github.com/TimothyNguyen04">Tim Nguyen</a> · Pre-MVP, accepting feedback
</p>
