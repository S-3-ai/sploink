"""Execution-graph variants for the RAG agent bench — DAG-as-data + executor.

Three Graph variants (`LINEAR`, `PARALLEL_DAG`, `DECOMPOSED`) defined as data,
plus one generic `execute()` function that walks any DAG and produces an
AgentRun. The three are the experimental variable: same model, same dataset,
same routing strategy — only the topology differs.

Adding a fourth variant is one new Graph definition. The executor doesn't
change. This is the architectural payoff for moving topology out of code.

Latency note: executor measures wall-clock around the full graph at the
driver layer (bench/run.py), not the sum of step latencies. Nodes in the
same topological layer run concurrently via ThreadPoolExecutor.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sploink.graph import Graph, Node

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
from bench.dataset import Example, Paragraph


TOP_K = 3


def _top_k_paragraphs(example: Example, rerank_result: StepResult) -> list[Paragraph]:
    scores = parse_rerank_scores(rerank_result.text, len(example.paragraphs))
    ranked = sorted(zip(scores, example.paragraphs), key=lambda x: -x[0])
    return [p for _, p in ranked[:TOP_K]]


def _normalize_answer(text: str) -> str:
    """First non-empty line, trailing period stripped."""
    return text.strip().split("\n")[0].strip().strip(".").strip()


def _merge_decomposed_facts(extract_results: list[StepResult]) -> str:
    """Concatenate per-paragraph extract outputs into one fact list."""
    lines: list[str] = []
    for sr in extract_results:
        for line in sr.text.strip().splitlines():
            line = line.strip()
            if line:
                lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Variant: linear — sequential chain
# ─────────────────────────────────────────────────────────────────────────────
# Note: a previous version of this workflow had a `classify` step but its
# output was never read by any downstream step (dead code). It was removed
# 2026-05-22 to keep the bench honest. If a real branching policy is ever
# introduced (e.g. bridge vs comparison routes through different rerank
# prompts), classify comes back.
LINEAR = Graph(
    nodes=(
        Node(
            id="rerank", step="rerank", max_tokens=400,
            build_prompt=lambda ex, state: rerank_prompt(ex.question, ex.paragraphs),
        ),
        Node(
            id="extract", step="extract", max_tokens=300,
            build_prompt=lambda ex, state: extract_prompt(
                ex.question, _top_k_paragraphs(ex, state["rerank"]),
            ),
        ),
        Node(
            id="reason", step="reason", max_tokens=60,
            build_prompt=lambda ex, state: synthesize_prompt(
                ex.question, state["extract"].text.strip(),
            ),
        ),
        Node(
            id="verify", step="verify", max_tokens=6,
            build_prompt=lambda ex, state: verify_prompt(
                _normalize_answer(state["reason"].text), state["extract"].text.strip(),
            ),
        ),
    ),
    edges=(
        ("rerank", "extract"),
        ("extract", "reason"),
        ("reason", "verify"),
    ),
    answer_node="reason",
)


# ─────────────────────────────────────────────────────────────────────────────
# Variant: parallel_dag — same shape as linear after classify removal.
# (Kept in the registry so the bench's --graphs flag still works; for substrate
# experiments we use parallel_dag and the two are currently equivalent.)
# ─────────────────────────────────────────────────────────────────────────────
PARALLEL_DAG = Graph(
    nodes=LINEAR.nodes,
    edges=LINEAR.edges,
    answer_node="reason",
)


# ─────────────────────────────────────────────────────────────────────────────
# Variant: decomposed — fan out extract to one call per top-k paragraph
# ─────────────────────────────────────────────────────────────────────────────
# Per-paragraph extracts run in parallel; their outputs are merged (string
# concatenation, no LM call) by reason's build_prompt before synthesis.
DECOMPOSED = Graph(
    nodes=(
        Node(
            id="rerank", step="rerank", max_tokens=400,
            build_prompt=lambda ex, state: rerank_prompt(ex.question, ex.paragraphs),
        ),
        *(
            Node(
                id=f"extract_{i}", step="extract", max_tokens=150,
                build_prompt=(
                    lambda ex, state, i=i: extract_one_paragraph_prompt(
                        ex.question, _top_k_paragraphs(ex, state["rerank"])[i],
                    )
                ),
                params={"paragraph_index": i},
            )
            for i in range(TOP_K)
        ),
        Node(
            id="reason", step="reason", max_tokens=60,
            build_prompt=lambda ex, state: synthesize_prompt(
                ex.question,
                _merge_decomposed_facts(
                    [state[f"extract_{i}"] for i in range(TOP_K)]
                ),
            ),
        ),
        Node(
            id="verify", step="verify", max_tokens=6,
            build_prompt=lambda ex, state: verify_prompt(
                _normalize_answer(state["reason"].text),
                _merge_decomposed_facts(
                    [state[f"extract_{i}"] for i in range(TOP_K)]
                ),
            ),
        ),
    ),
    edges=(
        *((f"rerank", f"extract_{i}") for i in range(TOP_K)),
        *((f"extract_{i}", "reason") for i in range(TOP_K)),
        ("reason", "verify"),
    ),
    answer_node="reason",
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry — used by the driver to dispatch by name.
# ─────────────────────────────────────────────────────────────────────────────
GRAPHS: dict[str, Graph] = {
    "linear": LINEAR,
    "parallel_dag": PARALLEL_DAG,
    "decomposed": DECOMPOSED,
}


# ─────────────────────────────────────────────────────────────────────────────
# Generic executor — walks any DAG, returns an AgentRun.
# ─────────────────────────────────────────────────────────────────────────────
def execute(graph: Graph, example: Example, runner: Runner) -> AgentRun:
    """Execute `graph` on `example`, dispatching each node via `runner`.

    Nodes in the same topological layer run concurrently. Sequential layers
    run on the calling thread. State is keyed by node.id — each node's
    build_prompt sees every result produced so far.
    """
    state: dict[str, StepResult] = {}
    ordered_results: list[StepResult] = []

    for layer in graph.topological_layers():
        if len(layer) == 1:
            node = layer[0]
            result = runner(node.step, node.build_prompt(example, state), node.max_tokens)
            state[node.id] = result
            ordered_results.append(result)
        else:
            with ThreadPoolExecutor(max_workers=len(layer)) as ex:
                futs = {
                    node.id: ex.submit(
                        runner, node.step, node.build_prompt(example, state), node.max_tokens,
                    )
                    for node in layer
                }
                for node in layer:
                    result = futs[node.id].result()
                    state[node.id] = result
                    ordered_results.append(result)

    answer = _normalize_answer(state[graph.answer_node].text)
    return AgentRun(example=example, answer=answer, steps=ordered_results)
