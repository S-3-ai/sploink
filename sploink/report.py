"""Self-contained static HTML report from a JSONL trace.

Usage:
    python -m sploink.report                # latest trace in ~/.sploink/traces/
    python -m sploink.report path/to.jsonl  # specific file
    python -m sploink.report --no-open      # do not auto-open in browser
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from collections import defaultdict
from pathlib import Path


HARDWARE_COLORS = {
    "frontier_api": "#7B61FF",
    "lpu": "#00C2A8",
    "gpu": "#FF7A59",
    "cpu": "#A0A8B8",
    "unknown": "#555B6A",
}


def _default_trace_dir() -> Path:
    return Path(os.environ.get("SPLOINK_TRACE_DIR", Path.home() / ".sploink" / "traces"))


def _latest_trace() -> Path | None:
    d = _default_trace_dir()
    if not d.exists():
        return None
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _aggregate(records: list[dict]) -> dict:
    by_step: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost_usd": 0.0, "latency_ms": 0.0})
    by_hw: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost_usd": 0.0})
    by_substrate: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost_usd": 0.0})

    for r in records:
        s = by_step[r["step_label"]]
        s["count"] += 1
        s["cost_usd"] += r["cost_usd"]
        s["latency_ms"] += r["latency_ms"]

        hw = r.get("hardware_type") or "unknown"
        by_hw[hw]["count"] += 1
        by_hw[hw]["cost_usd"] += r["cost_usd"]

        sub = r.get("substrate") or "unknown"
        by_substrate[sub]["count"] += 1
        by_substrate[sub]["cost_usd"] += r["cost_usd"]

    return {
        "workflow_id": records[0]["workflow_id"] if records else "(empty)",
        "calls": len(records),
        "tokens_in": sum(r.get("tokens_in") or 0 for r in records),
        "tokens_out": sum(r.get("tokens_out") or 0 for r in records),
        "cost_usd": sum(r["cost_usd"] for r in records),
        "latency_ms": sum(r["latency_ms"] for r in records),
        "by_step": dict(by_step),
        "by_hardware": dict(by_hw),
        "by_substrate": dict(by_substrate),
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>sploink trace — __WORKFLOW_ID__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0e1116;
    --panel: #161b22;
    --text: #e6edf3;
    --muted: #8b949e;
    --border: #30363d;
    --accent: #7ee787;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 32px; }
  h1 { font-weight: 600; font-size: 18px; margin: 0 0 4px; letter-spacing: -0.01em; }
  h2 { font-weight: 500; font-size: 13px; margin: 0 0 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .wid { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  .totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 20px 0 32px; }
  .stat { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
  .stat .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
  .stat .value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat .value.accent { color: var(--accent); }
  .charts { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 32px; }
  .charts > .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .timeline-panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 32px; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  thead th { background: #1d242c; text-align: left; padding: 10px 12px; font-weight: 500; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; }
  tbody td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: rgba(255,255,255,0.03); }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  canvas { max-height: 280px; }
</style>
</head>
<body>
  <h1>sploink trace</h1>
  <div class="wid">workflow __WORKFLOW_ID__</div>

  <div class="totals">
    <div class="stat"><div class="label">calls</div><div class="value">__CALLS__</div></div>
    <div class="stat"><div class="label">total cost</div><div class="value accent">$__COST__</div></div>
    <div class="stat"><div class="label">total latency</div><div class="value">__LATENCY__ ms</div></div>
    <div class="stat"><div class="label">tokens in</div><div class="value">__TOKENS_IN__</div></div>
    <div class="stat"><div class="label">tokens out</div><div class="value">__TOKENS_OUT__</div></div>
  </div>

  <div class="charts">
    <div class="panel">
      <h2>cost by step type</h2>
      <canvas id="byStep"></canvas>
    </div>
    <div class="panel">
      <h2>cost by hardware</h2>
      <canvas id="byHardware"></canvas>
    </div>
  </div>

  <div class="timeline-panel">
    <h2>per-call latency</h2>
    <canvas id="timeline"></canvas>
  </div>

  <h2 style="margin-top:32px;">all calls</h2>
  <table id="detail">
    <thead><tr>
      <th>#</th><th>step</th><th>substrate</th><th>hardware</th><th>model</th>
      <th>tokens in</th><th>tokens out</th><th>latency (ms)</th><th>cost ($)</th>
    </tr></thead>
    <tbody></tbody>
  </table>

<script>
const DATA = __DATA_JSON__;
const HW_COLORS = __HW_COLORS_JSON__;

// cost by step
new Chart(document.getElementById('byStep'), {
  type: 'bar',
  data: {
    labels: Object.keys(DATA.agg.by_step),
    datasets: [{
      data: Object.values(DATA.agg.by_step).map(s => s.cost_usd),
      backgroundColor: '#7ee787',
      borderRadius: 4,
    }],
  },
  options: {
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#8b949e' }, grid: { display: false } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } },
    },
  },
});

// cost by hardware
const hwLabels = Object.keys(DATA.agg.by_hardware);
new Chart(document.getElementById('byHardware'), {
  type: 'doughnut',
  data: {
    labels: hwLabels,
    datasets: [{
      data: hwLabels.map(k => DATA.agg.by_hardware[k].cost_usd),
      backgroundColor: hwLabels.map(k => HW_COLORS[k] || '#555'),
      borderColor: '#0e1116',
      borderWidth: 2,
    }],
  },
  options: {
    plugins: { legend: { position: 'bottom', labels: { color: '#e6edf3' } } },
  },
});

// per-call latency
const records = DATA.records;
new Chart(document.getElementById('timeline'), {
  type: 'bar',
  data: {
    labels: records.map((r, i) => `${i}. ${r.step_label}`),
    datasets: [{
      label: 'latency (ms)',
      data: records.map(r => r.latency_ms),
      backgroundColor: records.map(r => HW_COLORS[r.hardware_type || 'unknown'] || '#555'),
      borderRadius: 4,
    }],
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#8b949e' }, grid: { color: '#30363d' } },
      y: { ticks: { color: '#8b949e' }, grid: { display: false } },
    },
  },
});

// detail table
const tbody = document.querySelector('#detail tbody');
records.forEach((r, i) => {
  const tr = document.createElement('tr');
  const hwColor = HW_COLORS[r.hardware_type || 'unknown'] || '#555';
  tr.innerHTML = `
    <td>${i}</td>
    <td>${r.step_label}</td>
    <td>${r.substrate || ''}</td>
    <td><span class="pill" style="background:${hwColor}20;color:${hwColor}">${r.hardware_type || ''}</span></td>
    <td class="mono">${r.model || ''}</td>
    <td>${r.tokens_in ?? ''}</td>
    <td>${r.tokens_out ?? ''}</td>
    <td>${r.latency_ms.toFixed(1)}</td>
    <td>$${r.cost_usd.toFixed(6)}</td>
  `;
  tbody.appendChild(tr);
});
</script>
</body>
</html>
"""


def render(records: list[dict], agg: dict) -> str:
    data_json = json.dumps({"records": records, "agg": agg})
    hw_colors_json = json.dumps(HARDWARE_COLORS)
    return (
        HTML_TEMPLATE
        .replace("__WORKFLOW_ID__", agg["workflow_id"])
        .replace("__CALLS__", str(agg["calls"]))
        .replace("__COST__", f"{agg['cost_usd']:.6f}")
        .replace("__LATENCY__", f"{agg['latency_ms']:.0f}")
        .replace("__TOKENS_IN__", f"{agg['tokens_in']:,}")
        .replace("__TOKENS_OUT__", f"{agg['tokens_out']:,}")
        .replace("__DATA_JSON__", data_json)
        .replace("__HW_COLORS_JSON__", hw_colors_json)
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a sploink JSONL trace as a static HTML report.")
    p.add_argument("path", nargs="?", help="Path to a .jsonl trace (default: latest in ~/.sploink/traces/)")
    p.add_argument("-o", "--output", default=None, help="Output HTML path (default: alongside the input)")
    p.add_argument("--no-open", action="store_true", help="Do not auto-open the report in a browser")
    args = p.parse_args(argv)

    src = Path(args.path) if args.path else _latest_trace()
    if src is None or not src.exists():
        print(f"No trace file found. Run an example first to generate one in {_default_trace_dir()}.", file=sys.stderr)
        return 1

    records = _load(src)
    if not records:
        print(f"Trace {src} is empty.", file=sys.stderr)
        return 1

    agg = _aggregate(records)
    html = render(records, agg)

    out = Path(args.output) if args.output else src.with_suffix(".html")
    out.write_text(html)
    print(f"wrote {out}  ({len(records)} calls, ${agg['cost_usd']:.6f}, {agg['latency_ms']:.0f} ms)")

    if not args.no_open:
        webbrowser.open(out.as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
