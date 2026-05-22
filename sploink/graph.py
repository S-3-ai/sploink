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
from typing import Any, Callable


# A node's `build_prompt` takes the workflow's input and the dict of
# already-completed step results (keyed by node.id), and returns the prompt
# string to send for this node.
PromptBuilder = Callable[..., str]


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
        if self.answer_node not in node_set:
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
