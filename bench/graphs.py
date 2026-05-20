"""Execution-graph variants for the RAG agent bench.

Each graph is `(example, runner, top_k=3) -> AgentRun`. The Runner is the same
substrate-dispatching contract used by `bench/strategies.py` — what varies
between graphs is only the topology of the steps.

The scientific claim being tested: holding input + routing + compute pool +
model constant and varying only the graph structure produces measurable
cost / latency / quality differences. The graph is the central optimization
variable.

Variants:
  linear         — baseline 5-step sequential chain
  parallel_dag   — classify and rerank run concurrently (no data dependency)
  decomposed     — extract fans out to one call per top-k paragraph,
                   then a merge step concatenates facts

Latency note: with parallel variants, the relevant latency metric is wall-clock
time at the driver, not the sum of step latencies in the AgentRun (since steps
overlap). The driver in `bench/run.py` measures wall-clock around the graph
call, so that metric is correct regardless of graph topology.

Concurrency note: parallel variants use threads (concurrent.futures). For
Ollama, set OLLAMA_NUM_PARALLEL>=2 to enable concurrent local inference
(default in recent versions is 4). The Groq and Ollama clients used by the
runners are thread-safe.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from bench.agent import (
    AgentRun,
    Runner,
    StepResult,
    classify_prompt,
    extract_one_paragraph_prompt,
    extract_prompt,
    parse_rerank_scores,
    rerank_prompt,
    synthesize_prompt,
    verify_prompt,
)
from bench.dataset import Example


# ─────────────────────────────────────────────────────────────────────────────
# Variant: linear — baseline sequential 5-step chain
# ─────────────────────────────────────────────────────────────────────────────
def linear(example: Example, runner: Runner, top_k: int = 3) -> AgentRun:
    steps: list[StepResult] = []

    s = runner("classify", classify_prompt(example.question), 8)
    steps.append(s)

    s = runner("rerank", rerank_prompt(example.question, example.paragraphs), 400)
    steps.append(s)
    scores = parse_rerank_scores(s.text, len(example.paragraphs))
    ranked = sorted(zip(scores, example.paragraphs), key=lambda x: -x[0])
    top_paragraphs = [p for _, p in ranked[:top_k]]

    s = runner("extract", extract_prompt(example.question, top_paragraphs), 300)
    steps.append(s)
    facts = s.text.strip()

    s = runner("reason", synthesize_prompt(example.question, facts), 60)
    steps.append(s)
    answer = _normalize_answer(s.text)

    s = runner("verify", verify_prompt(answer, facts), 6)
    steps.append(s)

    return AgentRun(example=example, answer=answer, steps=steps)


# ─────────────────────────────────────────────────────────────────────────────
# Variant: parallel_dag — classify ∥ rerank, then sequential extract → reason → verify
# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis: classify and rerank have no data dependency on each other (rerank
# only consumes the question + paragraphs, not the classify output). Running
# them in parallel cuts wall-clock latency by ~min(classify_lat, rerank_lat)
# at no extra cost and no quality change.
def parallel_dag(example: Example, runner: Runner, top_k: int = 3) -> AgentRun:
    steps: list[StepResult] = []

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_classify = ex.submit(
            runner, "classify", classify_prompt(example.question), 8
        )
        fut_rerank = ex.submit(
            runner, "rerank", rerank_prompt(example.question, example.paragraphs), 400
        )
        s_classify = fut_classify.result()
        s_rerank = fut_rerank.result()

    steps.append(s_classify)
    steps.append(s_rerank)

    scores = parse_rerank_scores(s_rerank.text, len(example.paragraphs))
    ranked = sorted(zip(scores, example.paragraphs), key=lambda x: -x[0])
    top_paragraphs = [p for _, p in ranked[:top_k]]

    s = runner("extract", extract_prompt(example.question, top_paragraphs), 300)
    steps.append(s)
    facts = s.text.strip()

    s = runner("reason", synthesize_prompt(example.question, facts), 60)
    steps.append(s)
    answer = _normalize_answer(s.text)

    s = runner("verify", verify_prompt(answer, facts), 6)
    steps.append(s)

    return AgentRun(example=example, answer=answer, steps=steps)


# ─────────────────────────────────────────────────────────────────────────────
# Variant: decomposed — fan out extract to one call per top-k paragraph
# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis: per-paragraph extract calls are smaller and more focused. They
# may improve quality (each prompt has less to attend to) and enable
# parallelism (independent extracts), at the cost of more calls and losing
# cross-paragraph synthesis. Genuinely unknown outcome — that's why it's
# worth testing.
def decomposed(example: Example, runner: Runner, top_k: int = 3) -> AgentRun:
    steps: list[StepResult] = []

    s = runner("classify", classify_prompt(example.question), 8)
    steps.append(s)

    s = runner("rerank", rerank_prompt(example.question, example.paragraphs), 400)
    steps.append(s)
    scores = parse_rerank_scores(s.text, len(example.paragraphs))
    ranked = sorted(zip(scores, example.paragraphs), key=lambda x: -x[0])
    top_paragraphs = [p for _, p in ranked[:top_k]]

    # Fan out: one extract call per paragraph, in parallel.
    with ThreadPoolExecutor(max_workers=top_k) as ex:
        futures = [
            ex.submit(
                runner,
                "extract",
                extract_one_paragraph_prompt(example.question, p),
                150,
            )
            for p in top_paragraphs
        ]
        extracts = [f.result() for f in futures]

    steps.extend(extracts)

    # Merge facts into a single newline-joined block. Skip empty extractions.
    facts_lines: list[str] = []
    for sr in extracts:
        for line in sr.text.strip().splitlines():
            line = line.strip()
            if line:
                facts_lines.append(line)
    facts = "\n".join(facts_lines)

    s = runner("reason", synthesize_prompt(example.question, facts), 60)
    steps.append(s)
    answer = _normalize_answer(s.text)

    s = runner("verify", verify_prompt(answer, facts), 6)
    steps.append(s)

    return AgentRun(example=example, answer=answer, steps=steps)


# ─────────────────────────────────────────────────────────────────────────────
# Registry — used by the driver to dispatch by name.
# ─────────────────────────────────────────────────────────────────────────────
GRAPHS = {
    "linear": linear,
    "parallel_dag": parallel_dag,
    "decomposed": decomposed,
}


def _normalize_answer(text: str) -> str:
    """Take the first non-empty line of a generation, strip trailing period."""
    return text.strip().split("\n")[0].strip().strip(".").strip()
