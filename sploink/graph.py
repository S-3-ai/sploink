"""DAG data structures for execution graphs.

A `Graph` is a set of `Node`s (LM-call decision points) and edges (data
dependencies between them). Topology lives in data, not in Python control
flow — which means topologies can be generated, mutated, persisted, and
compared, instead of hand-written as functions.

This module is intentionally minimal: pure data structures + topological
sorting + validation. The actual *execution* of a graph (turning nodes into
LM calls, threading data between them) is the consumer's job — bench/graphs.py
holds the bench executor today; the SDK can add its own executor later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

if TYPE_CHECKING:
    # avoid a runtime import cycle (trace imports nothing from graph; graph
    # only needs CallRecord for type hints + from_trace())
    from sploink.trace import CallRecord


# A node's `build_prompt` takes the workflow's input and the dict of
# already-completed step results (keyed by node.id), and returns the prompt
# string to send for this node.
PromptBuilder = Callable[..., str]


# Sentinel build_prompt used when a Graph is inferred from a trace — the
# original prompt-building closures aren't recoverable from observed records,
# so inferred graphs are for analysis/visualization, not re-execution.
def _inferred_prompt(_example: Any, _state: Any) -> str:
    raise RuntimeError(
        "this Graph was inferred from a trace via Graph.from_trace() — its "
        "nodes can't be re-executed because the original prompt-builder "
        "closures weren't captured. use the inferred graph for analysis "
        "(topology, parallelism, routing decisions), not execution."
    )


@dataclass(frozen=True)
class Node:
    """One decision point in the graph — one LM call at execution time."""
    id: str                       # unique within the graph
    step: str                     # canonical step label (classify / rerank / extract / reason / verify / ...)
    max_tokens: int
    build_prompt: PromptBuilder   # (example, state_dict) -> prompt string
    # Optional metadata. Useful for fan-out nodes that need to know "I am extract #2 of 3"
    # without baking it into build_prompt's closure (so the graph can be inspected).
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Graph:
    """A directed acyclic graph of `Node`s.

    `answer_node` names which node's output becomes the workflow's final answer
    (after any normalization the executor chooses to apply).
    """
    nodes: tuple[Node, ...]
    edges: tuple[tuple[str, str], ...]
    answer_node: str

    def __post_init__(self) -> None:
        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate node ids: {ids}")
        node_set = set(ids)
        for src, dst in self.edges:
            if src not in node_set:
                raise ValueError(f"Edge references unknown source node: {src}")
            if dst not in node_set:
                raise ValueError(f"Edge references unknown destination node: {dst}")
        # Empty graphs (e.g. from an empty trace) bypass the answer_node check.
        if self.nodes and self.answer_node not in node_set:
            raise ValueError(f"answer_node {self.answer_node!r} not in graph")
        # Verify acyclicity by running a topological sort; raises on cycle.
        self.topological_layers()

    def node_by_id(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def predecessors(self, node_id: str) -> list[str]:
        return [src for src, dst in self.edges if dst == node_id]

    def successors(self, node_id: str) -> list[str]:
        return [dst for src, dst in self.edges if src == node_id]

    def roots(self) -> list[Node]:
        """Nodes with no incoming edges — these run first."""
        has_predecessor = {dst for _, dst in self.edges}
        return [n for n in self.nodes if n.id not in has_predecessor]

    @classmethod
    def from_trace(
        cls,
        records: Iterable["CallRecord"],
        method: Literal["sequential", "overlap"] = "sequential",
        overlap_tolerance_ms: float = 5.0,
    ) -> "Graph":
        """Reconstruct a Graph from observed CallRecords.

        The result is an *inferred* graph — useful for analysis (topology,
        parallelism detection, routing decisions) but NOT re-executable: the
        original prompt-builder closures aren't captured in a trace.

        Args:
          records: the CallRecord sequence (e.g. `sploink.trace.all_records()`)
          method:
            'sequential' (safe default): every node depends on the previous
              one. Always correct, never exploits parallelism. Use when in
              doubt or when timestamps aren't available.
            'overlap':  use started_at_ms / finished_at_ms to detect calls
              that ran concurrently. Calls whose execution intervals overlap
              (within `overlap_tolerance_ms`) have no dependency edge between
              them. A call B that started after A finished depends on A.
              Requires that wrap.py populates the timestamp fields.
          overlap_tolerance_ms: tiny gaps under this many ms are treated as
            "overlapped" (covers thread-scheduler jitter between two concurrent
            calls).
        """
        recs = list(records)
        if not recs:
            return cls(
                nodes=tuple(),
                edges=tuple(),
                answer_node="",
            )

        nodes = tuple(
            Node(
                id=rec.call_id,
                step=str(rec.step_label),
                max_tokens=rec.tokens_out or 256,
                build_prompt=_inferred_prompt,
                params={
                    "model":         rec.model,
                    "substrate":     rec.substrate,
                    "hardware_type": rec.hardware_type,
                    "tokens_in":     rec.tokens_in,
                    "tokens_out":    rec.tokens_out,
                    "latency_ms":    rec.latency_ms,
                    "cost_usd":      rec.cost_usd,
                    "step_index":    rec.step_index,
                },
            )
            for rec in recs
        )

        if method == "sequential":
            edges = tuple(
                (recs[i - 1].call_id, recs[i].call_id) for i in range(1, len(recs))
            )
        elif method == "overlap":
            edges = _infer_overlap_edges(recs, tolerance_ms=overlap_tolerance_ms)
        else:
            raise ValueError(f"unknown method {method!r}; use 'sequential' or 'overlap'")

        return cls(
            nodes=nodes,
            edges=edges,
            answer_node=recs[-1].call_id,
        )

    def is_inferred(self) -> bool:
        """True if this Graph was reconstructed from a trace (and thus its
        nodes can't be re-executed)."""
        return all(n.build_prompt is _inferred_prompt for n in self.nodes) if self.nodes else False

    def topological_layers(self) -> list[list[Node]]:
        """Kahn's algorithm, grouped by depth.

        Nodes in the same layer have no dependencies on each other and can be
        executed concurrently. Layers are ordered: every node in layer K only
        depends on nodes in layers < K.

        Raises ValueError if the graph contains a cycle.
        """
        in_degree: dict[str, int] = {n.id: len(self.predecessors(n.id)) for n in self.nodes}
        remaining = {n.id for n in self.nodes}
        layers: list[list[Node]] = []
        while remaining:
            layer_ids = [nid for nid in remaining if in_degree[nid] == 0]
            if not layer_ids:
                raise ValueError("Cycle detected in graph")
            # Stable order for reproducibility — by definition order of self.nodes.
            ordered = [n for n in self.nodes if n.id in layer_ids]
            layers.append(ordered)
            for nid in layer_ids:
                remaining.discard(nid)
                for succ in self.successors(nid):
                    in_degree[succ] -= 1
        return layers


def _infer_overlap_edges(
    records: list["CallRecord"], tolerance_ms: float = 5.0
) -> tuple[tuple[str, str], ...]:
    """Edge inference via temporal-overlap analysis.

    For each call B, its direct predecessors are calls A that:
      - finished before B started (with `tolerance_ms` slack), AND
      - are not transitively dominated by another predecessor of B

    Calls whose execution intervals overlap (within tolerance) have no
    edge between them — they ran in parallel.

    Falls back to step_index ordering for records missing timestamps.
    """
    def _start(r: "CallRecord") -> float:
        return r.started_at_ms if r.started_at_ms is not None else float(r.step_index)

    def _end(r: "CallRecord") -> float:
        if r.finished_at_ms is not None:
            return r.finished_at_ms
        if r.started_at_ms is not None:
            return r.started_at_ms + (r.latency_ms or 0.0)
        return float(r.step_index)

    sorted_records = sorted(records, key=_start)
    edges: list[tuple[str, str]] = []

    for i, b in enumerate(sorted_records):
        # Candidates: every earlier record whose end < b.start (with tolerance).
        candidates = [
            a for a in sorted_records[:i]
            if _end(a) < _start(b) + tolerance_ms
        ]
        if not candidates:
            continue
        # Transitive reduction: keep only candidates that are NOT predecessors
        # of another candidate (those are covered transitively).
        direct: list["CallRecord"] = []
        for a in candidates:
            is_direct = True
            for other in candidates:
                if other is a:
                    continue
                if _end(a) < _start(other) + tolerance_ms:
                    # `a` finished before `other` started → `a` is a predecessor
                    # of `other` → b reaches a via other → drop direct edge a→b
                    is_direct = False
                    break
            if is_direct:
                direct.append(a)
        for a in direct:
            edges.append((a.call_id, b.call_id))

    return tuple(edges)
