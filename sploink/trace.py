"""Trace records and aggregation for observed agent runs."""
from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

StepLabel = Literal[
    "classify",
    "extract",
    "rerank",
    "embed",
    "summarize_short",
    "summarize_long",
    "reason",
    "code_gen",
    "tool_call_decision",
    "verify",
    "multimodal",
    "tool_execute",
    "code_execute",
    "unknown",
]

OutputStructure = Literal["freeform", "json", "tool_call"]
# Hardware architecture categories — the load-bearing axis for routing decisions.
# "edge" was dropped because it conflated geography (where the chip lives) with
# architecture (what kind of chip it is). On-device CPU is just `cpu` with a
# location property; the architecture is what matters for cost/latency.
HardwareType = Literal[
    "cpu",          # von Neumann general-purpose (Ollama on laptop CPU, AWS Graviton)
    "gpu",          # massively parallel SIMT (Together, RunPod, local CUDA/Metal)
    "lpu",          # deterministic tensor streaming (Groq)
    "tpu",          # systolic array, matmul-specialized (Google Cloud)
    "npu",          # on-device neural accelerator (Apple Neural Engine, Qualcomm Hexagon)
    "wafer_scale",  # entire-wafer chip (Cerebras WSE)
    "frontier_api", # closed-API, hardware opaque (Anthropic, OpenAI)
]


class CallRecord(BaseModel):
    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    workflow_id: str
    step_index: int
    step_label: StepLabel
    is_llm: bool
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    output_structure: OutputStructure = "freeform"
    latency_ms: float
    cost_usd: float
    substrate: str | None = None
    hardware_type: HardwareType | None = None
    # Monotonic timestamps (ms, relative to process start via time.perf_counter).
    # Used by Graph.from_trace() to detect parallelism via temporal overlap.
    started_at_ms: float | None = None
    finished_at_ms: float | None = None


_workflow_id: ContextVar[str | None] = ContextVar("_workflow_id", default=None)
# Per-workflow record store. Indexed by workflow_id so concurrent workflows
# (asyncio tasks, FastAPI requests) don't interleave their records.
_records_by_workflow: dict[str, list[CallRecord]] = defaultdict(list)
# Per-workflow step counters, same reason.
_step_counters: dict[str, int] = defaultdict(int)


def current_workflow_id() -> str:
    wid = _workflow_id.get()
    if wid is None:
        wid = uuid.uuid4().hex[:12]
        _workflow_id.set(wid)
    return wid


class workflow:
    """Context manager that scopes one workflow.

    Inside the block, every LLM call wrapped by sploink.wrap() is attributed
    to a fresh workflow_id. On exit, you can recover the trace and infer the
    workflow Graph from it.

    Usage:
        import sploink
        sploink.wrap()
        with sploink.workflow() as wf:
            client.chat.completions.create(...)   # observed
            client.chat.completions.create(...)   # observed
            # ... any number of LLM calls, any SDK ...

        # After exit:
        graph = wf.graph()        # inferred sploink.graph.Graph
        records = wf.records()    # the raw CallRecord list
        summary = wf.summary()    # cost / latency / step-type aggregates

    Works under threading and asyncio — each task or thread gets its own
    workflow_id via contextvars. Concurrent workflows do not interleave.
    """
    def __init__(self, workflow_id: str | None = None) -> None:
        # If the caller provided an id (e.g., FastAPI request id), use it;
        # otherwise we mint a fresh one.
        self._provided_id = workflow_id
        self._token: Any = None
        self.id: str = ""

    def __enter__(self) -> "workflow":
        self.id = self._provided_id or uuid.uuid4().hex[:12]
        self._token = _workflow_id.set(self.id)
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._token is not None:
            _workflow_id.reset(self._token)

    def records(self) -> list[CallRecord]:
        """The observed CallRecords for this workflow."""
        return list(_records_by_workflow.get(self.id, []))

    def graph(self, method: str = "sequential") -> Any:
        """Infer a sploink.graph.Graph from this workflow's trace.

        method='sequential' is the safe default (no parallelism assumed).
        method='overlap' uses timestamps to detect concurrent calls.
        """
        from sploink.graph import Graph
        return Graph.from_trace(self.records(), method=method)  # type: ignore[arg-type]

    def summary(self) -> dict[str, Any]:
        """Aggregate stats for this workflow (delegates to module summary())."""
        return summary(workflow_id=self.id)


def set_workflow_id(workflow_id: str) -> None:
    """Pin a specific workflow_id for the current context (e.g. one per request)."""
    _workflow_id.set(workflow_id)


def next_step_index() -> int:
    wid = current_workflow_id()
    i = _step_counters[wid]
    _step_counters[wid] = i + 1
    return i


def record(call: CallRecord) -> None:
    _records_by_workflow[call.workflow_id].append(call)
    _write_jsonl(call)


def all_records(workflow_id: str | None = None) -> list[CallRecord]:
    """Records for the current workflow (default) or a specific workflow."""
    wid = workflow_id if workflow_id is not None else current_workflow_id()
    return list(_records_by_workflow.get(wid, []))


def all_records_global() -> list[CallRecord]:
    """All records across every workflow_id. Use for cross-workflow reports."""
    out: list[CallRecord] = []
    for v in _records_by_workflow.values():
        out.extend(v)
    return out


def reset(workflow_id: str | None = None) -> None:
    """Clear records for the current workflow. Pass workflow_id=None and call
    reset_all() to wipe everything."""
    wid = workflow_id if workflow_id is not None else current_workflow_id()
    _records_by_workflow.pop(wid, None)
    _step_counters.pop(wid, None)
    _workflow_id.set(None)


def reset_all() -> None:
    """Drop every workflow's records. Test-only."""
    _records_by_workflow.clear()
    _step_counters.clear()
    _workflow_id.set(None)


def _trace_path() -> Path:
    root = Path(os.environ.get("SPLOINK_TRACE_DIR", Path.home() / ".sploink" / "traces"))
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{current_workflow_id()}.jsonl"


def _write_jsonl(call: CallRecord) -> None:
    with _trace_path().open("a") as f:
        f.write(call.model_dump_json() + "\n")


def summary(workflow_id: str | None = None) -> dict[str, Any]:
    """Aggregate trace by step type and overall for one workflow."""
    wid = workflow_id if workflow_id is not None else current_workflow_id()
    records = _records_by_workflow.get(wid, [])
    if not records:
        return {"workflow_id": wid, "calls": 0, "by_step": {}, "by_hardware": {}, "totals": {
            "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0, "cost_usd": 0.0,
        }}

    by_step: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0, "cost_usd": 0.0}
    )
    by_hardware: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"count": 0, "cost_usd": 0.0, "latency_ms": 0.0}
    )

    for r in records:
        s = by_step[r.step_label]
        s["count"] += 1
        s["tokens_in"] += r.tokens_in or 0
        s["tokens_out"] += r.tokens_out or 0
        s["latency_ms"] += r.latency_ms
        s["cost_usd"] += r.cost_usd

        hw = r.hardware_type or "unknown"
        h = by_hardware[hw]
        h["count"] += 1
        h["cost_usd"] += r.cost_usd
        h["latency_ms"] += r.latency_ms

    return {
        "workflow_id": wid,
        "calls": len(records),
        "by_step": dict(by_step),
        "by_hardware": dict(by_hardware),
        "totals": {
            "tokens_in": sum(r.tokens_in or 0 for r in records),
            "tokens_out": sum(r.tokens_out or 0 for r in records),
            "latency_ms": sum(r.latency_ms for r in records),
            "cost_usd": sum(r.cost_usd for r in records),
        },
    }


def print_summary() -> None:
    s = summary()
    if s["calls"] == 0:
        print("(no calls observed)")
        return
    print(f"workflow {s['workflow_id']}  |  {s['calls']} calls  |  ${s['totals']['cost_usd']:.6f}  |  {s['totals']['latency_ms']:.0f} ms")
    print(f"  tokens: in={s['totals']['tokens_in']:>6}  out={s['totals']['tokens_out']:>6}")
    print("  by step:")
    for step, stats in s["by_step"].items():
        print(f"    {step:<24} {stats['count']:>2}x  ${stats['cost_usd']:.6f}  {stats['latency_ms']:.0f}ms")
    print("  by hardware:")
    for hw, stats in s["by_hardware"].items():
        print(f"    {hw:<24} {stats['count']:>2}x  ${stats['cost_usd']:.6f}")
