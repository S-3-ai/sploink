# Product Requirements Document: Sploink

*Composable AI for inference compute: per-step routing across (model × hardware × provider) combinations, driven by a curated index and user-declared optimization weights.*

**Author**: Tim Nguyen
**Date**: 2026-05-23
**Status**: Draft v0.5 — pre-MVP. Thesis narrowed and sharpened: sploink is **composable AI for inference compute**. A curated index of validated (model × hardware × provider) combinations + objective-weighted scoring + per-step dispatch. NOT autonomous discovery, NOT learned routing, NOT auto-provisioning (those are research directions, not committed phases).

---

## 1. Summary

**Sploink is composable AI for inference compute.** It treats `(model, hardware architecture, provider)` as three independent dimensions that get composed per workflow step, driven by user-declared optimization weights (cost / latency / quality) against a curated index of validated combinations.

Concretely, sploink does four things, each as bounded and unmagical as possible:

1. **Intercepts** every LLM call in the customer's agent code via a one-line `sploink.wrap()`.
2. **Classifies** each intercepted call by step type (classify, rerank, extract, reason, verify, …).
3. **Picks** a `(model, provider, hardware)` Stack from a curated index by scoring candidate Stacks against the user's declared optimization weights.
4. **Dispatches** the call to the chosen Stack via the appropriate provider SDK.

The customer never writes substrate code, never benchmarks combinations, never tunes routing rules. They declare `optimize_for={"cost": 0.6, "latency": 0.3, "quality": 0.1}` and sploink picks combinations from its curated index that maximize the weighted score per step.

**Core thesis (the compression — v0.5):**

> ai agent workflow → typed steps → for each step, score curated `(model × hardware × provider)` Stacks by user weights → pick the highest-scoring Stack → dispatch → record telemetry → expand the index as new combinations get validated

**The product is the curated index** (knowledge of which combinations work for which workloads) **plus the scoring + dispatch runtime** (the thin shim that turns "optimize for X" into actual routed calls). The index is sploink's defensible value; the runtime is the unavoidable scaffolding.

**Three deliberate non-features** (cut from v0.4 over-reach):

- **No autonomous discovery**: sploink ships with a curated catalog. It does not crawl OpenRouter / Vast.ai / Conduit to discover combinations at runtime. New entries are added through validation work, not autonomous indexing.
- **No learned routing model**: the scoring function is a deterministic weighted sum over normalized metrics from the curated index. No ML, no bandits, no bayesian optimization in v1.
- **No auto-provisioning**: sploink does not rent GPUs from Modal / RunPod / Vast on the user's behalf. The user (or their provider) brings the compute; sploink just routes to it.

These three are real possible directions for a v2+ product, but **building them in v1 would dilute the core value (curated knowledge) with speculative complexity**.

**Layer positioning:** Sploink sits *above* inference providers and *inside* the customer's agent code. It is **composable AI at the application layer** — analogous to TVM/XLA at the compiler layer (which treated model architecture × hardware target × execution schedule as composable axes), or to OpenRouter at the model layer (which treats model × provider as composable). The hardware-architecture-aware, per-workflow-step composition niche is empty at the product layer; sploink is built to occupy it.

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

## 3. Vision — three-phase arc (deliberately bounded)

Sploink is built as a three-phase product. Each phase has explicit, narrow scope. The v0.4 expansion (discovery, joint optimization, auto-provisioning) is moved to **research directions** below — interesting, possibly future, not committed.

- **Phase 1 (now, v0.1.x shipped May 22 2026): Per-step routing across known substrates.** `sploink.wrap()` intercepts LLM calls; static routing table maps step type to one of `{cpu_only, lpu_only, hw_routed}` strategies. Lives on PyPI. Bench validates 92.5% cost reduction on HotpotQA (at a real -0.13 F1 trade-off under the default policy). Currently shipping.
- **Phase 2 (next 4-8 weeks): Curated index + objective-weighted scoring.** Replace the hand-coded routing table with `sploink.index` — a curated list of validated `(step_type, model, provider, hardware)` Recommendations, each with measured cost / latency / quality. User declares `optimize_for={"cost": w1, "latency": w2, "quality": w3}`. A deterministic scoring function picks the highest-scoring Recommendation per step. **`sploink.Stack` becomes a first-class abstraction** — a `(model, provider, hardware)` triple users can declare in their own code and add to the index.
- **Phase 3 (months 3-6): Index expansion + telemetry feedback.** Add more Recommendations through validation work (each entry requires a benchmark run we trust). Allow customers to contribute Stacks they've validated. Customer-side telemetry surfaces when a customer's traffic exposes a combination missing from the index; sploink staff validates and adds it.

That's the full committed roadmap. **Three phases. Bounded.** Each is buildable by one founder + occasional part-time help; each has a clear customer-value story; none requires research-grade work that might fail.

Trigger conditions:
- Phase 1 → 2: bench validates routing-thesis (done); ≥1 paying or design-partner customer running on Phase 1 (current gating function).
- Phase 2 → 3: ≥3 customers with workloads where curated-index recommendations meaningfully beat their current setup; index has ≥30 validated Recommendations across ≥5 step types.

**Possible research directions (NOT committed phases — explicitly de-prioritized):**

These were Phase 2/2.5/3 in v0.4 and have been demoted to research directions because each one is a multi-engineer multi-quarter project that would dilute Phase 2's focus:

- *Autonomous discovery via aggregator APIs* (OpenRouter, Vast.ai, RunPod, Conduit). Possible, but adds API integration burden and the discovered combinations still need validation work before being trustworthy. Better to grow the curated index manually until customer pull justifies automation.
- *Learned routing model* trained on cross-customer telemetry. Possible, but the deterministic scoring function works fine for the first 100 customers; ML adds complexity without clear value gain at small scale.
- *Auto-provisioning* via Modal / RunPod / Vast.ai. Possible, but the customer-money-on-the-line surface (runaway costs, leaked instances) is the highest-risk thing sploink could touch. Defer until there is sustained customer demand AND ops headcount to monitor it.
- *Skill distillation into substrate-tuned SLMs.* Real research direction; requires a training-infra team. Not solo-founder buildable.
- *Marketplace + agent substrate layer.* Late-game positioning; emerges from earlier phases working at scale.

**Discipline: do not pursue any of the research directions in v1.** They are written down so they aren't forgotten, but Phase 2 is the only committed scope for the next 6 months. Each research direction's *trigger condition* is the same: a paying customer asks for it. Until then, the right answer is "v2 roadmap."

**The single most common failure mode this PRD is trying to prevent (v0.5 update):** doing speculative engineering on the research directions instead of grinding on Phase 2 fundamentals (curated index, scoring, customer integrations). Phase 2's value is the curation work itself — the validated Recommendations — not any single new algorithm. Resist the urge to build the AutoML version.

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

### Tertiary persona (unlocked by Phase 2 discovery + Phase 3 auto-provisioning): the workload owner with no infrastructure

- Has a multi-step agent that needs inference
- Does NOT have Anthropic / Groq / Together accounts; doesn't want to set them up
- Wants to pay one company for "the right inference, please"
- Today these users either over-pay via OpenAI's API or under-deliver via a single provider
- Adoption motion: install sploink, declare workload + budget, sploink discovers + provisions + dispatches; one bill from sploink (markup on the underlying compute)

This persona is meaningful only after Phase 2.5+ when sploink can actually do discovery + joint optimization + auto-provisioning. Until then, they fall back to the primary persona's path.

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

The competitive picture expands as the phases unlock. Each row notes our relationship per phase.

| Layer | Player | Phase 1 (now) | Phase 2.5+ (joint optimization) | Phase 3+ (auto-provisioning) |
|---|---|---|---|---|
| Heterogeneous compute orchestration (chip-level) | Gimlet Labs, NVIDIA Dynamo, llm-d | We route on top of them | Same | Same |
| Managed inference clouds | Together, Modal, Fireworks, Baseten, Anyscale | We route to them | We discover them via their APIs + benchmark on demand | We auto-provision via their APIs |
| AI ASIC clouds | Groq, Cerebras, d-Matrix | Substrate backend | Discoverable + benchmarked | We dispatch with their constraints |
| GPU rental marketplaces | RunPod, Vast.ai, Salad, io.net | Not used | Discovery target (price, availability, spec) | Auto-provisioning target |
| Model API aggregation | OpenRouter, Portkey, Martian | Adjacent (model layer vs hardware layer) | Direct competitor *for the routing decision*; we differentiate by also optimizing hardware below the model choice | Same — they don't auto-provision; we do |
| Auto-provisioned inference | Modal, Replicate, Hugging Face Inference Endpoints | Not in scope | Discovery target | Direct competitor — we make this a routable substrate, not a primary product |
| Agent frameworks | LangGraph, CrewAI, LlamaIndex, DSPy | Integration targets | Same | Same — we run *inside* their workflows |
| Observability | LangSmith, Langfuse, Braintrust | We expose hardware-attribution none of them surface | Same | Same |
| Payment / settlement networks for AI | Conduit Protocol (x402 on Solana), other x402 marketplaces | Not in scope | Discovery layer — Conduit's listings become a substrate type | Substrate dispatched to with payment automation |
| Inference-cost FinOps tools | Helicone, BasePilot, internal dashboards | Light overlap on observability | Direct competitor on cost-optimization narrative; we go further by *acting* on the cost decision | Same |

**Our wedge in v0.4 framing**: be the only layer that does **discovery + joint optimization + dispatch** across the full (model × hardware × provider) space, exposed as a one-line library that drops into existing agent code. No competitor does all three; the incumbents in each row above do one piece.

**The one-line positioning evolves per phase:**

- **Phase 1**: "Drop-in `sploink.wrap()`; we route each step of your agent to the cheapest substrate you already have access to."
- **Phase 2.5**: "Tell us your workload; we discover and benchmark the best (model × hardware × provider) combination for each step, then route there."
- **Phase 3**: "Bring an agent and a budget; we find the right compute, rent it, deploy it, and dispatch your calls. You see one bill, not ten."

**Why composition rather than competition**:
- Conduit's USDC marketplace becomes a substrate type Sploink dispatches to (Phase 2.5+)
- Modal's auto-deployed inference becomes a substrate type Sploink provisions on top of (Phase 3+)
- OpenRouter's model catalog informs Sploink's discovery layer (Phase 2)
- Gimlet's chip-level routing is what powers some of our underlying substrates (Phase 3+)

Sploink is **above all of them**, optimizing across the union of their offerings.

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

### Scope (added v0.4)

The expanded vision in §3 (discovery → joint optimization → auto-provisioning) is **12–18 months of engineering for a small team**, not a solo founder's quarter. The single largest risk of the v0.4 PRD is letting the vision pull resources off Phase 1 before Phase 1 has a paying customer.

- **Premature Phase 2 build**: writing discovery integrations before any customer asks for them. Mitigation: build Phase 1 (routing across known substrates) until ≥1 paying customer; only then start the discovery layer.
- **Premature Phase 2.5 build**: building a learned joint optimizer before there's enough customer telemetry to train it on. Mitigation: ship a "leaderboard + on-demand bench" surface as the *first* iteration of Phase 2.5; defer learned routing until ≥10 customers' telemetry is available.
- **Premature Phase 3 build**: auto-provisioning is the highest-risk surface because customer money is on the line (runaway GPU costs, leaked instances). Mitigation: do not build Phase 3 until Phase 2.5 has produced a clear customer pull for it.
- **Trying to monetize too many layers**: charging for discovery, optimization, provisioning, AND routing creates a confusing pricing surface. Mitigation: revenue is one line at a time — Phase 1 is per-call markup or savings share; Phase 2.5 may add a benchmark-runs fee; Phase 3 may add a provisioning markup. Don't combine.

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

**The compression (memorize) — v0.4:**
> workflow → typed steps → for each step: discover (model × hardware × provider) options → jointly optimize for cost + quality + latency → dispatch (auto-provision if needed) → observe → re-optimize → crystallize patterns into skills

**One-line mantra (internal):**
> "Right compute for the right work — found, evaluated, provisioned, and remembered."

**One-sentence layman pitch:**
> "Software that finds the best AI compute for each piece of an agent's work and dispatches there automatically — so developers stop manually picking models and providers."

**Three-sentence pitch (Phase 1 framing — for design-partner conversations today):**
> "AI agents do work by chaining a lot of small steps, but today every step runs on the same expensive cloud AI, even when it doesn't need to. Sploink intercepts each call your agent makes and routes it to the substrate (CPU, LPU, GPU, frontier API) that's cheapest for that specific step type. You save 60–80% on your AI bill while keeping quality where it matters."

**Three-sentence pitch (Phase 2.5–3 framing — for the longer-arc story):**
> "Picking the right AI compute is an optimization problem nobody has time to solve — there are dozens of models, hundreds of hardware options, and the right answer depends on the workload. Sploink does the discovery, benchmarking, and selection automatically: tell it your workload and budget, and it routes each step of your agent to the (model × hardware × provider) combination that's best right now. Eventually it even provisions the compute for you, so you bring an agent and a bill cap; we bring everything below."

**Cofounder-level positioning:**
Sploink is the **compute meta-layer** above the entire inference stack. We treat every provider, every engine, every marketplace as a substrate we discover, evaluate, and dispatch to. Our moat is the joint-optimization brain (which combinations work best for which workloads) built on cross-customer telemetry and the user-facing routing layer that surfaces those decisions. No incumbent has assembled this because it requires fluency in workflow systems, hardware architecture, inference engines, and ML-driven optimization simultaneously.

**Pattern discipline:**
Phases 1 through 5 are *chapters of the same product*, not separate startups. Resist the urge to spin up adjacent companies when new substrate layers reveal themselves (this has been a recurring failure mode). Write each new framing into the PRD as a future phase with a trigger condition.

**Discipline against premature scope expansion (added v0.4):**
The v0.4 expansion of the thesis (discovery + joint optimization + auto-provisioning) is a 12–18-month, multi-engineer project. **It is the right direction; it is the wrong sprint.** Phase 1 still needs a paying customer before any of Phase 2+ is worth building. Each phase has an explicit trigger condition for a reason: the trigger conditions are the only thing preventing this PRD from being a 5-year wishlist instead of a buildable roadmap.