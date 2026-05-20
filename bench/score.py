"""HotpotQA-style answer scoring: token-level F1 + exact match."""
from __future__ import annotations

import re
import string
from collections import Counter


_ARTICLES = re.compile(r"\b(a|an|the)\b", re.UNICODE)


def normalize(s: str) -> str:
    s = s.lower()
    s = "".join(ch for ch in s if ch not in string.punctuation)
    s = _ARTICLES.sub(" ", s)
    s = " ".join(s.split())
    return s


def exact_match(pred: str, gold: str) -> float:
    return 1.0 if normalize(pred) == normalize(gold) else 0.0


def f1(pred: str, gold: str) -> float:
    p_tokens = normalize(pred).split()
    g_tokens = normalize(gold).split()
    if not p_tokens or not g_tokens:
        return float(p_tokens == g_tokens)
    common = Counter(p_tokens) & Counter(g_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(p_tokens)
    recall = same / len(g_tokens)
    return 2 * precision * recall / (precision + recall)
