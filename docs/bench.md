# Bench

The bench validates sploink's core claim — *per-step hardware routing produces meaningful cost reduction on real multi-step workloads* — and characterizes the cost / quality trade-off honestly.

## Setup

- **Task**: HotpotQA distractor — multi-hop QA over ~10 candidate paragraphs per question.
- **Workflow**: 4-step RAG agent (`rerank → extract → reason → verify`). (A `classify` step was removed 2026-05-22 after it was identified as dead code — its output wasn't consumed downstream.)
- **Model**: Llama 3.1 8B Instruct on both substrates — so the only variable is hardware.
- **Substrates**:
  - **CPU** — Ollama `llama3.1:8b` (4-bit quantized) on a MacBook
  - **LPU** — Groq `llama-3.1-8b-instant`
- **Metrics**: F1 + EM against gold answers; wall-clock latency; cost from observed token counts × published rates.

## Strategies compared

| Strategy | rerank | extract | reason | verify | What it tests |
|---|---|---|---|---|---|
| `cpu_only` | cpu | cpu | cpu | cpu | "What if I never touch the cloud?" |
| `lpu_only` | lpu | lpu | lpu | lpu | "What if everything ran on LPU?" |
| `hw_routed` | cpu | cpu | **lpu** | cpu | The sploink thesis — cheap steps local, reasoning to LPU |

## Results (n=30, all completed on every strategy)

| Strategy | n | Avg cost / query | Avg F1 | Avg EM | Avg latency |
|---|---|---|---|---|---|
| `cpu_only` | 30 / 30 | $0 | 0.594 | 0.500 | 13.2s |
| `lpu_only` | 30 / 30 | $0.000115 | **0.721** | 0.600 | 20.5s\* |
| `hw_routed` | 30 / 30 | **$0.000009** | 0.589 | 0.533 | **10.5s** |

\* `lpu_only` latency is inflated by Groq free-tier rate-limit retries — on a paid Groq tier this would be ~2-3s, not 20s.

### Headline numbers (`hw_routed` vs `lpu_only`)

| | Result |
|---|---|
| Cost reduction | **92.5%** ($0.000115 → $0.000009 per query) |
| F1 delta | **-0.132** (an 18% relative drop) |
| Latency reduction (on free-tier Groq) | 49% — but this is partly a rate-limit artifact, not a true win |

## What this validates — honestly

**Validated:** routing cheap steps off the LPU produces dramatic cost reduction. ~10× cheaper per query, free-tier rate-limiting also disappears as a bottleneck.

**Not yet validated:** "preserved quality." F1 drops ~13 points with the current policy. That's not free.

**Why F1 drops**: even though both substrates run "Llama 3.1 8B," they're not the same in practice. Ollama's 4-bit quantized model on CPU produces subtly worse rerank scores and extract outputs; that error propagates through the workflow. The "same model, different hardware" framing is an idealization — quantization and decoder implementation matter.

## The recoverable gap

The F1 drop is not an architectural ceiling — it's a *policy* artifact. Things we'll test next:

| Lever | What it tries | Expected effect |
|---|---|---|
| Route `rerank` to LPU too | Keep extract/verify on CPU but give rerank LPU precision | Should recover most of the F1 gap; modest cost increase |
| FP16 Ollama (`llama3.1:8b-instruct-fp16`) | Remove Q4 quantization from the CPU substrate | Closes ~half the F1 gap, same cost |
| `qwen2.5:14b` on CPU | Stronger CPU model that's better at structured outputs | Trades latency for F1, same cost |
| Constrained JSON decoding | Force rerank's JSON output to be parseable | Eliminates parse failures eating F1 |

The next iteration will be a four-cell policy sweep that produces a **cost / quality curve**, not a single point. The pitch becomes: "here's the cost-quality tradeoff; customers pick where to live on the curve."

## Reproducing

```bash
# 1. Install. The bench package is shipped in the wheel as of v0.1.3
#    (before that you had to clone the repo).
pip install "sploink[bench]"

# 2. Install Ollama from https://ollama.com/download, then pull the local model:
ollama pull llama3.1:8b

# 3. Set GROQ_API_KEY for the cloud calls (free tier at https://console.groq.com/keys).
export GROQ_API_KEY="gsk_..."

# 4. Run each strategy at n=30
python -m bench.run --n 30 --graphs parallel_dag --strategy cpu_only  --out bench/results/v2_cpu.csv
python -m bench.run --n 30 --graphs parallel_dag --strategy lpu_only  --out bench/results/v2_lpu.csv
python -m bench.run --n 30 --graphs parallel_dag --strategy hw_routed --out bench/results/v2_hw.csv

# 5. Intersection-F1 comparison (apples to apples across runs)
python -m bench.compare bench/results/v2_*.csv

# 6. Local dashboard with the savings hero + bar charts
python -m sploink.dashboard
```

Approximate run cost: ~$0.005 in Groq API spend at n=30 (the `lpu_only` run). The other two strategies are free.

**If `python -m bench.run` says "No module named 'bench'"**: you have a pre-v0.1.3 install. Upgrade with `pip install --upgrade "sploink[bench]"`.

## Caveats

- `hw_routed`'s latency advantage is partly an artifact of Groq's free-tier rate-limiting on `lpu_only`. A paid Groq tier would invert this — `lpu_only` would be ~5× faster than `hw_routed`. Latency comparisons here should be read for cost-context, not as absolute "sploink is faster."
- HotpotQA distractor is a stand-in for enterprise multi-hop QA workloads (Glean / Hebbia / Harvey-style). Real workloads will have different prompts, different paragraph distributions, and possibly different optimal routing policies.
- All numbers are from a single n=30 run with seed-stable example ordering. Tight error bars need n≥100 and ideally cross-seed averaging.
- The `decomposed` graph variant exists in the codebase but isn't part of this experiment — that's the topology axis, not the substrate axis.

## What we still want to know

- Does FP16 Ollama recover the F1 gap?
- Which step routing decision matters most? (We suspect `rerank`.)
- Does the cost/quality curve have a "sweet spot" where 90%+ savings come with <5 F1 drop?
- Does this generalize beyond HotpotQA? (TriviaQA, MS MARCO, custom enterprise workloads as design partners come on.)
