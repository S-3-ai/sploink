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

<div markdown="0" style="margin: 28px 0;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 380" style="width: 100%; max-width: 920px; height: auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 8px;" role="img" aria-label="Diagram: a 4-step agent workflow routed across two hardware types. Three cheap steps (rerank, extract, verify) go to CPU at $0 per call; the reasoning step goes to LPU. Result: ~80% inference cost reduction versus running every step on LPU.">

  <defs>
    <marker id="cheap-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981"/>
    </marker>
    <marker id="pricey-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#d97706"/>
    </marker>
  </defs>

  <text x="125" y="34" text-anchor="middle" fill="#64748b" font-size="11" font-weight="700" letter-spacing="1.2" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">WORKFLOW STEPS</text>
  <text x="450" y="34" text-anchor="middle" fill="#64748b" font-size="11" font-weight="700" letter-spacing="1.2" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">SPLOINK</text>
  <text x="775" y="34" text-anchor="middle" fill="#64748b" font-size="11" font-weight="700" letter-spacing="1.2" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">HARDWARE</text>

  <g font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">
    <rect x="35" y="62" width="180" height="50" rx="8" fill="#ffffff" stroke="#475569" stroke-width="1.5"/>
    <text x="50" y="86" font-size="14" font-weight="600" fill="#0f172a">rerank</text>
    <text x="50" y="102" font-size="11" fill="#64748b">score paragraphs</text>
    <text x="200" y="86" text-anchor="end" font-size="10" font-family="ui-monospace, SF Mono, monospace" fill="#94a3b8">400 tok</text>

    <rect x="35" y="132" width="180" height="50" rx="8" fill="#ffffff" stroke="#475569" stroke-width="1.5"/>
    <text x="50" y="156" font-size="14" font-weight="600" fill="#0f172a">extract</text>
    <text x="50" y="172" font-size="11" fill="#64748b">pull relevant facts</text>
    <text x="200" y="156" text-anchor="end" font-size="10" font-family="ui-monospace, SF Mono, monospace" fill="#94a3b8">300 tok</text>

    <rect x="35" y="202" width="180" height="50" rx="8" fill="#ffffff" stroke="#475569" stroke-width="1.5"/>
    <text x="50" y="226" font-size="14" font-weight="600" fill="#0f172a">reason</text>
    <text x="50" y="242" font-size="11" fill="#64748b">synthesize answer</text>
    <text x="200" y="226" text-anchor="end" font-size="10" font-family="ui-monospace, SF Mono, monospace" fill="#94a3b8">60 tok</text>

    <rect x="35" y="272" width="180" height="50" rx="8" fill="#ffffff" stroke="#475569" stroke-width="1.5"/>
    <text x="50" y="296" font-size="14" font-weight="600" fill="#0f172a">verify</text>
    <text x="50" y="312" font-size="11" fill="#64748b">answer follows facts?</text>
    <text x="200" y="296" text-anchor="end" font-size="10" font-family="ui-monospace, SF Mono, monospace" fill="#94a3b8">6 tok</text>
  </g>

  <g font-family="ui-monospace, SF Mono, monospace">
    <rect x="375" y="148" width="150" height="84" rx="10" fill="#f8fafc" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="4 3"/>
    <text x="450" y="172" text-anchor="middle" font-size="12" font-weight="700" fill="#3b82f6" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">router</text>
    <text x="450" y="188" text-anchor="middle" font-size="9" fill="#64748b" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">classify each call</text>
    <text x="450" y="202" text-anchor="middle" font-size="9" fill="#64748b" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">pick hardware</text>
    <text x="450" y="216" text-anchor="middle" font-size="9" fill="#64748b" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">pick substrate</text>
  </g>

  <g font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">
    <rect x="600" y="110" width="280" height="64" rx="10" fill="#eef2ff" stroke="#4f46e5" stroke-width="1.5"/>
    <rect x="600" y="110" width="280" height="4" rx="2" fill="#4f46e5"/>
    <text x="615" y="134" font-size="15" font-weight="700" fill="#0f172a">CPU</text>
    <text x="615" y="150" font-size="11" fill="#64748b">Ollama, local · llama3.1:8b</text>
    <text x="865" y="134" text-anchor="end" font-size="13" font-weight="700" fill="#10b981" font-family="ui-monospace, SF Mono, monospace">$0</text>
    <text x="865" y="150" text-anchor="end" font-size="10" fill="#64748b" font-family="ui-monospace, SF Mono, monospace">marginal</text>
    <text x="865" y="166" text-anchor="end" font-size="10" fill="#94a3b8">3 calls routed here →</text>

    <rect x="600" y="210" width="280" height="64" rx="10" fill="#fef3c7" stroke="#d97706" stroke-width="1.5"/>
    <rect x="600" y="210" width="280" height="4" rx="2" fill="#d97706"/>
    <text x="615" y="234" font-size="15" font-weight="700" fill="#0f172a">LPU</text>
    <text x="615" y="250" font-size="11" fill="#64748b">Groq, cloud · llama-3.1-8b-instant</text>
    <text x="865" y="234" text-anchor="end" font-size="13" font-weight="700" fill="#d97706" font-family="ui-monospace, SF Mono, monospace">$0.05/M</text>
    <text x="865" y="250" text-anchor="end" font-size="10" fill="#64748b" font-family="ui-monospace, SF Mono, monospace">in tokens</text>
    <text x="865" y="266" text-anchor="end" font-size="10" fill="#94a3b8">1 call routed here →</text>
  </g>

  <path d="M 215 87 C 290 87, 290 142, 375 142" stroke="#cbd5e1" stroke-width="1.5" fill="none"/>
  <path d="M 215 157 C 290 157, 290 175, 375 175" stroke="#cbd5e1" stroke-width="1.5" fill="none"/>
  <path d="M 215 227 C 290 227, 290 190, 375 190" stroke="#cbd5e1" stroke-width="1.5" fill="none"/>
  <path d="M 215 297 C 290 297, 290 210, 375 210" stroke="#cbd5e1" stroke-width="1.5" fill="none"/>

  <path d="M 525 162 C 565 162, 565 142, 600 142" stroke="#10b981" stroke-width="2" fill="none" marker-end="url(#cheap-arrow)" opacity="0.9"/>
  <path d="M 525 178 C 565 178, 565 142, 600 142" stroke="#10b981" stroke-width="2" fill="none" marker-end="url(#cheap-arrow)" opacity="0.7"/>
  <path d="M 525 195 C 565 195, 565 242, 600 242" stroke="#d97706" stroke-width="2.5" fill="none" marker-end="url(#pricey-arrow)"/>
  <path d="M 525 212 C 565 212, 565 142, 600 142" stroke="#10b981" stroke-width="2" fill="none" marker-end="url(#cheap-arrow)" opacity="0.55"/>

  <text x="450" y="365" text-anchor="middle" fill="#475569" font-size="12" font-style="italic" font-family="-apple-system, BlinkMacSystemFont, Inter, sans-serif">Same model on both hardware. The reason step goes to LPU; rerank / extract / verify stay on free CPU.</text>

</svg>
</div>

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
