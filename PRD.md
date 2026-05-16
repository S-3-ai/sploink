# Product Requirements Document: Sploink

*Heterogeneous compute routing for AI agent workflows*

**Author**: Tim Nguyen
**Date**: 2026-05-16
**Status**: Draft v0.2 — pre-MVP

---

## 1. Summary

Sploink routes each step of an AI agent workflow to the optimal compute substrate — cloud GPU, AI ASIC, edge NPU, or closed-API passthrough — based on the step's actual compute profile and the developer's cost / latency / quality SLA. Developers wrap their existing agent code; Sploink intercepts each LLM call, tool call, embedding, or compute step and dispatches it to the best substrate available.

**Core thesis**: an agent workflow is a graph of heterogeneous steps with wildly different compute needs. Today, every step runs on the same hardware (one provider, one chip type), which means most steps overpay. Routing per step against the step's actual demands can deliver 3–10x cost reduction without quality loss.

---

## 2. Problem

Agent workflows today have 5–20 distinct steps per request: extraction, retrieval, reranking, reasoning, synthesis, tool calls, formatting. Each step has a unique compute fingerprint:

- A 50-token classification doesn't need an H100. It needs a 4090 or an NPU.
- A long-context summarization wants Cerebras or a memory-rich GPU.
- A latency-critical short-form generation wants Groq's LPU.
- A frontier reasoning step needs Claude or GPT.
- A tool call needs a CPU.

Despite this, almost all production workflows run every step on the same substrate — usually a closed API or a single inference provider. That's because:

1. Routing across providers is operationally painful (different SDKs, different auth, different latency profiles).
2. Developers have no per-step cost or latency visibility to know which step to optimize.
3. There's no abstraction that exposes "the substrate" as a first-class routable choice.

The opportunity: **make per-step substrate routing a one-line code change.**

---

## 3. Vision (24 months)

A developer wraps their agent code:

```python
from splnk import wrap

agent = wrap(my_agent, sla={"cost": "minimize", "latency_p95_ms": 2000})
result = agent.run(query)
```

Under the hood, Sploink:

- Intercepts every LLM call, tool call, and inference step
- Profiles each step's compute needs (input size, output size, latency requirement, quality bar)
- Routes each step to the optimal substrate based on the SLA and current substrate cost/availability
- Falls back to the original frontier API for steps explicitly marked as requiring it
- Logs every routing decision with cost, latency, and quality attribution to a dashboard
- Continuously re-evaluates whether a cheaper substrate maintains quality, via background evals

The developer never thinks about Groq vs. H100 vs. consumer GPU vs. Claude. They think about cost / latency / quality SLAs and the substrate becomes invisible.

---

## 4. Why now

1. **Substrate diversity is real and growing.** Groq, Cerebras, d-Matrix, AMD MI300, Intel Gaudi 3, Apple Silicon NPU, Microsoft Copilot+ NPU. Each has a distinct cost-perf profile. Five years ago this was "NVIDIA or nothing."
2. **Open models are good enough for most steps.** Llama 3, Qwen 2.5, Phi-4, DeepSeek-V3 match closed models on extraction, classification, reranking, and summarization. The frontier-only assumption no longer holds.
3. **Inference cost is the dominant agent-economics concern.** Companies at scale spend $100K–$10M/month on inference. A 3–5x reduction is a real budget line item.
4. **Gimlet validated the thesis (and the ceiling).** Their July 2025 paper proves measurable TCO benefits from heterogeneous routing on real workloads. They target infrastructure teams at frontier labs; the developer-facing layer above their orchestration is open.

---

## 5. Non-goals (v1)

- **Not** building inference hardware orchestration from scratch. Use Modal, Together, Groq, OpenRouter, and (eventually) Gimlet as substrate backends.
- **Not** competing with Anthropic / OpenAI on frontier reasoning quality.
- **Not** an agent framework. Plug into LangGraph, CrewAI, raw Python — wherever the agent already lives.
- **Not** an MLIR compiler stack. Use existing ONNX, TensorRT, MLC-LLM, ROCm toolchains.
- **Not** a marketplace. The product is the runtime + observability layer.

---

## 6. Users

### Primary persona: AI engineer at a Series A–C startup spending real money on inference

- Building a production agent (coding assistant, research agent, voice agent, support automation)
- Current inference spend: $10K–$500K/month
- Agent has 5–20 LLM/tool calls per request
- Currently runs everything on OpenAI or Anthropic
- Pain: bill is growing faster than revenue; no visibility into per-step cost
- Adoption motion: Python SDK, drop in 10 lines, see savings within a day

### Secondary persona: platform/infra lead at a scaled AI company

- Owns inference cost budget across multiple product teams
- Already mixed-model (some open, some closed)
- Wants per-step observability and substrate flexibility
- Will adopt as a sidecar/proxy or via SDK integration

### Anti-personas

- Pre-PMF startups with small inference bills — savings don't matter to them yet.
- Enterprise compliance buyers — sales cycle too long.
- Hobbyists / personal projects — no willingness to pay.

---

## 7. Core concepts

### Step

A single unit of work in an agent workflow: one LLM call, one tool call, one embedding lookup, one rerank operation. Steps are the routing unit.

### Substrate

A compute backend Sploink can dispatch a step to. Each substrate is characterized by cost ($/1K tokens or $/sec), latency profile (P50/P95), available models, and supported step types. Examples:

- Modal H100 / L4
- Together AI (Llama, Qwen, Mixtral on NVIDIA)
- Groq LPU (Llama, Qwen — latency-optimized)
- Cerebras (long-context, high-throughput)
- Anthropic / OpenAI passthrough (frontier reasoning)
- Apple Silicon / browser WebGPU (edge, on-device, free)

### Step fingerprint

A profile of a step's compute demands: input size distribution, output size distribution, latency target, quality target, and a step-type label (extraction, classification, reasoning, summarization, etc.). Derived from runtime observation, not declared upfront.

### Router

The runtime component that maps each step invocation to a substrate, given the step's fingerprint, the workflow SLA, and current substrate state (cost, latency, availability).

### SLA

A per-workflow or per-step constraint set: cost ceiling, latency budget, quality floor. The router minimizes against the SLA.

---

## 8. v1 scope (MVP — 12 weeks)

The smallest thing that demonstrates per-step heterogeneous routing on real workloads.

### Must-have

1. **Python SDK** that wraps an existing agent (function or LangGraph workflow). Intercepts LLM calls and routes per step. Minimum integration: 5 lines of code.
2. **4 substrate backends** integrated:
   - Anthropic API (frontier passthrough)
   - OpenAI API (frontier passthrough)
   - Together AI (open models on NVIDIA)
   - Groq (open models on LPU)
   - Stretch: Modal direct, for custom-deployed open models
3. **Step fingerprinting**: runtime profiling of each step type within a workflow, building a per-step cost / latency / quality table.
4. **Router v0**: rule-based, profile-driven. No convex optimization yet. Picks the cheapest substrate that meets the SLA based on profiled performance.
5. **Trace dashboard** showing per-step substrate, cost, latency, and aggregate workflow cost. Hard requirement: customer can see *why* a step was routed where it was.
6. **Eval harness**: customer-defined eval suite per workflow. Every routing decision is validated against the eval suite asynchronously; quality regressions trigger rollback to the prior substrate.
7. **Cost dashboard**: aggregate monthly savings vs. baseline (what they would have paid running everything on their current default).

### Stretch

- Integration with LangGraph as a drop-in execution backend
- Custom-model deployment (BYO fine-tuned SLM via Modal)
- Cerebras and d-Matrix backends
- Workflow-level optimization (joint optimization across all steps, not just per-step)
- Cold-start mitigation via pre-warmed pools

### Explicitly deferred

- Edge / on-device routing
- Marketplace / public skill catalog
- Multi-tenant billing
- Enterprise SSO and governance
- Gimlet as a routing substrate (revisit after their API matures)
- Convex / formal optimization router (the v1 rule-based router is sufficient)

---

## 9. Success metrics

### v1 launch (12 weeks)

- 5 design partners running production workflows on Sploink
- Demonstrated ≥3x cost reduction on the routable portion of ≥1 workflow per partner, at ≤2% quality regression measured on customer evals
- 1 published case study with concrete numbers
- SDK install → first successful wrapped agent run < 30 minutes

### 12 months

- $100K MRR or 50 paying customers
- Substrate catalog covers ≥8 backends including ≥2 ASIC vendors
- Public benchmark dataset of step-type × substrate performance (becomes the data moat)

### Anti-metrics

- Substrate breadth without usage
- Dashboard impressions without behavior change
- Integration breadth without design-partner traction

---

## 10. Competitive positioning

| Layer | Player | Our relationship |
|---|---|---|
| Heterogeneous compute orchestration (infrastructure) | Gimlet Labs, NVIDIA Dynamo, llm-d | Substrate provider — we route to / on top of them |
| Single-provider inference (NVIDIA-bound) | Together, Modal, Fireworks, Baseten | Substrate backends we route to |
| AI ASIC clouds | Groq, Cerebras, d-Matrix | Substrate backends |
| Model API aggregation | OpenRouter, Portkey, Martian | Adjacent — they route between *closed models*; we route between *substrates* |
| Agent frameworks | LangGraph, CrewAI, LlamaIndex | Integration targets; we run inside their workflows |
| Observability | LangSmith, Langfuse, Braintrust | We expose hardware-attribution none of them surface |

**Our wedge**: per-step substrate routing with developer-facing observability. Gimlet does the infrastructure; we do the developer experience above it. OpenRouter routes models; we route substrates. LangSmith traces workflows; we route and trace them.

---

## 11. Risks

### Technical

- **Cold-start latency on diverse substrates**: switching substrates mid-workflow introduces tail latency. Mitigation: keep-alive heuristics, pre-warm common paths, accept cost overhead for latency-critical steps.
- **Step fingerprinting cold start**: a new workflow has no historical data, so the first routing decisions are uninformed. Mitigation: ship default fingerprints per common step type (extraction, classification, etc.); learn customer-specific fingerprints over time.
- **Quality regression detection**: hard to know if a cheaper substrate is "good enough" without ground truth. Mitigation: customer-defined evals as a first-class product surface; LLM-as-judge for the long tail.

### Market

- **Inference prices drop faster than our savings story**: if frontier API prices drop 10x, our 3-5x savings story shrinks. Mitigation: position around aggregate workflow optimization, not raw $/token; emphasize the steps where open models are *already* equivalent and only cost remains.
- **Gimlet adds a developer-facing SDK**: they could ship the same developer wrapper on top of their orchestrator. Mitigation: speed to developer mindshare; they ship enterprise-first.
- **Closed-API providers expose hardware choice**: unlikely in 24 months — Anthropic / OpenAI have no incentive — but if it happens, our routing scope on closed APIs grows.

### Execution

- **Eval infrastructure is hard**: weak evals → weak routing → broken trust. Mitigation: invest in evals from week 1, not as an afterthought.
- **Cold outreach to design partners is the gating function**: nothing else matters until we have 5 customers willing to run production workflows on Sploink.

---

## 12. Open questions

1. **Pricing**: per-token markup on routed compute (OpenRouter-style), per-seat SaaS, or a hybrid?
2. **Open / closed source**: SDK and runtime open-source to drive adoption, hosted dashboard / evals as paid?
3. **Integration depth**: ship as a Python SDK only, or also as a sidecar/proxy customers can put in front of any client?
4. **First vertical to dominate**: coding agents (developer-native), research / RAG (SLM-friendly), or voice agents (latency-critical, Groq sweet spot)?
5. **Workflow-level vs. per-step optimization**: v1 is per-step; when do we add joint optimization across steps?
6. **Gimlet partnership timing**: when (if ever) do we route to Gimlet as a substrate? Their product maturity vs. ours.

---

## 13. Milestones

| Week | Milestone |
|---|---|
| 1 | Thesis validated with 3 prospective customer conversations |
| 2 | End-to-end demo: one workflow, two substrates, measured cost delta |
| 4 | SDK alpha: wrap an agent, route between Anthropic + Groq + Together, log traces |
| 6 | Router v0 with profiled fingerprints; eval harness wired in |
| 8 | First design partner running production traffic on a single wrapped workflow |
| 10 | Trace + cost dashboard live; nightly evals running |
| 12 | 5 design partners, 1 case study, pricing model decided, fundraising deck v1 |

---

## 14. What we are *not* doing this week

- Writing more research memos
- Reading more papers
- Drafting a Series A deck before a working demo
- Building hardware orchestration from scratch
- Designing a marketplace
- Building anything customers haven't asked for

Everything in v1 serves one question: **can per-step substrate routing deliver real cost savings on real workflows without quality regression?** If yes, this is a company. If no, we learn fast.

---

## 15. Appendix: terminology

- **Step**: one unit of work in an agent workflow (LLM call, tool call, embedding, etc.).
- **Substrate**: a compute backend Sploink can dispatch to.
- **Step fingerprint**: profiled compute / latency / quality characteristics of a step.
- **Router**: runtime component selecting substrate per step.
- **SLA**: customer-defined cost / latency / quality envelope.
- **Frontier passthrough**: forwarding a step to a closed API (Claude, GPT) without substrate selection.
