"""Graphical canvas view of a sploink JSONL trace.

Self-contained HTML: Cytoscape.js + Cola.js (continuous force-directed physics)
via CDN. Each call is a node — colored AND shaped by hardware type, with the
substrate name visible underneath. Drag a node and the rest float in response.

Includes:
  - Cost arbitrage panel: compares actual routed cost vs. a baseline of running
    every step on a single frontier model (default: claude-sonnet-4-6).
  - Replay/rewind: scrub or play through the workflow step by step.

Usage:
    python -m sploink.canvas                # latest trace
    python -m sploink.canvas path/to.jsonl  # specific file
    python -m sploink.canvas --baseline claude-opus-4-7
    python -m sploink.canvas --no-open
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

from sploink.pricing import ANTHROPIC


# Light-theme palette tuned for white background.
HARDWARE_COLORS = {
    "frontier_api": "#6f42c1",
    "lpu": "#0a7f6a",
    "gpu": "#d1731e",
    "cpu": "#57606a",
    "unknown": "#8c959f",
}

HARDWARE_SHAPES = {
    "frontier_api": "ellipse",
    "lpu": "hexagon",
    "gpu": "round-rectangle",
    "cpu": "diamond",
    "unknown": "ellipse",
}

DEFAULT_BASELINE_MODEL = "claude-sonnet-4-6"


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


def _compute_savings(records: list[dict], baseline_model: str) -> dict:
    """For each record, what would it have cost if every step ran on baseline_model?

    Returns a dict containing per-record baseline_cost and aggregate totals.
    """
    rates = ANTHROPIC.get(baseline_model)
    if rates is None:
        # try prefix match
        for k, v in ANTHROPIC.items():
            if baseline_model.startswith(k) or k.startswith(baseline_model):
                rates = v
                break
    if rates is None:
        rates = (3.00, 15.00)  # safe Sonnet-tier default

    in_rate, out_rate = rates

    enriched = []
    baseline_total = 0.0
    actual_total = 0.0
    for r in records:
        ti = r.get("tokens_in") or 0
        to = r.get("tokens_out") or 0
        baseline_cost = (ti / 1_000_000) * in_rate + (to / 1_000_000) * out_rate
        enriched.append({**r, "baseline_cost_usd": baseline_cost})
        baseline_total += baseline_cost
        actual_total += r.get("cost_usd", 0.0)

    saved = baseline_total - actual_total
    pct = (saved / baseline_total * 100) if baseline_total > 0 else 0.0

    return {
        "baseline_model": baseline_model,
        "baseline_in_rate": in_rate,
        "baseline_out_rate": out_rate,
        "baseline_total": baseline_total,
        "actual_total": actual_total,
        "saved": saved,
        "saved_pct": pct,
        "records": enriched,
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>sploink canvas — __WORKFLOW_ID__</title>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/webcola@3.4.0/WebCola/cola.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-cola@2.5.1/cytoscape-cola.min.js"></script>
<style>
  :root {
    --bg: #ffffff;
    --grid: #eef0f3;
    --panel: #ffffff;
    --panel-overlay: rgba(255,255,255,0.94);
    --text: #1f2328;
    --muted: #6e7781;
    --border: #d0d7de;
    --shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
    --accent: #1a7f37;
    --accent-strong: #137433;
    --warn: #bf6f00;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; overflow: hidden; }
  #wrap { position: relative; width: 100%; height: 100vh; }
  #cy { width: 100%; height: 100%;
    background-color: var(--bg);
    background-image:
      linear-gradient(var(--grid) 1px, transparent 1px),
      linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 40px 40px;
  }
  .floater { background: var(--panel-overlay); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); backdrop-filter: blur(6px); }

  #header { position: absolute; top: 16px; left: 16px; z-index: 10; padding: 12px 16px; }
  #header h1 { margin: 0; font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
  #header .wid { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; margin-top: 2px; }
  #header .totals { margin-top: 8px; display: flex; gap: 14px; font-size: 12px; }
  #header .totals .k { color: var(--muted); margin-right: 4px; }
  #header .totals .accent { color: var(--accent); font-weight: 600; }

  #savings-badge { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); z-index: 10; padding: 10px 18px; cursor: pointer; display: flex; align-items: center; gap: 14px; user-select: none; transition: box-shadow 0.15s ease; }
  #savings-badge:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.08); }
  #savings-badge .label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); font-weight: 600; }
  #savings-badge .figure { font-size: 22px; font-weight: 700; color: var(--accent-strong); font-variant-numeric: tabular-nums; }
  #savings-badge .pct { font-size: 13px; color: var(--accent); font-weight: 600; }
  #savings-badge .chev { color: var(--muted); font-size: 14px; }

  #savings-panel { position: absolute; top: 70px; left: 50%; transform: translateX(-50%); z-index: 11; width: 460px; padding: 18px 20px; display: none; }
  #savings-panel.open { display: block; }
  #savings-panel h2 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
  #savings-panel .sub { color: var(--muted); font-size: 11px; margin-bottom: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  #savings-panel .big-numbers { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  #savings-panel .big-numbers .cell { background: #f6f8fa; border-radius: 6px; padding: 10px 12px; }
  #savings-panel .big-numbers .k { font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); font-weight: 600; }
  #savings-panel .big-numbers .v { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 3px; }
  #savings-panel .big-numbers .v.savings { color: var(--accent-strong); }
  #savings-panel table { width: 100%; border-collapse: collapse; font-size: 12px; }
  #savings-panel th { text-align: left; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500; padding: 4px 6px; border-bottom: 1px solid var(--border); }
  #savings-panel th.r, #savings-panel td.r { text-align: right; }
  #savings-panel td { padding: 6px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  #savings-panel tr:last-child td { border-bottom: none; }
  #savings-panel .saved-pos { color: var(--accent-strong); font-weight: 600; }
  #savings-panel .saved-zero { color: var(--muted); }
  #savings-panel .close { float: right; cursor: pointer; color: var(--muted); border: none; background: none; font-size: 16px; line-height: 1; padding: 0; }

  #legend { position: absolute; top: 16px; right: 16px; z-index: 10; padding: 12px 14px; }
  #legend h2 { margin: 0 0 8px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
  #legend .item { display: flex; align-items: center; gap: 10px; margin: 6px 0; font-size: 12px; }
  #legend .glyph { width: 14px; height: 14px; display: inline-block; flex-shrink: 0; }
  #legend .glyph.ellipse { border-radius: 50%; }
  #legend .glyph.hexagon { clip-path: polygon(25% 5%, 75% 5%, 100% 50%, 75% 95%, 25% 95%, 0% 50%); }
  #legend .glyph.round-rectangle { border-radius: 4px; }
  #legend .glyph.diamond { transform: rotate(45deg); }

  #panel { position: absolute; bottom: 90px; right: 16px; z-index: 10; width: 320px; max-height: 60vh; overflow: auto; padding: 14px 16px; display: none; }
  #panel h2 { margin: 0 0 8px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  #panel .row { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  #panel .row:last-child { border-bottom: none; }
  #panel .k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  #panel .v { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; text-align: right; }
  #panel .close { float: right; cursor: pointer; color: var(--muted); border: none; background: none; font-size: 16px; line-height: 1; padding: 0; }

  #controls { position: absolute; bottom: 16px; left: 16px; z-index: 10; padding: 6px; display: flex; gap: 4px; }
  #controls button { background: transparent; color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
  #controls button:hover { background: #f6f8fa; }
  #controls button.active { background: var(--text); color: white; border-color: var(--text); }

  #replay { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%); z-index: 10; padding: 8px 14px; display: flex; align-items: center; gap: 12px; }
  #replay .btn { background: transparent; border: 1px solid var(--border); color: var(--text); border-radius: 6px; width: 30px; height: 28px; cursor: pointer; font-size: 13px; display: flex; align-items: center; justify-content: center; }
  #replay .btn:hover { background: #f6f8fa; }
  #replay .scrub { width: 260px; }
  #replay .counter { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); min-width: 60px; text-align: right; }
</style>
</head>
<body>
<div id="wrap">
  <div id="header" class="floater">
    <h1>sploink canvas</h1>
    <div class="wid">workflow __WORKFLOW_ID__</div>
    <div class="totals">
      <div><span class="k">calls</span><span>__CALLS__</span></div>
      <div><span class="k">routed</span><span class="accent">$__COST__</span></div>
      <div><span class="k">latency</span><span>__LATENCY__ms</span></div>
    </div>
  </div>

  <div id="savings-badge" class="floater" onclick="toggleSavings()">
    <div>
      <div class="label">cost arbitrage</div>
      <div><span class="figure">+$__SAVED__</span> <span class="pct">__SAVED_PCT__% saved</span></div>
    </div>
    <span class="chev">▾</span>
  </div>

  <div id="savings-panel" class="floater">
    <button class="close" onclick="toggleSavings()">×</button>
    <h2>cost arbitrage</h2>
    <div class="sub">vs. baseline: every step on <strong>__BASELINE_MODEL__</strong> ($__BASELINE_IN__/M in, $__BASELINE_OUT__/M out)</div>
    <div class="big-numbers">
      <div class="cell"><div class="k">baseline</div><div class="v">$__BASELINE_TOTAL__</div></div>
      <div class="cell"><div class="k">routed (actual)</div><div class="v">$__COST__</div></div>
      <div class="cell"><div class="k">saved</div><div class="v savings">+$__SAVED__</div></div>
    </div>
    <table>
      <thead><tr>
        <th>#</th><th>step</th><th>substrate</th>
        <th class="r">baseline</th><th class="r">actual</th><th class="r">saved</th>
      </tr></thead>
      <tbody id="savings-rows"></tbody>
    </table>
  </div>

  <div id="legend" class="floater">
    <h2>compute substrate</h2>
    <div id="legendItems"></div>
  </div>

  <div id="cy"></div>

  <div id="controls" class="floater">
    <button onclick="cy.fit(undefined, 60)">fit</button>
    <button onclick="cy.zoom(cy.zoom() * 1.25)">+</button>
    <button onclick="cy.zoom(cy.zoom() / 1.25)">−</button>
    <button id="physicsToggle" class="active" onclick="togglePhysics()">physics</button>
  </div>

  <div id="replay" class="floater">
    <button class="btn" onclick="setStep(-1)" title="show all">⤒</button>
    <button class="btn" onclick="stepBy(-1)" title="step back">◀</button>
    <button class="btn" id="playBtn" onclick="togglePlay()" title="play / pause">▶</button>
    <button class="btn" onclick="stepBy(1)" title="step forward">▶|</button>
    <input class="scrub" type="range" id="scrub" min="-1" max="0" step="1" value="-1">
    <span class="counter" id="counter">all</span>
  </div>

  <div id="panel" class="floater">
    <button class="close" onclick="document.getElementById('panel').style.display='none'">×</button>
    <h2>call detail</h2>
    <div id="panelBody"></div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
const HW_COLORS = __HW_COLORS_JSON__;
const HW_SHAPES = __HW_SHAPES_JSON__;

const records = DATA.records;
const N = records.length;
const maxCost = Math.max(...records.map(r => r.cost_usd), 1e-12);

function nodeSize(cost) {
  return 56 + 72 * Math.sqrt(cost / maxCost);
}

const nodes = records.map((r, i) => ({
  data: {
    id: String(i),
    label: `${r.step_label}`,
    sublabel: `${r.substrate || '?'} · ${r.hardware_type || '?'}`,
    hw: r.hardware_type || 'unknown',
    shape: HW_SHAPES[r.hardware_type || 'unknown'] || 'ellipse',
    record: r,
    size: nodeSize(r.cost_usd),
    stepIndex: i,
  },
}));

const edges = records.slice(1).map((r, i) => ({
  data: { id: `e${i}`, source: String(i), target: String(i + 1), targetStep: i + 1 },
}));

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements: { nodes, edges },
  wheelSensitivity: 0.2,
  style: [
    {
      selector: 'node',
      style: {
        'background-color': ele => HW_COLORS[ele.data('hw')] || '#888',
        'background-opacity': 0.92,
        'shape': ele => ele.data('shape'),
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'color': '#ffffff',
        'font-size': 13,
        'font-weight': 600,
        'width': 'data(size)',
        'height': 'data(size)',
        'border-width': 0,
        'opacity': 1,
        'transition-property': 'opacity, border-width, border-color',
        'transition-duration': '180ms',
      },
    },
    {
      selector: 'node.future',
      style: { 'opacity': 0.12 },
    },
    {
      selector: 'node.current',
      style: {
        'border-width': 4,
        'border-color': '#1a7f37',
        'border-opacity': 1,
      },
    },
    {
      selector: 'node:selected',
      style: { 'border-width': 3, 'border-color': '#1f2328', 'border-opacity': 1 },
    },
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#c8d0d8',
        'target-arrow-color': '#c8d0d8',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'opacity': 0.9,
        'transition-property': 'opacity',
        'transition-duration': '180ms',
      },
    },
    {
      selector: 'edge.future',
      style: { 'opacity': 0.1 },
    },
  ],
});

// HTML overlay for sublabels (substrate · hardware) under each node
const overlay = document.createElement('div');
overlay.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:5;';
document.getElementById('cy').appendChild(overlay);

const sublabelEls = new Map();
function syncSublabels() {
  cy.nodes().forEach(node => {
    const id = node.id();
    const pos = node.renderedPosition();
    const r = node.renderedHeight() / 2;
    let el = sublabelEls.get(id);
    if (!el) {
      el = document.createElement('div');
      el.style.cssText = 'position:absolute;transform:translate(-50%,0);background:rgba(255,255,255,0.85);border:1px solid #d0d7de;border-radius:4px;padding:1px 6px;font-size:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#1f2328;white-space:nowrap;transition:opacity 180ms;';
      overlay.appendChild(el);
      sublabelEls.set(id, el);
    }
    el.textContent = node.data('sublabel');
    el.style.left = pos.x + 'px';
    el.style.top = (pos.y + r + 6) + 'px';
    el.style.opacity = node.hasClass('future') ? '0.15' : '1';
  });
}

// --- continuous force-directed layout (Obsidian-style) ---
let layout = null;
let physicsOn = true;

function startPhysics() {
  if (layout) layout.stop();
  layout = cy.layout({
    name: 'cola',
    infinite: true,
    fit: false,
    animate: true,
    refresh: 1,
    edgeLength: 220,
    nodeSpacing: 30,
    randomize: false,
    avoidOverlap: true,
    handleDisconnected: true,
  });
  layout.run();
}

function stopPhysics() {
  if (layout) { layout.stop(); layout = null; }
}

function togglePhysics() {
  physicsOn = !physicsOn;
  const btn = document.getElementById('physicsToggle');
  if (physicsOn) { startPhysics(); btn.classList.add('active'); }
  else { stopPhysics(); btn.classList.remove('active'); }
}

startPhysics();
cy.on('render pan zoom position', syncSublabels);
setTimeout(() => { cy.fit(undefined, 80); syncSublabels(); }, 300);

// --- detail panel on click ---
cy.on('tap', 'node', evt => {
  const r = evt.target.data('record');
  const body = document.getElementById('panelBody');
  const rows = [
    ['step', r.step_label],
    ['substrate', r.substrate || '—'],
    ['hardware', r.hardware_type || '—'],
    ['model', r.model || '—'],
    ['tokens in', r.tokens_in ?? '—'],
    ['tokens out', r.tokens_out ?? '—'],
    ['latency', `${r.latency_ms.toFixed(2)} ms`],
    ['cost', `$${r.cost_usd.toFixed(8)}`],
    ['baseline cost', `$${(r.baseline_cost_usd || 0).toFixed(8)}`],
    ['savings', `$${((r.baseline_cost_usd || 0) - r.cost_usd).toFixed(8)}`],
    ['call_id', r.call_id],
  ];
  body.innerHTML = rows.map(([k, v]) =>
    `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`
  ).join('');
  document.getElementById('panel').style.display = 'block';
});

cy.on('tap', evt => {
  if (evt.target === cy) {
    document.getElementById('panel').style.display = 'none';
  }
});

// --- legend ---
const usedHw = [...new Set(records.map(r => r.hardware_type || 'unknown'))];
const HW_DESCRIPTIONS = {
  frontier_api: 'frontier API (closed)',
  lpu: 'LPU (e.g. Groq)',
  gpu: 'NVIDIA GPU',
  cpu: 'CPU',
  unknown: 'unknown',
};
document.getElementById('legendItems').innerHTML = usedHw.map(hw => `
  <div class="item">
    <span class="glyph ${HW_SHAPES[hw] || 'ellipse'}" style="background:${HW_COLORS[hw] || '#888'}"></span>
    ${HW_DESCRIPTIONS[hw] || hw}
  </div>`).join('');

// --- savings panel content ---
function renderSavingsRows() {
  const rows = records.map((r, i) => {
    const baseline = r.baseline_cost_usd || 0;
    const saved = baseline - r.cost_usd;
    const savedCls = saved > 1e-9 ? 'saved-pos' : 'saved-zero';
    return `<tr>
      <td>${i}</td>
      <td>${r.step_label}</td>
      <td>${r.substrate || '—'}</td>
      <td class="r">$${baseline.toFixed(6)}</td>
      <td class="r">$${r.cost_usd.toFixed(6)}</td>
      <td class="r ${savedCls}">$${saved.toFixed(6)}</td>
    </tr>`;
  }).join('');
  document.getElementById('savings-rows').innerHTML = rows;
}
renderSavingsRows();

function toggleSavings() {
  document.getElementById('savings-panel').classList.toggle('open');
}

// --- replay / rewind ---
let currentStep = -1;  // -1 means "show all"; otherwise show 0..currentStep
let playing = false;
let playInterval = null;

const scrub = document.getElementById('scrub');
scrub.max = N - 1;
scrub.value = -1;

function applyStepVisibility() {
  cy.nodes().forEach(n => {
    const i = n.data('stepIndex');
    n.removeClass('future current');
    if (currentStep === -1) {
      // show all, no current
    } else if (i > currentStep) {
      n.addClass('future');
    } else if (i === currentStep) {
      n.addClass('current');
    }
  });
  cy.edges().forEach(e => {
    const ti = e.data('targetStep');
    e.removeClass('future');
    if (currentStep !== -1 && ti > currentStep) {
      e.addClass('future');
    }
  });
  syncSublabels();
  document.getElementById('counter').textContent =
    currentStep === -1 ? 'all' : `${currentStep + 1} / ${N}`;
  scrub.value = String(currentStep);
}

function setStep(i) {
  currentStep = Math.max(-1, Math.min(N - 1, i));
  applyStepVisibility();
}

function stepBy(delta) {
  if (currentStep === -1) {
    currentStep = delta > 0 ? 0 : N - 1;
  } else {
    currentStep += delta;
    if (currentStep < -1) currentStep = -1;
    if (currentStep >= N) currentStep = N - 1;
  }
  applyStepVisibility();
}

function togglePlay() {
  playing = !playing;
  const btn = document.getElementById('playBtn');
  if (playing) {
    btn.textContent = '❚❚';
    if (currentStep === -1 || currentStep >= N - 1) currentStep = -1;
    playInterval = setInterval(() => {
      if (currentStep >= N - 1) {
        playing = false;
        btn.textContent = '▶';
        clearInterval(playInterval);
        return;
      }
      stepBy(1);
    }, 850);
  } else {
    btn.textContent = '▶';
    if (playInterval) { clearInterval(playInterval); playInterval = null; }
  }
}

scrub.addEventListener('input', e => {
  setStep(parseInt(e.target.value, 10));
});

applyStepVisibility();
</script>
</body>
</html>
"""


def render(records: list[dict], baseline_model: str) -> str:
    workflow_id = records[0]["workflow_id"] if records else "(empty)"
    total_latency = sum(r["latency_ms"] for r in records)

    sv = _compute_savings(records, baseline_model)
    data_json = json.dumps({"records": sv["records"]})
    hw_colors_json = json.dumps(HARDWARE_COLORS)
    hw_shapes_json = json.dumps(HARDWARE_SHAPES)

    return (
        HTML_TEMPLATE
        .replace("__WORKFLOW_ID__", workflow_id)
        .replace("__CALLS__", str(len(records)))
        .replace("__COST__", f"{sv['actual_total']:.6f}")
        .replace("__LATENCY__", f"{total_latency:.0f}")
        .replace("__SAVED__", f"{sv['saved']:.6f}")
        .replace("__SAVED_PCT__", f"{sv['saved_pct']:.1f}")
        .replace("__BASELINE_MODEL__", sv["baseline_model"])
        .replace("__BASELINE_IN__", f"{sv['baseline_in_rate']:.2f}")
        .replace("__BASELINE_OUT__", f"{sv['baseline_out_rate']:.2f}")
        .replace("__BASELINE_TOTAL__", f"{sv['baseline_total']:.6f}")
        .replace("__DATA_JSON__", data_json)
        .replace("__HW_COLORS_JSON__", hw_colors_json)
        .replace("__HW_SHAPES_JSON__", hw_shapes_json)
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render a sploink JSONL trace as a graph canvas.")
    p.add_argument("path", nargs="?", help="Path to a .jsonl trace (default: latest)")
    p.add_argument("-o", "--output", default=None, help="Output HTML path")
    p.add_argument("--baseline", default=DEFAULT_BASELINE_MODEL,
                   help=f"Baseline model for cost-arbitrage comparison (default: {DEFAULT_BASELINE_MODEL})")
    p.add_argument("--no-open", action="store_true", help="Do not auto-open in a browser")
    args = p.parse_args(argv)

    src = Path(args.path) if args.path else _latest_trace()
    if src is None or not src.exists():
        print(f"No trace file found in {_default_trace_dir()}. Run an example first.", file=sys.stderr)
        return 1

    records = _load(src)
    if not records:
        print(f"Trace {src} is empty.", file=sys.stderr)
        return 1

    html = render(records, args.baseline)
    out = Path(args.output) if args.output else src.with_name(src.stem + ".canvas.html")
    out.write_text(html)

    sv = _compute_savings(records, args.baseline)
    print(f"wrote {out}  ({len(records)} calls, baseline={args.baseline}, saved=${sv['saved']:.6f} ({sv['saved_pct']:.1f}%))")

    if not args.no_open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
