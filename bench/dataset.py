"""HotpotQA dev-set loader for the routing bench.

We use the `distractor` config: each example ships ~10 candidate paragraphs
(some gold, some distractors) so the agent has a real rerank/extract surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Paragraph:
    title: str
    text: str  # joined sentences

    def render(self) -> str:
        return f"[{self.title}] {self.text}"


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    answer: str  # gold short-form answer
    qtype: str  # 'bridge' or 'comparison'
    paragraphs: list[Paragraph]
    gold_titles: list[str]  # which paragraphs contain supporting facts


def load(n: int = 50, split: str = "validation") -> list[Example]:
    """Load the first `n` examples from HotpotQA distractor `split`.

    Cached on disk via HF datasets after first call.
    """
    from datasets import load_dataset

    ds = load_dataset("hotpot_qa", "distractor", split=split)
    out: list[Example] = []
    for row in ds.select(range(min(n, len(ds)))):
        ctx = row["context"]
        # context is {'title': [...], 'sentences': [[...], [...], ...]}
        titles: list[str] = ctx["title"]
        sentences_by_para: list[list[str]] = ctx["sentences"]
        paragraphs = [
            Paragraph(title=t, text=" ".join(s).strip())
            for t, s in zip(titles, sentences_by_para)
        ]
        supporting = row["supporting_facts"]
        gold_titles = list(set(supporting["title"]))
        out.append(
            Example(
                id=row["id"],
                question=row["question"],
                answer=row["answer"],
                qtype=row["type"],
                paragraphs=paragraphs,
                gold_titles=gold_titles,
            )
        )
    return out


def iter_examples(n: int = 50) -> Iterator[Example]:
    yield from load(n=n)
