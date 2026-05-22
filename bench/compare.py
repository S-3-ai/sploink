"""Fair apples-to-apples comparison across multiple bench result CSVs.

Reads N CSVs produced by bench/run.py, intersects them on `example_id`, and
reports per-strategy averages on the shared subset — so F1 differences reflect
the routing strategy, not which subset of examples happened to complete.

Usage:
    python -m bench.compare bench/results/v2_cpu.csv bench/results/v2_lpu.csv bench/results/v2_hw.csv
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path


def load(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2

    runs: dict[str, list[dict]] = {}
    for path_str in args:
        p = Path(path_str)
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            return 1
        rows = load(p)
        if not rows:
            print(f"{p} is empty", file=sys.stderr)
            continue
        # Use the `strategy` column from the CSV as the label.
        strategy = rows[0].get("strategy", p.stem)
        runs[strategy] = rows

    if len(runs) < 2:
        print("need at least 2 CSVs to compare", file=sys.stderr)
        return 2

    # Intersect on example_id.
    id_sets = [set(r["example_id"] for r in rows) for rows in runs.values()]
    shared_ids = set.intersection(*id_sets)
    union_ids = set.union(*id_sets)

    print()
    print(f"  {'strategy':<14} {'completed':>10} {'on_shared':>10} "
          f"{'avg_f1':>8} {'avg_em':>8} {'avg_cost':>12} {'avg_lat_ms':>12}")
    print(f"  {'-'*14:<14} {'-'*10:>10} {'-'*10:>10} "
          f"{'-'*8:>8} {'-'*8:>8} {'-'*12:>12} {'-'*12:>12}")

    aggregates = {}
    for strategy, rows in runs.items():
        shared_rows = [r for r in rows if r["example_id"] in shared_ids]
        f1s = [float(r["f1"]) for r in shared_rows]
        ems = [float(r["em"]) for r in shared_rows]
        costs = [float(r["cost_usd"]) for r in shared_rows]
        lats = [float(r["latency_ms"]) for r in shared_rows]
        aggregates[strategy] = {
            "f1": statistics.mean(f1s) if f1s else 0,
            "em": statistics.mean(ems) if ems else 0,
            "cost": statistics.mean(costs) if costs else 0,
            "latency": statistics.mean(lats) if lats else 0,
        }
        print(
            f"  {strategy:<14} {len(rows):>10} {len(shared_rows):>10} "
            f"{aggregates[strategy]['f1']:>8.3f} "
            f"{aggregates[strategy]['em']:>8.3f} "
            f"${aggregates[strategy]['cost']:>11.6f} "
            f"{aggregates[strategy]['latency']:>12.0f}"
        )

    print()
    print(f"  shared examples: {len(shared_ids)} of {len(union_ids)} union "
          f"(intersection on example_id across runs)")

    # Deltas vs cpu_only (or first strategy) baseline.
    baseline_key = "cpu_only" if "cpu_only" in aggregates else next(iter(aggregates))
    baseline = aggregates[baseline_key]
    if baseline["cost"] > 0:
        print(f"\n  deltas vs {baseline_key}:")
        for strategy, agg in aggregates.items():
            if strategy == baseline_key:
                continue
            f1_delta = agg["f1"] - baseline["f1"]
            cost_ratio = agg["cost"] / baseline["cost"] if baseline["cost"] else float("inf")
            lat_ratio = agg["latency"] / baseline["latency"] if baseline["latency"] else float("inf")
            print(f"    {strategy:<14}  F1 Δ{f1_delta:+.3f}   "
                  f"cost {cost_ratio:.2f}×   latency {lat_ratio:.2f}×")

    # Also against lpu_only if both exist (the "all cloud" comparison)
    if "lpu_only" in aggregates and "hw_routed" in aggregates:
        a = aggregates["lpu_only"]
        b = aggregates["hw_routed"]
        if a["cost"] > 0:
            savings = (1 - b["cost"] / a["cost"]) * 100
            print(f"\n  hw_routed vs lpu_only on shared examples:")
            print(f"    cost savings: {savings:.1f}% (${a['cost']:.6f} → ${b['cost']:.6f} per query)")
            print(f"    F1 delta:     {b['f1'] - a['f1']:+.3f}")
            print(f"    latency:      {b['latency']/a['latency']:.2f}× (hw_routed / lpu_only)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
