"""Five-step RAG agent over HotpotQA — shared types and prompt templates.

This module owns the building blocks every graph variant uses:
  - StepResult, AgentRun, Runner types
  - Prompt templates for the canonical step types (classify / rerank / extract / reason / verify)
  - The rerank-score parser

Graph topologies (linear, parallel_dag, decomposed, ...) live in `bench/graphs.py`
and compose these helpers. The Runner is substrate-agnostic — it's what differs
between routing strategies in `bench/strategies.py`.

Canonical step labels (mirrors sploink.trace.StepLabel):
  classify   — bridge vs comparison question?
  rerank     — score each candidate paragraph 0..10
  extract    — list facts relevant to the question from top-k paragraphs
  reason     — synthesize the answer
  verify     — does the answer follow from the facts?
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from bench.dataset import Example, Paragraph


@dataclass
class StepResult:
    label: str
    text: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    substrate: str       # provider name: "ollama", "groq", "anthropic", ...
    model: str
    hardware_type: str = "cpu"  # architecture: "cpu", "lpu", "gpu", "frontier_api", ...


# A Runner takes (step_label, prompt, max_tokens) and returns a StepResult.
Runner = Callable[[str, str, int], StepResult]


@dataclass
class AgentRun:
    example: Example
    answer: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(s.cost_usd for s in self.steps)

    @property
    def total_latency_ms(self) -> float:
        # Sum is correct for purely-sequential graphs; parallel graphs override
        # by computing wall-clock time at the driver layer instead.
        return sum(s.latency_ms for s in self.steps)


def classify_prompt(question: str) -> str:
    return (
        "Classify this multi-hop question as exactly one word: "
        "'bridge' (requires finding an intermediate entity) or "
        "'comparison' (compares two entities directly).\n\n"
        f"Question: {question}\n\nType:"
    )


def rerank_prompt(question: str, paragraphs: list[Paragraph]) -> str:
    listing = "\n".join(f"[{i}] {p.render()[:400]}" for i, p in enumerate(paragraphs))
    return (
        "Rate how relevant each paragraph is to answering the question, on a 0-10 scale. "
        "Return ONLY a JSON object mapping paragraph index (string) to score (int).\n\n"
        f"Question: {question}\n\n{listing}\n\n"
        'JSON (e.g. {"0": 7, "1": 2, ...}):'
    )


def extract_prompt(question: str, top_paragraphs: list[Paragraph]) -> str:
    listing = "\n\n".join(p.render() for p in top_paragraphs)
    return (
        "From the paragraphs below, list the key facts that help answer the question. "
        "One short fact per line. No numbering, no commentary.\n\n"
        f"Question: {question}\n\nParagraphs:\n{listing}\n\nFacts:"
    )


def extract_one_paragraph_prompt(question: str, paragraph: Paragraph) -> str:
    """Variant of extract_prompt that targets a single paragraph — used by the
    decomposed graph to fan out per-paragraph extraction in parallel."""
    return (
        "From the paragraph below, list the key facts that help answer the question. "
        "One short fact per line. No numbering, no commentary. "
        "If the paragraph contains no relevant facts, reply with an empty line.\n\n"
        f"Question: {question}\n\nParagraph:\n{paragraph.render()}\n\nFacts:"
    )


def synthesize_prompt(question: str, facts: str) -> str:
    return (
        "Answer the question using only the facts. Reply with the shortest possible answer "
        "(a name, date, number, or phrase). No explanation.\n\n"
        f"Facts:\n{facts}\n\nQuestion: {question}\nAnswer:"
    )


def verify_prompt(answer: str, facts: str) -> str:
    return (
        "Does the answer follow from the facts? Reply with exactly 'yes' or 'no'.\n\n"
        f"Facts:\n{facts}\n\nAnswer: {answer}\n\nVerdict:"
    )


def parse_rerank_scores(text: str, n_paragraphs: int) -> list[float]:
    """Best-effort JSON parse. Falls back to uniform scores on failure."""
    m = re.search(r"\{[^}]+\}", text)
    if not m:
        return [5.0] * n_paragraphs
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return [5.0] * n_paragraphs
    scores = [5.0] * n_paragraphs
    for k, v in raw.items():
        try:
            idx = int(k)
            if 0 <= idx < n_paragraphs:
                scores[idx] = float(v)
        except (ValueError, TypeError):
            continue
    return scores


