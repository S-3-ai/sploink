"""Bench driver — graph-structure experiment.

Holds routing strategy + model + compute pool + dataset constant; varies the
execution graph topology across runs. Scores each graph variant against
HotpotQA gold answers and emits a per-variant comparison table + CSV.

Usage:
    uv run python -m bench.run --n 5                       # smoke test
    uv run python -m bench.run --n 100                     # full bench
    uv run python -m bench.run --graphs linear,parallel_dag
    uv run python -m bench.run --strategy cpu_only --graphs linear,parallel_dag,decomposed

The default `--strategy hw_routed` is the sploink thesis: cheap steps run on
CPU (Ollama, free), the reasoning step escalates to LPU (Groq, low-latency).
Other strategies (cpu_only, lpu_only) are uniform-hardware baselines that
isolate per-architecture cost/latency/quality.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from bench import dataset as dataset_mod
from bench import score as score_mod
from bench.graphs import GRAPHS, execute
from bench.strategies import STRATEGIES


@dataclass
class PerRun:
    graph: str
    strategy: str
    example_id: str
    question: str
    gold: str
    pred: str
    f1: float
    em: float
    cost_usd: float
    latency_ms: float
    n_steps: int


@dataclass
class Aggregate:
    graph: str
    n: int
    avg_cost: float
    avg_latency_ms: float
    p95_latency_ms: float
    avg_f1: float
    avg_em: float
    avg_n_steps: float


def _aggregate(runs: list[PerRun], graph: str) -> Aggregate:
    subset = [r for r in runs if r.graph == graph]
    if not subset:
        return Aggregate(graph, 0, 0, 0, 0, 0, 0, 0)
    latencies = sorted(r.latency_ms for r in subset)
    p95 = latencies[max(0, int(0.95 * len(latencies)) - 1)] if latencies else 0.0
    return Aggregate(
        graph=graph,
        n=len(subset),
        avg_cost=statistics.mean(r.cost_usd for r in subset),
        avg_latency_ms=statistics.mean(r.latency_ms for r in subset),
        p95_latency_ms=p95,
        avg_f1=statistics.mean(r.f1 for r in subset),
        avg_em=statistics.mean(r.em for r in subset),
        avg_n_steps=statistics.mean(r.n_steps for r in subset),
    )


def _print_table(aggs: list[Aggregate], baseline_graph: str) -> None:
    if not aggs:
        print("(no results)")
        return
    print()
    print(
        f"  {'graph':<14} {'n':>4} {'avg_cost':>12} {'avg_lat_ms':>12} "
        f"{'p95_lat_ms':>12} {'avg_f1':>8} {'avg_em':>8} {'avg_steps':>10}"
    )
    print(
        f"  {'-'*14:<14} {'----':>4} {'-'*12:>12} {'-'*12:>12} "
        f"{'-'*12:>12} {'-'*8:>8} {'-'*8:>8} {'-'*10:>10}"
    )
    for a in aggs:
        print(
            f"  {a.graph:<14} {a.n:>4} "
            f"${a.avg_cost:>11.6f} "
            f"{a.avg_latency_ms:>12.0f} "
            f"{a.p95_latency_ms:>12.0f} "
            f"{a.avg_f1:>8.3f} "
            f"{a.avg_em:>8.3f} "
            f"{a.avg_n_steps:>10.1f}"
        )

    # Deltas vs the baseline graph (default: linear).
    baseline = next((a for a in aggs if a.graph == baseline_graph), None)
    if baseline is None:
        return
    print()
    print(f"  deltas vs {baseline_graph}:")
    for a in aggs:
        if a.graph == baseline_graph:
            continue
        cost_delta = (
            (1 - (a.avg_cost / baseline.avg_cost)) * 100
            if baseline.avg_cost > 0
            else 0.0
        )
        latency_delta = (
            (1 - (a.avg_latency_ms / baseline.avg_latency_ms)) * 100
            if baseline.avg_latency_ms > 0
            else 0.0
        )
        f1_delta = a.avg_f1 - baseline.avg_f1
        print(
            f"    {a.graph:<14}  "
            f"cost {'↓' if cost_delta > 0 else '↑'}{abs(cost_delta):>5.1f}%   "
            f"latency {'↓' if latency_delta > 0 else '↑'}{abs(latency_delta):>5.1f}%   "
            f"F1 Δ{f1_delta:+.3f}"
        )


def _write_csv(runs: list[PerRun], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["graph", "strategy", "example_id", "question", "gold", "pred",
             "f1", "em", "cost_usd", "latency_ms", "n_steps"]
        )
        for r in runs:
            w.writerow([
                r.graph, r.strategy, r.example_id, r.question, r.gold, r.pred,
                f"{r.f1:.4f}", f"{r.em:.1f}", f"{r.cost_usd:.6f}",
                f"{r.latency_ms:.1f}", r.n_steps,
            ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=5, help="examples per graph variant")
    p.add_argument(
        "--graphs",
        type=str,
        default="linear,parallel_dag,decomposed",
        help="comma-separated subset of: " + ",".join(GRAPHS.keys()),
    )
    p.add_argument(
        "--strategy",
        type=str,
        default="hw_routed",
        help="routing strategy held constant across graphs. one of: "
        + ",".join(STRATEGIES.keys()),
    )
    p.add_argument(
        "--baseline",
        type=str,
        default="linear",
        help="graph to use as the deltas baseline in the printed table",
    )
    p.add_argument("--out", type=str, default="bench/results/latest.csv")
    args = p.parse_args(argv)

    load_dotenv()

    graphs = [g.strip() for g in args.graphs.split(",") if g.strip()]
    for g in graphs:
        if g not in GRAPHS:
            print(f"unknown graph: {g}", file=sys.stderr)
            return 2

    if args.strategy not in STRATEGIES:
        print(f"unknown strategy: {args.strategy}", file=sys.stderr)
        return 2

    runner = STRATEGIES[args.strategy]
    print(f"loading {args.n} HotpotQA dev examples...")
    examples = dataset_mod.load(n=args.n)
    print(f"  loaded {len(examples)}")
    print(f"routing strategy (constant): {args.strategy}")
    print(f"graph variants:             {graphs}")

    all_runs: list[PerRun] = []

    for graph_name in graphs:
        graph = GRAPHS[graph_name]
        print(f"\n=== graph: {graph_name} ===")
        for i, ex in enumerate(examples):
            t0 = time.perf_counter()
            try:
                run_result = execute(graph, ex, runner)
            except Exception as e:
                print(f"  [{i+1}/{len(examples)}] FAILED: {e}", file=sys.stderr)
                continue
            wall_ms = (time.perf_counter() - t0) * 1000
            f1 = score_mod.f1(run_result.answer, ex.answer)
            em = score_mod.exact_match(run_result.answer, ex.answer)
            print(
                f"  [{i+1}/{len(examples)}] f1={f1:.2f}  ${run_result.total_cost:.6f}  "
                f"{wall_ms:.0f}ms  steps={len(run_result.steps)}  "
                f"pred={run_result.answer[:40]!r} gold={ex.answer[:30]!r}"
            )
            all_runs.append(PerRun(
                graph=graph_name,
                strategy=args.strategy,
                example_id=ex.id,
                question=ex.question,
                gold=ex.answer,
                pred=run_result.answer,
                f1=f1,
                em=em,
                cost_usd=run_result.total_cost,
                latency_ms=wall_ms,
                n_steps=len(run_result.steps),
            ))

    aggs = [_aggregate(all_runs, g) for g in graphs]
    _print_table(aggs, baseline_graph=args.baseline)

    out_path = Path(args.out)
    _write_csv(all_runs, out_path)
    print(f"\nwrote {out_path}  ({len(all_runs)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
