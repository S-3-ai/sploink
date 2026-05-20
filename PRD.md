# Product Requirements Document: Sploink

*Workflow-aware substrate routing and skill generation for AI agents*

**Author**: Tim Nguyen
**Date**: 2026-05-17
**Status**: Draft v0.3 — pre-MVP (thesis stabilized after Gimlet competitive analysis)

---

## 1. Summary

Sploink is the workflow-and-skill layer for AI agents. It breaks each agent workflow into typed steps, routes each step to the optimal substrate (edge NPU, cloud frontier, cloud specialist, local CPU), directs hardware-level mechanisms (caching, quantization, batching, speculative decoding) per step via the inference layer's APIs, and crystallizes winning patterns into reusable substrate-tuned skills. Developers wrap their existing agent code; Sploink intercepts each step, classifies it by workflow type, and dispatches it to the best available substrate for that type under the developer's cost / latency / quality SLA.

**Core thesis (the compression):**

> ai agent workflow → typed steps → break steps apart → attribute the right compute per step → edge vs cloud, different hardware types → crystallize winning patterns into reusable skills

An agent workflow is a graph of *typed* heterogeneous steps. Step type (classification, embedding, bounded reasoning, frontier reasoning, tool execution, etc.), not just step size, determines the optimal substrate. Today every step runs on the same substrate (usually a closed frontier API), which means most steps overpay by 3–10x. Workflow-aware substrate routing with hardware-level policy directives delivers 30–60% cost reduction on real agent workloads without quality loss, with the savings compounding as the skill layer matures.

**Layer positioning:** Sploink sits at the workflow + skill layer, *above* the inference orchestration layer. We consume inference providers (Anthropic, OpenAI, Together, Modal, Groq, Cerebras, eventually Gimlet) as substrates. We are not building an inference engine. The differentiation is that we issue hardware-level directives per workflow step based on step type and observed telemetry — the inference layer below us executes them.

---

## 2. Problem

Agent workflows today have 5–20 distinct steps per request: extraction, classification, retrieval, reranking, reasoning, synthesis, tool calls, formatting. Each step has a unique compute fingerprint:

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

## 3. Vision — four-phase arc

Sploink is built as a four-phase stack. Each phase unlocks the next; each phase is a chapter of the same product, not a separate company.

- **Phase 1 (now, v1 shipped May 10 2026): Workflow telemetry and cockpit.** Rewind, replay, intervene mid-session. The original wedge. Already live with users.
- **Phase 2 (next 12 weeks): Hardware-aware workflow + skill generation.** Per-step substrate routing across edge, cloud frontier, and cloud specialists. Hardware-level policy directives (caching, quantization, spec-dec) issued per workflow step based on type. Skill library begins to crystallize from observed routing patterns.
- **Phase 3 (months 6–18): Skill distillation.** Crystallized skills compress into substrate-tuned specialized SLMs that replace cloud-API calls on the workloads where they outperform on cost, latency, or quality. Telemetry from Phases 1–2 *is* the training signal that no incumbent has.
- **Phase 4 (year 2+): Agent substrate layer.** Once skill libraries and substrate routing reach scale, Sploink becomes the runtime substrate for the broader agentic economy. Marketplace, composition search, just-in-time agent synthesis.

Trigger conditions for advancing phases:
- Phase 1 → 2: live customer workflows with measurable per-step cost; current state
- Phase 2 → 3: ≥3 customers on Phase 2 with N workflows running, M skill patterns observed
- Phase 3 → 4: skill library reaches K distinct substrate-tuned variants used across customers

**Do not pursue Phase 3 or 4 as separate companies.** They are the natural output of executing Phase 2 well.

## 3.1 The 24-month developer experience

A developer wraps their agent code:

```python
from sploink import wrap

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
4. **Gimlet validated the pattern at the inference layer; the workflow + skill layer above is open.** Gimlet Labs ($92M raised through Series A March 2026, ex-Pixie team led by Zain Asgar, partnered with NVIDIA / AMD / Intel / ARM / Cerebras / d-Matrix, customers include a top-3 frontier lab and top-3 hyperscaler) is doing heterogeneous routing at the inference layer for the largest AI labs and hyperscalers. Their existence is validating, not blocking. They operate one layer below Sploink. The Asgar pattern is "lower-layer telemetry → upper-layer decisions": Pixie did it at kernel/application, Gimlet does it at chip/inference, Sploink applies the same pattern at inference/workflow + skill. The developer-facing, workflow-typed, edge-inclusive layer above Gimlet is not occupied.
5. **Edge substrate has shipped at consumer scale.** Apple Silicon ANE (18–38 TOPS), Qualcomm X Elite (45 TOPS), Intel Lunar Lake NPU (48 TOPS), AMD XDNA2 (50 TOPS). Apple Intelligence and Microsoft Copilot+ commit the trend at the OS level. Edge is the substrate where the full hardware → workflow → skills chain is most realizable; cloud frontier APIs are where the chain collapses to inference-aware observability.
6. **Specialized SLMs are catching up on bounded reasoning.** Phi-4, Qwen 2.5, DeepSeek-R1 distillations. On bounded reasoning tasks (math, code subtasks, multi-hop search, structured analysis), specialized SLMs now match or beat frontier-via-API at far lower cost. Decomposed-edge reasoning extends this surface further: even tasks that look "frontier-required" can often be broken into bounded chunks that run on edge with a synthesis step.

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

### Anti-personas (v1)

- Pre-PMF startups with small inference bills — savings don't matter to them yet.
- Enterprise compliance buyers — sales cycle too long.
- Hobbyists / personal projects — no willingness to pay.

---

## 7. Core concepts

### Step

A single unit of work in an agent workflow: one LLM call, one tool call, one embedding lookup, one rerank operation. Steps are the routing unit.

### Workflow type

The semantic category of a step, used as the primary input to substrate routing. The current taxonomy:

| Type | Optimal substrate | Reasoning |
|---|---|---|
| Classification / intent parsing | Edge NPU | Small model, bounded output, latency-sensitive |
| Embedding | Edge NPU (batched) or cloud GPU at scale | Parallelizable, fixed model |
| Vector search / retrieval | Local CPU + RAM | Memory-bound, deterministic |
| Short structured generation | Edge SLM or Groq LPU | Bounded output, token-rate matters |
| Long-context analysis | Cerebras WSE or H100 cluster | Memory footprint exceeds edge |
| Bounded reasoning (math, code) | Edge specialized SLM or Groq LPU | Specialized SLMs match frontier |
| Decomposable bounded reasoning | Edge SLMs with decomposition (CoT, ToT, skeleton) + synthesis | Extend edge surface beyond raw step size |
| Open-ended reasoning / planning | Cloud frontier | Integrative reasoning, doesn't decompose cleanly |
| Code generation (substantial) | Cloud frontier or large local on M-series Pro/Max | Quality + context |
| Tool execution | Local CPU | Deterministic, no inference |
| Multimodal (vision) | Apple ANE or specialized vision accelerator | Vendor co-design |
| Quality verification / critique | Edge SLM (light) or cloud frontier (deep) | Bifurcates by depth |

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

The runtime component that maps each step invocation to a substrate, given the step's workflow type, fingerprint, the workflow SLA, and current substrate state (cost, latency, availability). The router does not implement hardware operations; it issues hardware-level directives (precision tier, cache strategy, batching mode, spec-dec policy) to the inference layer's APIs, which execute them on the physical substrate.

### Skill

A crystallized pattern that combines a workflow type + substrate choice + per-step policy directives + (eventually) a substrate-tuned model variant. Skills emerge from observed routing telemetry: when a routing decision works well across many invocations, it becomes a named, reusable skill. The skill library compounds with usage and is a primary moat artifact.

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
- Integrations shipped without design-partner traction

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

**Our wedge**: workflow-typed, per-step substrate routing with hardware-level policy directives and a crystallizing skill library, exposed via a developer-facing observability cockpit.

**The one-line positioning vs Gimlet** (do not pitch as "Gimlet but more"; that anchors to their measuring stick and loses): *"Gimlet routes chips. We route agents. They optimize each inference call; we orchestrate the workflow of many inference, tool, and edge calls under one SLA."*

**Why this composition is differentiated** (and where each piece exists individually):
- Workflow decomposition: LangGraph/CrewAI do this but without type classification or substrate awareness
- Per-step substrate routing across edge + cloud: nobody does this with workflow type as the primary input
- Hardware-level policy directives at the workflow layer: rare; most workflow tools don't expose quantization, cache strategy, spec-dec policy per step
- Skill crystallization from telemetry: novel; OpenPipe-class distillation is customer-directed, not telemetry-driven
- Decomposed reasoning on edge: research-validated pattern (CoT, ToT, skeleton-of-thought) but no production product applies it as a workflow-layer routing decision

The differentiation is the *combination*, not any single piece. Each piece exists somewhere; the integration across all of them is what no competitor has assembled.

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
- **18 disciplines to integrate (the breadth tax)**: workflow orchestration, agent systems, hardware architecture, inference systems, ML model architectures, reasoning decomposition, networking, confidential computing, edge runtimes, observability, RL/multi-objective optimization, developer experience, compiler intuition, economics, cryptography, capability theory, benchmarking, GTM. Most of these need fluency, not depth, on the founder side; the team must cover deep implementation for the disciplines the founder doesn't own. Failure mode: paralysis from trying to go deep on all of them. Mitigation: founder goes deep on 4 (workflow + agent systems, hardware architecture at systems level, inference systems mechanics, reasoning decomposition strategies); fluency on the rest; team hires cover implementation depth.

### Trust (edge inference's structural objection)

The single hardest external objection to the edge thesis: "If you're using compute that isn't yours, how do you trust the result hasn't been tampered with?" (asked by Jason in the May 17 cofounder call). The three-tier answer:

1. **For B2B SaaS customers on company-managed devices** (MDM-controlled Macs, Copilot+ PCs in enterprise): the company already trusts those devices. Edge inference inherits that trust. This is the answer for v1 customers.
2. **For cross-organization edge** (where the device user is not the buying organization): TEE + remote attestation. Apple Secure Enclave, Intel TDX, AMD SEV-SNP. The inference runs in an attested enclave; the attestation report proves the code and weights weren't modified; the workflow layer validates the report before trusting output. Medium-term answer.
3. **For adversarial users**: probabilistic verification — frontier sampling on a fraction of requests, redundant computation, output consistency checks. Long-term answer.

Sploink must be able to articulate all three in any cofounder, investor, or design-partner conversation.

---

## 12. Open questions

1. **Pricing**: per-token markup on routed compute (OpenRouter-style), per-seat SaaS, or a hybrid?
2. **Open / closed source**: SDK and runtime open-source to drive adoption, hosted dashboard / evals as paid?
3. **Integration depth**: ship as a Python SDK only, or also as a sidecar proxy customers can put in front of any client?
4. **First vertical to dominate**: coding agents (developer-native), research / RAG (SLM-friendly), or voice agents (latency-critical, Groq sweet spot)?
5. **Workflow-level vs. per-step optimization**: v1 is per-step; when do we add joint optimization across steps?
6. **Gimlet partnership timing**: when (if ever) do we route to Gimlet as a substrate? Their product maturity vs. ours.
7. **Decomposed-edge reasoning validation**: empirical question — what fraction of real agent reasoning steps are decomposable-bounded (can be chunked, run on edge SLMs, synthesized) vs. structurally requiring frontier? This determines whether edge's addressable surface is 30% or 60%+ of typical agent compute. MVP-able with a benchmark across 3 representative workflows.
8. **Skill crystallization mechanism**: when does an observed routing pattern become a named skill? Threshold by usage count, by quality stability, by cost-savings magnitude? The crystallization policy is itself a product surface.
9. **Trust answer per customer segment**: which of the three trust tiers do we ship in v1, v2, v3? The B2B-on-company-managed-devices tier is the v1 answer; TEE attestation is medium-term; probabilistic verification is long-term.

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

# Notes

**The compression (memorize):**
> workflow → typed steps → break apart → attribute right compute → edge vs cloud + different hardware → crystallize patterns into skills

**One-line mantra (internal):**
> "Right compute for the right work, and remember what worked."

**One-sentence layman pitch:**
> "Software that makes AI agents cheaper and faster by sending each piece of their work to the right hardware — your laptop's AI chip when possible, the cloud when actually needed."

**Three-sentence pitch:**
> "AI agents do work by chaining a lot of small steps, but today every step runs on the same expensive cloud AI, even when it doesn't need to. Sploink breaks down what the agent is doing, sends each piece to the right place — the user's own laptop AI chip for the small stuff, the cloud for the heavy reasoning — and stitches it back together. You save 30–60% on your AI bill, get faster responses, and keep more of your data on your own machine."

**Cofounder-level positioning:**
Sploink is the workflow + skill layer that uses hardware-layer telemetry to make better routing decisions and to crystallize substrate-tuned skills. We sit one layer above the inference orchestration layer (Gimlet's space). We do not build inference infrastructure; we direct it via APIs. Our moat is the integration across workflow, hardware, skills, and edge — a combination no incumbent has assembled because it requires unusual cross-disciplinary fluency to operate.

**Pattern discipline:**
Phases 1 through 4 are *chapters of the same product*, not separate startups. Resist the urge to spin up adjacent companies when new substrate layers reveal themselves (this has been a recurring failure mode). Write each new framing into the PRD as a future phase with a trigger condition.