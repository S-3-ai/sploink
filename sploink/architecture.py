"""Static HTML visualizer for sploink's two-layer routing architecture.

Renders three things:
  1. Workflow IR (left) — logical agent steps with data-dependency edges.
  2. Hardware types (right) — the routing targets, each holding one or more
     substrate instances (providers).
  3. The bipartite assignment — solid blue edges showing which workflow node
     is routed to which hardware TYPE under the selected strategy.

Two-layer model:
  Layer 1 = bipartite edges (workflow step → hardware_type) — sploink's policy
  Layer 2 = the substrate instances nested inside each hardware_type box —
           the operational choice of WHICH provider serves that hardware type

Strategy switcher in the header shows how Layer 1 changes between strategies.
Layer 2 (instance selection) is shown but doesn't currently change per strategy.

Single self-contained HTML, no external dependencies, white theme.

Usage:
    python -m sploink.architecture
    python -m sploink.architecture --workflow parallel_dag --strategy hw_routed
    python -m sploink.architecture --out FILE --no-open
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from sploink.graph import Graph


# UI labels for step types — purely presentational.
STEP_DESCRIPTIONS: dict[str, str] = {
    "classify": "bridge vs comparison",
    "rerank":   "score paragraphs",
    "extract":  "pull relevant facts",
    "reason":   "synthesize answer",
    "verify":   "answer follows facts?",
}


# ─────────────────────────────────────────────────────────────────────────────
# Hardware types — the Layer 1 routing targets. Each contains substrate
# instances (Layer 2 — which provider serves this hardware type).
# ─────────────────────────────────────────────────────────────────────────────

HARDWARE_TYPES: list[dict] = [
    {
        "id": "cpu",
        "label": "CPU",
        "subtitle": "von Neumann general-purpose",
        "color": "#4f46e5",
        "bg":    "#eef2ff",
        "instances": [
            {"id": "ollama",   "provider": "Ollama",  "model": "llama3.1:8b",      "active": True,  "location": "local"},
            {"id": "salad",    "provider": "Salad",   "model": "llama3.1:8b",      "active": False, "location": "cloud"},
        ],
    },
    {
        "id": "lpu",
        "label": "LPU",
        "subtitle": "tensor streaming, deterministic",
        "color": "#d97706",
        "bg":    "#fef3c7",
        "instances": [
            {"id": "groq",     "provider": "Groq",    "model": "llama-3.1-8b-instant", "active": True,  "location": "cloud"},
            {"id": "cerebras", "provider": "Cerebras","model": "llama-3.1-8b",     "active": False, "location": "cloud"},
        ],
    },
    {
        "id": "gpu",
        "label": "GPU",
        "subtitle": "SIMT, high throughput",
        "color": "#059669",
        "bg":    "#d1fae5",
        "instances": [
            {"id": "together", "provider": "Together","model": "llama-3.1-70b",    "active": False, "location": "cloud"},
            {"id": "runpod",   "provider": "RunPod",  "model": "llama-3.1-70b",    "active": False, "location": "cloud"},
        ],
    },
    {
        "id": "frontier_api",
        "label": "Frontier API",
        "subtitle": "closed, hardware-opaque",
        "color": "#dc2626",
        "bg":    "#fee2e2",
        "instances": [
            {"id": "anthropic","provider": "Anthropic","model": "claude-sonnet-4-6","active": False, "location": "cloud"},
            {"id": "openai",   "provider": "OpenAI",  "model": "gpt-4o",           "active": False, "location": "cloud"},
        ],
    },
]


# Strategies map step → hardware_type. This is LAYER 1 only. Layer 2
# (which substrate instance to use for that hardware_type) is decoupled.
STRATEGIES: dict[str, dict[str, str]] = {
    "cpu_only": {
        "classify": "cpu", "rerank": "cpu", "extract": "cpu",
        "reason":   "cpu", "verify": "cpu",
    },
    "lpu_only": {
        "classify": "lpu", "rerank": "lpu", "extract": "lpu",
        "reason":   "lpu", "verify": "lpu",
    },
    "hw_routed": {
        "classify": "cpu", "rerank": "cpu", "extract": "cpu",
        "reason":   "lpu", "verify": "cpu",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Geometry
# ─────────────────────────────────────────────────────────────────────────────

CANVAS_W = 1240
CANVAS_H = 760
WORKFLOW_X = 200
HW_X = 880
WORKFLOW_NODE_W = 220
WORKFLOW_NODE_H = 70
HW_BOX_W = 260
HW_BOX_HEADER_H = 50
HW_INSTANCE_H = 36
HW_INSTANCE_PAD = 8


def _hw_box_height(hw_type: dict) -> int:
    return HW_BOX_HEADER_H + len(hw_type["instances"]) * HW_INSTANCE_H + HW_INSTANCE_PAD * 2


def _ypositions(n: int, top: int, bottom: int) -> list[int]:
    if n <= 1:
        return [top]
    gap = (bottom - top) / (n - 1)
    return [int(top + i * gap) for i in range(n)]


def _workflow_payload(graph: Graph) -> tuple[list[dict], list[tuple[str, str]], dict[str, tuple[int, int]]]:
    nodes_ui = []
    for node in graph.nodes:
        nodes_ui.append({
            "id": node.id,
            "label": node.id,
            "step": node.step,
            "subtitle": STEP_DESCRIPTIONS.get(node.step, node.step),
            "max_tokens": node.max_tokens,
        })

    layers = graph.topological_layers()
    n = len(graph.nodes)
    ys = _ypositions(n, 120, CANVAS_H - 80)

    positions: dict[str, tuple[int, int]] = {}
    i = 0
    for layer in layers:
        if len(layer) == 1:
            positions[layer[0].id] = (WORKFLOW_X, ys[i])
            i += 1
        else:
            spread = 220
            x_offsets = (
                [-spread // 2 + j * spread // (len(layer) - 1) for j in range(len(layer))]
                if len(layer) > 1 else [0]
            )
            layer_y = ys[i] if i < len(ys) else ys[-1]
            for node, dx in zip(layer, x_offsets):
                positions[node.id] = (WORKFLOW_X + dx, layer_y)
            i += 1
    return nodes_ui, list(graph.edges), positions


def _hardware_positions() -> dict[str, tuple[int, int]]:
    """Stack hardware-type boxes vertically. Each box's height depends on instance count."""
    positions: dict[str, tuple[int, int]] = {}
    total_height = sum(_hw_box_height(ht) for ht in HARDWARE_TYPES)
    spacing = (CANVAS_H - 160 - total_height) / max(1, len(HARDWARE_TYPES) - 1)
    spacing = max(spacing, 12)
    y = 120
    for ht in HARDWARE_TYPES:
        positions[ht["id"]] = (HW_X, y)
        y += _hw_box_height(ht) + int(spacing)
    return positions


def render_html(workflow_graph: Graph, default_strategy: str = "hw_routed",
                workflow_name: str = "workflow") -> str:
    workflow_nodes, workflow_edges, workflow_pos = _workflow_payload(workflow_graph)
    hw_pos = _hardware_positions()

    payload = {
        "workflow_name": workflow_name,
        "workflow_nodes": workflow_nodes,
        "workflow_edges": workflow_edges,
        "workflow_pos": workflow_pos,
        "hardware_types": HARDWARE_TYPES,
        "hw_pos": hw_pos,
        "strategies": STRATEGIES,
        "default_strategy": default_strategy,
        "geom": {
            "wf_node_w": WORKFLOW_NODE_W,
            "wf_node_h": WORKFLOW_NODE_H,
            "hw_box_w": HW_BOX_W,
            "hw_box_header_h": HW_BOX_HEADER_H,
            "hw_instance_h": HW_INSTANCE_H,
            "hw_instance_pad": HW_INSTANCE_PAD,
        },
        "canvas_w": CANVAS_W,
        "canvas_h": CANVAS_H,
    }
    return _HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sploink — Workflow ↔ Hardware</title>
<style>
  :root {
    --bg: #ffffff;
    --panel: #f8fafc;
    --text: #0f172a;
    --muted: #64748b;
    --border: #e2e8f0;
    --border-strong: #cbd5e1;
    --edge: #94a3b8;
    --bipartite: #3b82f6;
    --workflow-stroke: #475569;
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
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 24px;
  }
  header h1 { font-size: 18px; font-weight: 600; margin: 0; }
  header .subtitle { color: var(--muted); font-size: 13px; }
  .controls { display: flex; align-items: center; gap: 16px; }
  .controls label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
  .controls .pill {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid var(--border);
  }
  .controls select {
    font-family: inherit; font-size: 13px;
    padding: 6px 10px;
    background: var(--bg);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    cursor: pointer;
  }
  main { padding: 20px 28px; display: flex; gap: 24px; align-items: flex-start; }
  .canvas-wrap {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px;
    flex: 1;
  }
  svg { display: block; }
  .col-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    fill: var(--muted);
    font-weight: 600;
  }
  .col-sublabel {
    font-size: 10px;
    fill: var(--muted);
    font-style: italic;
  }
  .node-rect {
    fill: #ffffff;
    stroke: var(--workflow-stroke);
    stroke-width: 1.5;
  }
  .node-title { font-size: 14px; font-weight: 600; fill: var(--text); }
  .node-sub   { font-size: 11px; fill: var(--muted); }
  .node-tok   {
    font-size: 11px; fill: var(--muted);
    font-family: "SF Mono", Menlo, Consolas, monospace;
  }
  .hw-box {
    stroke-width: 1.5;
  }
  .hw-header-accent { /* the thin colored bar at top */ }
  .hw-title { font-size: 14px; font-weight: 600; fill: var(--text); }
  .hw-sub   { font-size: 11px; fill: var(--muted); }
  .hw-instance-row.active {
    /* active instance — vivid */
  }
  .hw-instance-row.inactive text { fill: var(--muted); opacity: 0.55; }
  .instance-provider { font-size: 12px; font-weight: 500; }
  .instance-model    { font-size: 11px; font-family: "SF Mono", Menlo, Consolas, monospace; fill: var(--muted); }
  .instance-dot      { stroke-width: 1.5; }
  .workflow-edge {
    stroke: var(--edge);
    stroke-width: 1.5;
    fill: none;
    stroke-dasharray: 4 4;
  }
  .bipartite-edge {
    stroke: var(--bipartite);
    stroke-width: 2;
    fill: none;
    opacity: 0.7;
    transition: opacity 0.15s ease;
  }
  .bipartite-edge.highlighted { opacity: 1; stroke-width: 3; }
  .bipartite-edge.dimmed { opacity: 0.12; }
  .arrow { fill: var(--edge); }
  .arrow-bipartite { fill: var(--bipartite); }
  .side-panel {
    width: 320px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .side-panel h2 {
    font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 10px 0;
  }
  .layer-badge {
    display: inline-block;
    background: var(--bipartite);
    color: white;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 3px;
    margin-right: 6px;
  }
  .legend-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 13px; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
  .assignment-section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); font-size: 13px; }
  .assignment-section table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .assignment-section td { padding: 4px 0; border-bottom: 1px solid var(--border); }
  .assignment-section td:first-child {
    color: var(--muted);
    font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 12px;
  }
  .assignment-section td:nth-child(2) { font-weight: 500; }
  .assignment-section td:last-child {
    text-align: right;
    color: var(--muted);
    font-size: 11px;
  }
  footer { padding: 14px 28px 22px; color: var(--muted); font-size: 12px; }
  footer code {
    background: var(--panel);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 11px;
  }
  /* viewer switcher — shared between architecture.html + dashboard.html */
  .viewer-switcher {
    display: flex;
    gap: 4px;
    background: var(--panel);
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
  .viewer-switcher .docs-link { color: var(--bipartite); padding: 6px 10px; }
  .viewer-switcher .docs-link:hover { background: transparent; color: var(--bipartite); }
</style>
</head>
<body>

<header>
  <div>
    <h1>Sploink — workflow ↔ hardware (two-layer routing)</h1>
    <div class="subtitle">Layer 1: routing policy (workflow step → hardware type) &nbsp; · &nbsp; Layer 2: substrate selection (hardware type → provider instance)</div>
  </div>
  <div class="controls">
    <nav class="viewer-switcher">
      <a href="architecture.html" class="active">Architecture</a>
      <a href="dashboard.html">Dashboard</a>
      <a href="/" class="docs-link">← Docs</a>
    </nav>
    <span class="pill" id="workflow-pill"></span>
    <label for="strategy">routing strategy</label>
    <select id="strategy"></select>
  </div>
</header>

<main>
  <div class="canvas-wrap">
    <svg id="canvas" viewBox="0 0 1240 760" width="100%"></svg>
  </div>
  <aside class="side-panel">
    <h2><span class="layer-badge">L1</span>Hardware types</h2>
    <div id="legend"></div>
    <div class="assignment-section">
      <h2><span class="layer-badge">L1</span>Routing (step → hw type)</h2>
      <table id="assignment-table"></table>
    </div>
    <div class="assignment-section">
      <h2><span class="layer-badge">L2</span>Active substrates</h2>
      <table id="instance-table"></table>
    </div>
  </aside>
</main>

<footer>
  Workflow IR (left) read from <code>bench.graphs.GRAPHS</code>. Hardware types and substrate instances (right) defined in <code>sploink.architecture</code>. Routing policies in <code>bench.strategies.HW_POLICIES</code>. Solid blue = Layer 1 (the routing decision). Filled dots inside each hardware-type box = Layer 2 (currently active substrate).
</footer>

<script>
const DATA = __PAYLOAD__;

const ARROW_DEFS = `
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" class="arrow"/>
    </marker>
    <marker id="arrow-bipartite" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" class="arrow-bipartite"/>
    </marker>
  </defs>
`;

function hwBoxHeight(ht) {
  return DATA.geom.hw_box_header_h + ht.instances.length * DATA.geom.hw_instance_h + DATA.geom.hw_instance_pad * 2;
}

function activeInstance(ht) {
  return ht.instances.find(i => i.active) || ht.instances[0];
}

function renderSVG(strategyName) {
  const assignment = DATA.strategies[strategyName];
  const used = new Set(Object.values(assignment));

  const WW = DATA.geom.wf_node_w, WH = DATA.geom.wf_node_h;
  const HW = DATA.geom.hw_box_w;
  let svg = ARROW_DEFS;

  // Column labels
  const sampleWfX = DATA.workflow_nodes.length ? DATA.workflow_pos[DATA.workflow_nodes[0].id][0] + WW/2 : 200;
  svg += `<text x="${sampleWfX}" y="60" text-anchor="middle" class="col-label">workflow ir</text>`;
  svg += `<text x="${sampleWfX}" y="76" text-anchor="middle" class="col-sublabel">customer's agent — fixed</text>`;
  const hwLabelX = DATA.hw_pos[DATA.hardware_types[0].id][0] + HW/2;
  svg += `<text x="${hwLabelX}" y="60" text-anchor="middle" class="col-label">hardware types</text>`;
  svg += `<text x="${hwLabelX}" y="76" text-anchor="middle" class="col-sublabel">routing targets</text>`;

  // Workflow dependency edges (dashed)
  for (const [src, dst] of DATA.workflow_edges) {
    const [x1, y1] = DATA.workflow_pos[src];
    const [x2, y2] = DATA.workflow_pos[dst];
    const sx = x1 + WW/2, sy = y1 + WH;
    const ex = x2 + WW/2, ey = y2;
    const cy = (sy + ey) / 2;
    svg += `<path class="workflow-edge" d="M ${sx} ${sy} C ${sx} ${cy}, ${ex} ${cy}, ${ex} ${ey}" marker-end="url(#arrow)"/>`;
  }

  // Layer-1 bipartite edges — workflow node → hardware-type box
  for (const node of DATA.workflow_nodes) {
    const hwId = assignment[node.step] || assignment[node.id];
    if (!hwId) continue;
    const ht = DATA.hardware_types.find(h => h.id === hwId);
    if (!ht) continue;
    const [x1, y1] = DATA.workflow_pos[node.id];
    const [x2, y2] = DATA.hw_pos[hwId];
    const boxH = hwBoxHeight(ht);
    const sx = x1 + WW;
    const sy = y1 + WH/2;
    const ex = x2;
    const ey = y2 + boxH/2;
    const mid = (sx + ex) / 2;
    svg += `<path class="bipartite-edge" data-step="${node.id}" data-hw="${hwId}" d="M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${ey}, ${ex} ${ey}" marker-end="url(#arrow-bipartite)"/>`;
  }

  // Workflow nodes
  for (const node of DATA.workflow_nodes) {
    const [x, y] = DATA.workflow_pos[node.id];
    svg += `<g data-node="${node.id}">`;
    svg += `<rect class="node-rect" x="${x}" y="${y}" width="${WW}" height="${WH}" rx="8" ry="8"/>`;
    svg += `<text class="node-title" x="${x + 14}" y="${y + 26}">${node.label}</text>`;
    svg += `<text class="node-sub"   x="${x + 14}" y="${y + 46}">${node.subtitle}</text>`;
    svg += `<text class="node-tok"   x="${x + WW - 14}" y="${y + 26}" text-anchor="end">${node.max_tokens} tok</text>`;
    svg += `</g>`;
  }

  // Hardware-type boxes (with nested substrate instances)
  for (const ht of DATA.hardware_types) {
    const [x, y] = DATA.hw_pos[ht.id];
    const boxH = hwBoxHeight(ht);
    const dim = !used.has(ht.id);
    svg += `<g data-hw="${ht.id}" style="${dim ? 'opacity:0.45' : ''}">`;
    // outer box
    svg += `<rect class="hw-box" x="${x}" y="${y}" width="${HW}" height="${boxH}" rx="10" ry="10" style="stroke:${ht.color}; fill:${ht.bg}"/>`;
    // colored accent bar
    svg += `<rect x="${x}" y="${y}" width="${HW}" height="4" rx="2" ry="2" style="fill:${ht.color}"/>`;
    // header
    svg += `<text class="hw-title" x="${x + 14}" y="${y + 26}">${ht.label}</text>`;
    svg += `<text class="hw-sub"   x="${x + 14}" y="${y + 42}">${ht.subtitle}</text>`;
    // instances
    const instTop = y + DATA.geom.hw_box_header_h + DATA.geom.hw_instance_pad;
    ht.instances.forEach((inst, j) => {
      const iy = instTop + j * DATA.geom.hw_instance_h;
      const rowCls = inst.active ? "hw-instance-row active" : "hw-instance-row inactive";
      svg += `<g class="${rowCls}">`;
      // dot — filled if active, outlined if inactive
      const dotFill = inst.active ? ht.color : "none";
      svg += `<circle class="instance-dot" cx="${x + 22}" cy="${iy + 18}" r="5" style="fill:${dotFill}; stroke:${ht.color}"/>`;
      svg += `<text class="instance-provider" x="${x + 36}" y="${iy + 16}">${inst.provider}</text>`;
      svg += `<text class="instance-model"    x="${x + 36}" y="${iy + 30}">${inst.model}</text>`;
      const tag = inst.location;
      svg += `<text class="instance-model" x="${x + HW - 14}" y="${iy + 16}" text-anchor="end">${tag}</text>`;
      if (!inst.active) {
        svg += `<text class="instance-model" x="${x + HW - 14}" y="${iy + 30}" text-anchor="end">(planned)</text>`;
      }
      svg += `</g>`;
    });
    svg += `</g>`;
  }

  document.getElementById('canvas').innerHTML = svg;
  attachHover();
}

function attachHover() {
  document.querySelectorAll('[data-node]').forEach(el => {
    const step = el.getAttribute('data-node');
    el.addEventListener('mouseenter', () => highlight({step}));
    el.addEventListener('mouseleave', clearHighlight);
  });
  document.querySelectorAll('g[data-hw]').forEach(el => {
    const hw = el.getAttribute('data-hw');
    el.addEventListener('mouseenter', () => highlight({hw}));
    el.addEventListener('mouseleave', clearHighlight);
  });
}

function highlight({step, hw}) {
  document.querySelectorAll('.bipartite-edge').forEach(el => {
    const matchStep = step && el.getAttribute('data-step') === step;
    const matchHw   = hw   && el.getAttribute('data-hw')   === hw;
    if (matchStep || matchHw) { el.classList.add('highlighted'); el.classList.remove('dimmed'); }
    else { el.classList.add('dimmed'); el.classList.remove('highlighted'); }
  });
}

function clearHighlight() {
  document.querySelectorAll('.bipartite-edge').forEach(el => {
    el.classList.remove('highlighted'); el.classList.remove('dimmed');
  });
}

function renderLegend() {
  const html = DATA.hardware_types.map(ht =>
    `<div class="legend-row">
       <div class="legend-swatch" style="background:${ht.color}"></div>
       <div><b>${ht.label}</b> <span style="color:var(--muted)">— ${ht.subtitle}</span></div>
     </div>`
  ).join('');
  document.getElementById('legend').innerHTML = html;
}

function renderAssignmentTable(strategyName) {
  const assignment = DATA.strategies[strategyName];
  const htById = Object.fromEntries(DATA.hardware_types.map(h => [h.id, h]));
  const html = DATA.workflow_nodes.map(n => {
    const hwId = assignment[n.step] || assignment[n.id];
    const ht = htById[hwId];
    if (!ht) return '';
    return `<tr>
       <td>${n.label}</td>
       <td><span style="color:${ht.color}">${ht.label}</span></td>
       <td>${ht.id}</td>
     </tr>`;
  }).join('');
  document.getElementById('assignment-table').innerHTML = html;
}

function renderInstanceTable(strategyName) {
  const assignment = DATA.strategies[strategyName];
  const used = new Set(Object.values(assignment));
  const html = DATA.hardware_types
    .filter(ht => used.has(ht.id))
    .map(ht => {
      const active = activeInstance(ht);
      return `<tr>
        <td>${ht.label}</td>
        <td><span style="color:${ht.color}">${active.provider}</span></td>
        <td>${active.model}</td>
      </tr>`;
    }).join('');
  document.getElementById('instance-table').innerHTML = html;
}

function renderStrategySelector() {
  const sel = document.getElementById('strategy');
  sel.innerHTML = Object.keys(DATA.strategies)
    .map(s => `<option value="${s}" ${s === DATA.default_strategy ? 'selected' : ''}>${s}</option>`)
    .join('');
  sel.addEventListener('change', e => {
    renderSVG(e.target.value);
    renderAssignmentTable(e.target.value);
    renderInstanceTable(e.target.value);
  });
}

document.getElementById('workflow-pill').textContent = `workflow: ${DATA.workflow_name}`;
renderLegend();
renderStrategySelector();
renderSVG(DATA.default_strategy);
renderAssignmentTable(DATA.default_strategy);
renderInstanceTable(DATA.default_strategy);
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=str, default="sploink_architecture.html",
                   help="Path to write the HTML file (default: ./sploink_architecture.html)")
    p.add_argument("--workflow", type=str, default="parallel_dag",
                   help="Which workflow graph to visualize")
    p.add_argument("--strategy", type=str, default="hw_routed",
                   choices=list(STRATEGIES.keys()),
                   help="Default strategy to display")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)

    try:
        from bench.graphs import GRAPHS
    except ImportError:
        GRAPHS = _builtin_example_graphs()

    if args.workflow not in GRAPHS:
        print(f"unknown workflow: {args.workflow!r}. available: {list(GRAPHS)}", file=sys.stderr)
        return 2
    graph = GRAPHS[args.workflow]

    html = render_html(workflow_graph=graph, default_strategy=args.strategy, workflow_name=args.workflow)
    out_path = Path(args.out).resolve()
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)

    if not args.no_open:
        webbrowser.open(out_path.as_uri())
    return 0


def _builtin_example_graphs() -> dict[str, Graph]:
    """Small built-in example workflows for pip-installed users without bench/."""
    def _no_prompt(_ex, _state):
        return ""

    def _node(node_id: str, step: str, max_tokens: int):
        from sploink.graph import Node
        return Node(id=node_id, step=step, max_tokens=max_tokens, build_prompt=_no_prompt)

    linear = Graph(
        nodes=(
            _node("classify", "classify", 8),
            _node("rerank", "rerank", 400),
            _node("extract", "extract", 300),
            _node("reason", "reason", 60),
            _node("verify", "verify", 6),
        ),
        edges=(("classify", "rerank"), ("rerank", "extract"),
               ("extract", "reason"), ("reason", "verify")),
        answer_node="reason",
    )
    parallel_dag = Graph(
        nodes=linear.nodes,
        edges=(("classify", "extract"), ("rerank", "extract"),
               ("extract", "reason"), ("reason", "verify")),
        answer_node="reason",
    )
    return {"linear": linear, "parallel_dag": parallel_dag}


if __name__ == "__main__":
    raise SystemExit(main())
