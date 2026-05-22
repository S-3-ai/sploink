"""Single-page HTML dashboard for sploink bench results.

Reads every CSV in `bench/results/` (or a directory you pass), aggregates by
strategy on the intersection of completed examples, and renders:

  - Hero: savings percentage (hw_routed vs lpu_only)
  - Bar charts: avg cost, avg F1, avg latency per strategy
  - Per-strategy stats table
  - Run history (one row per CSV)

Single self-contained HTML, no external dependencies, white theme. Matches
the visual language of `python -m sploink.architecture`.

Usage:
    python -m sploink.dashboard
    python -m sploink.dashboard --results-dir bench/results
    python -m sploink.dashboard --out sploink_dashboard.html --no-open
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import webbrowser
from datetime import datetime
from pathlib import Path


STRATEGY_COLORS = {
    "cpu_only":   "#4f46e5",  # indigo — CPU
    "lpu_only":   "#d97706",  # amber — LPU
    "hw_routed":  "#10b981",  # emerald — the sploink thesis
    "all_cloud":  "#dc2626",  # red — frontier baseline
    "edge_routed":"#10b981",  # legacy name
    "ollama_only":"#4f46e5",  # legacy name
}


def _color_for(strategy: str) -> str:
    return STRATEGY_COLORS.get(strategy, "#64748b")


def _load_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _aggregate_intersection(runs: dict[str, list[dict]]) -> tuple[dict[str, dict], set[str]]:
    """Aggregate per-strategy stats on the intersection of example_ids."""
    if not runs:
        return {}, set()
    id_sets = [set(r["example_id"] for r in rows) for rows in runs.values()]
    shared = set.intersection(*id_sets)

    agg = {}
    for strategy, rows in runs.items():
        shared_rows = [r for r in rows if r["example_id"] in shared]
        if not shared_rows:
            agg[strategy] = {"n_shared": 0, "n_total": len(rows), "f1": 0, "em": 0, "cost": 0, "latency": 0, "n_steps": 0}
            continue
        agg[strategy] = {
            "n_shared":  len(shared_rows),
            "n_total":   len(rows),
            "f1":        statistics.mean(float(r["f1"]) for r in shared_rows),
            "em":        statistics.mean(float(r["em"]) for r in shared_rows),
            "cost":      statistics.mean(float(r["cost_usd"]) for r in shared_rows),
            "latency":   statistics.mean(float(r["latency_ms"]) for r in shared_rows),
            "n_steps":   statistics.mean(float(r["n_steps"]) for r in shared_rows),
        }
    return agg, shared


def _file_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "—"


def collect_runs(results_dir: Path) -> tuple[dict[str, list[dict]], list[dict]]:
    """Load every CSV in results_dir. Returns (runs_by_strategy, run_history)."""
    if not results_dir.exists():
        return {}, []
    runs: dict[str, list[dict]] = {}
    history: list[dict] = []
    for csv_path in sorted(results_dir.glob("*.csv")):
        rows = _load_csv(csv_path)
        if not rows:
            continue
        strategy = rows[0].get("strategy", csv_path.stem)
        # If we have multiple files for the same strategy, take the latest one.
        if strategy not in runs or csv_path.stat().st_mtime > Path(
            history[next(i for i, h in enumerate(history) if h["strategy"] == strategy)]["path"]
        ).stat().st_mtime:
            runs[strategy] = rows
        history.append({
            "path": str(csv_path),
            "name": csv_path.name,
            "strategy": strategy,
            "rows": len(rows),
            "mtime": _file_mtime(csv_path),
        })
    return runs, history


def render_html(results_dir: Path) -> str:
    runs, history = collect_runs(results_dir)
    agg, shared = _aggregate_intersection(runs)

    # Compute "headline" savings if both lpu_only and hw_routed exist
    savings = None
    if "lpu_only" in agg and "hw_routed" in agg and agg["lpu_only"]["cost"] > 0:
        c_lpu = agg["lpu_only"]["cost"]
        c_hw = agg["hw_routed"]["cost"]
        savings = {
            "pct": (1 - c_hw / c_lpu) * 100,
            "from": c_lpu,
            "to": c_hw,
            "f1_delta": agg["hw_routed"]["f1"] - agg["lpu_only"]["f1"],
        }

    payload = {
        "results_dir": str(results_dir),
        "aggregates": agg,
        "history": history,
        "n_shared": len(shared),
        "savings": savings,
        "strategy_colors": STRATEGY_COLORS,
        "has_data": bool(agg),
    }
    return _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sploink — Dashboard</title>
<style>
  :root {
    --bg: #ffffff;
    --panel: #f8fafc;
    --text: #0f172a;
    --muted: #64748b;
    --border: #e2e8f0;
    --accent: #3b82f6;
    --success: #10b981;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", sans-serif;
    font-size: 14px;
  }
  header {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    padding: 16px 28px;
    display: flex; align-items: baseline; justify-content: space-between;
  }
  header h1 { font-size: 18px; font-weight: 600; margin: 0; }
  header .subtitle { color: var(--muted); font-size: 13px; }
  main { padding: 24px 28px; max-width: 1400px; margin: 0 auto; }
  .hero {
    background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%);
    border: 1px solid #bbf7d0;
    border-radius: 16px;
    padding: 32px;
    margin-bottom: 24px;
    text-align: center;
  }
  .hero .big-number {
    font-size: 64px;
    font-weight: 700;
    color: var(--success);
    line-height: 1;
    letter-spacing: -0.02em;
  }
  .hero .label { font-size: 14px; color: var(--muted); margin-top: 8px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
  .hero .detail { font-size: 14px; color: var(--text); margin-top: 14px; }
  .hero .detail b { font-family: "SF Mono", Menlo, monospace; }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 20px;
    margin-bottom: 24px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }
  .card h2 {
    font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 16px 0;
  }
  .bar-chart { display: flex; flex-direction: column; gap: 12px; }
  .bar-row { display: flex; flex-direction: column; gap: 4px; }
  .bar-label { display: flex; justify-content: space-between; font-size: 12px; }
  .bar-label .strategy {
    font-family: "SF Mono", Menlo, monospace;
    font-size: 11px;
  }
  .bar-label .value { font-weight: 600; }
  .bar-bg {
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
  }
  .empty-state {
    background: var(--panel);
    border: 1px dashed var(--border);
    border-radius: 12px;
    padding: 48px;
    text-align: center;
    color: var(--muted);
  }
  .empty-state code {
    background: white;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 13px;
    border: 1px solid var(--border);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
  }
  th, td {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }
  th {
    background: var(--panel);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    font-weight: 600;
  }
  td.num {
    font-family: "SF Mono", Menlo, monospace;
    font-size: 12px;
    text-align: right;
  }
  td.strategy-cell { font-weight: 600; }
  .stat-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; vertical-align: middle; }
  .table-wrap { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .table-wrap h2 { margin-top: 0; }
  footer {
    color: var(--muted);
    font-size: 12px;
    padding: 18px 28px 30px;
    text-align: center;
  }
  footer code { background: var(--panel); padding: 2px 6px; border-radius: 4px; }
  .savings-warning {
    background: #fef3c7;
    border: 1px solid #fbbf24;
    color: #78350f;
    padding: 14px 18px;
    border-radius: 8px;
    font-size: 13px;
    margin-bottom: 20px;
  }
  .savings-warning b { color: #92400e; }
  /* viewer switcher — shared between architecture.html + dashboard.html */
  .viewer-switcher {
    display: flex;
    gap: 4px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 4px;
  }
  .viewer-switcher a {
    text-decoration: none;
    font-size: 12px;
    font-weight: 500;
    padding: 6px 14px;
    border-radius: 999px;
    color: var(--muted);
    transition: all 0.15s ease;
  }
  .viewer-switcher a:hover { color: var(--text); }
  .viewer-switcher a.active {
    background: var(--text);
    color: var(--bg);
  }
  .viewer-switcher .docs-link { color: var(--accent); padding: 6px 10px; }
  .viewer-switcher .docs-link:hover { background: transparent; color: var(--accent); }
</style>
</head>
<body>

<header>
  <div>
    <h1>Sploink — bench dashboard</h1>
    <div class="subtitle" id="data-src"></div>
  </div>
  <div style="display:flex; align-items:center; gap:16px;">
    <nav class="viewer-switcher">
      <a href="architecture.html">Architecture</a>
      <a href="dashboard.html" class="active">Dashboard</a>
      <a href="/" class="docs-link">← Docs</a>
    </nav>
    <div class="subtitle" id="shared-meta"></div>
  </div>
</header>

<main>
  <div id="hero-mount"></div>
  <div id="charts-mount"></div>
  <div id="table-mount" style="margin-bottom: 24px;"></div>
  <div id="history-mount"></div>
</main>

<footer>
  Generated by <code>python -m sploink.dashboard</code> · <strong>Re-run that command after each bench</strong> to regenerate this file (the data is baked in at generation time) · No external dependencies
</footer>

<script>
const DATA = __PAYLOAD__;

function fmtUsd(v) {
  if (v === 0) return "$0";
  if (v < 0.00001) return "$" + v.toExponential(2);
  return "$" + v.toFixed(6);
}
function fmtMs(v) { return Math.round(v).toLocaleString() + " ms"; }
function fmtPct(v) { return v.toFixed(1) + "%"; }

document.getElementById("data-src").textContent = "Reading " + DATA.results_dir;
document.getElementById("shared-meta").textContent =
  DATA.has_data ? "intersected on " + DATA.n_shared + " shared examples" : "";

// HERO
const heroEl = document.getElementById("hero-mount");
if (DATA.savings) {
  const s = DATA.savings;
  const qualOk = s.f1_delta > -0.05;
  heroEl.innerHTML = `
    <div class="hero">
      <div class="big-number">${fmtPct(s.pct)}</div>
      <div class="label">cost savings · hw_routed vs lpu_only</div>
      <div class="detail">
        <b>${fmtUsd(s.from)}</b> → <b>${fmtUsd(s.to)}</b> per query
        · F1 ${s.f1_delta >= 0 ? "+" : ""}${s.f1_delta.toFixed(3)}
        ${qualOk ? "✓ quality preserved" : "⚠ quality dropped"}
      </div>
    </div>`;
} else if (!DATA.has_data) {
  heroEl.innerHTML = `
    <div class="empty-state">
      <p>No bench results found in <code>${DATA.results_dir}</code>.</p>
      <p>Run a bench to populate this dashboard:</p>
      <p><code>python -m bench.run --n 30 --graphs parallel_dag --strategy hw_routed</code></p>
      <p style="margin-top: 14px; font-size: 12px;">Then re-run <code>python -m sploink.dashboard</code> to regenerate this file.</p>
    </div>`;
} else {
  const have = Object.keys(DATA.aggregates);
  const need = ["lpu_only", "hw_routed"].filter(s => !have.includes(s));
  heroEl.innerHTML = `
    <div class="savings-warning">
      <b>Savings headline not available yet.</b>
      Measured <b>${have.length}</b> strateg${have.length === 1 ? "y" : "ies"} (<code>${have.join(", ")}</code>),
      but the headline needs both <code>lpu_only</code> AND <code>hw_routed</code> CSVs to compute a cost-reduction ratio.
      Run the missing strateg${need.length === 1 ? "y" : "ies"}:
      <pre style="margin: 8px 0 0 0; background: white; padding: 8px; border-radius: 4px;">${need.map(s => `python -m bench.run --n 30 --graphs parallel_dag --strategy ${s}\npython -m sploink.dashboard   # regenerate after`).join("\n")}</pre>
    </div>`;
}

// BAR CHARTS
function barChart(title, getValue, formatter, options = {}) {
  const aggs = DATA.aggregates;
  const strategies = Object.keys(aggs);
  if (strategies.length === 0) return '';
  const values = strategies.map(s => getValue(aggs[s]));
  const maxVal = Math.max(...values, 0.000001);
  const rows = strategies.map((s, i) => {
    const v = values[i];
    const pct = (v / maxVal) * 100;
    const color = DATA.strategy_colors[s] || "#64748b";
    return `
      <div class="bar-row">
        <div class="bar-label">
          <span class="strategy"><span class="stat-dot" style="background:${color}"></span>${s}</span>
          <span class="value">${formatter(v)}</span>
        </div>
        <div class="bar-bg">
          <div class="bar-fill" style="width:${pct}%; background:${color}"></div>
        </div>
      </div>`;
  }).join("");
  return `
    <div class="card">
      <h2>${title}</h2>
      <div class="bar-chart">${rows}</div>
    </div>`;
}

const chartsEl = document.getElementById("charts-mount");
if (DATA.has_data) {
  chartsEl.className = "grid";
  chartsEl.innerHTML = (
    barChart("Avg cost / query", a => a.cost, fmtUsd) +
    barChart("Avg F1 (quality)", a => a.f1, v => v.toFixed(3)) +
    barChart("Avg latency / query", a => a.latency, fmtMs)
  );
}

// STATS TABLE
const tableEl = document.getElementById("table-mount");
if (DATA.has_data) {
  const rows = Object.entries(DATA.aggregates).map(([s, a]) => `
    <tr>
      <td class="strategy-cell"><span class="stat-dot" style="background:${DATA.strategy_colors[s] || '#64748b'}"></span>${s}</td>
      <td class="num">${a.n_shared} / ${a.n_total}</td>
      <td class="num">${fmtUsd(a.cost)}</td>
      <td class="num">${a.f1.toFixed(3)}</td>
      <td class="num">${a.em.toFixed(3)}</td>
      <td class="num">${fmtMs(a.latency)}</td>
      <td class="num">${a.n_steps.toFixed(1)}</td>
    </tr>`).join("");
  tableEl.innerHTML = `
    <div class="table-wrap">
      <h2>Aggregate stats (on shared examples)</h2>
      <table>
        <thead>
          <tr>
            <th>Strategy</th>
            <th style="text-align:right">Examples</th>
            <th style="text-align:right">Avg cost</th>
            <th style="text-align:right">Avg F1</th>
            <th style="text-align:right">Avg EM</th>
            <th style="text-align:right">Avg latency</th>
            <th style="text-align:right">Avg steps</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// RUN HISTORY
const historyEl = document.getElementById("history-mount");
if (DATA.history.length > 0) {
  const rows = DATA.history.slice().reverse().map(h => `
    <tr>
      <td>${h.name}</td>
      <td>${h.strategy}</td>
      <td class="num">${h.rows}</td>
      <td class="num">${h.mtime}</td>
    </tr>`).join("");
  historyEl.innerHTML = `
    <div class="table-wrap">
      <h2>Run history</h2>
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Strategy</th>
            <th style="text-align:right">Rows</th>
            <th style="text-align:right">Last modified</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results-dir", type=str, default="bench/results")
    p.add_argument("--out", type=str, default="sploink_dashboard.html")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)

    html = render_html(Path(args.results_dir))
    out_path = Path(args.out).resolve()
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)
    if not args.no_open:
        webbrowser.open(out_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
