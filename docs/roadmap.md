# Roadmap

Honest list of what works, what's coming, and what's research.

## Done (v0.1)

- [x] `sploink.wrap()` monkey-patches Anthropic, Groq, OpenAI, Together, Ollama SDKs
- [x] `CallRecord` + per-workflow trace + JSONL persistence
- [x] Concurrent-workflow isolation via `ContextVar`
- [x] Heuristic step classifier from observed call shape (no LLM)
- [x] Static rule-based router (`sploink/router.py`)
- [x] `sploink.step(...)` explicit-label context manager
- [x] HTML report (`python -m sploink.report`)
- [x] Force-directed canvas (`python -m sploink.canvas`)
- [x] `Graph` data structure (DAG with topological-sort + validation)
- [x] Architecture viewer — bipartite workflow ↔ substrate viz (`python -m sploink.architecture`)
- [x] Bench against HotpotQA (preliminary results)

## Next (v0.2)

- [ ] **`Graph.from_trace()`** — infer the workflow graph from observed traces. Critical for customers who don't use LangGraph/DSPy.
- [ ] **`SubstrateGraph` data structure** — make the substrate side first-class data, like the workflow side.
- [ ] **Graceful fallback** on routed-call failure (currently propagates exceptions).
- [ ] **Start/end timestamps** on `CallRecord` so we can prove (or disprove) parallel execution from traces.
- [ ] **Tests for each wrapper** — confirm `sploink.wrap()` actually wraps each SDK across SDK versions.
- [ ] **Rate-limit-aware Groq calls** in the bench (so cloud results aren't contaminated).
- [ ] **Apples-to-apples bench comparison** — F1 on the intersection of completed examples.

## Mid-term (v0.3 – v0.5)

- [ ] **Telemetry-driven router** — learn routing decisions from observed quality/cost outcomes per step type.
- [ ] **Workflow shape detection** that drives shape-aware routing (RAG-shaped workflows route differently than coding-shaped ones).
- [ ] **External DAG consumption** — first-class support for LangGraph and DSPy programs as input.
- [ ] **PII / prompt redaction** in traces — opt-in for enterprise compliance.
- [ ] **Configurable trace storage backend** (currently JSONL only).
- [ ] **Encryption at rest** for traces.

## Research-grade (future)

- [ ] **Workflow design search** — given a benchmark, search over which steps to include. (DSPy is the prior art here.)
- [ ] **Joint workflow + substrate optimization** — propose new topologies AND new substrate assignments jointly. Open research problem.
- [ ] **Confidential compute** — run cheap steps in TEEs / secure enclaves so enterprise customers can trust the edge.
- [ ] **Distributed compute network** — user-contributed compute as a substrate type, with reputation and incentives.

## Not in scope

- Building our own inference engine (sploink dispatches to existing providers).
- Building our own agent framework (use LangGraph or DSPy).
- Building a vector database, retriever, or knowledge graph (orthogonal to compute routing).
