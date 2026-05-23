"""Verify resolve_route() routes via the curated index when configure() is set,
and falls back to the static DEFAULT_RULES otherwise.

This is the wiring test for v0.1.5: it proves sploink.configure(optimize_for=...)
actually drives the dispatch decision, not just the explain_pick() output.
"""
from __future__ import annotations

import importlib
import sys


def fresh_sploink():
    """Re-import sploink so module-level _USER_CONFIGURED is reset between cases."""
    for mod in [m for m in sys.modules if m == "sploink" or m.startswith("sploink.")]:
        del sys.modules[mod]
    return importlib.import_module("sploink")


def main() -> int:
    fails: list[str] = []

    # 1. Before configure(): legacy DEFAULT_RULES path.
    s = fresh_sploink()
    from sploink.route import resolve_route
    r = resolve_route("classify")
    if (r.substrate, r.model) != ("ollama", "qwen2.5:7b"):
        fails.append(f"pre-configure classify: expected DEFAULT_RULES ollama/qwen2.5:7b, got {r}")

    # 2. configure(cost): cheapest in index wins; cost=0 → Ollama Llama 8B.
    s = fresh_sploink()
    s.configure(optimize_for="cost")
    from sploink.route import resolve_route
    for step in ("classify", "rerank", "extract", "reason", "verify"):
        r = resolve_route(step)
        if r.substrate != "ollama":
            fails.append(f"cost {step}: expected ollama, got {r.substrate}")

    # 3. configure(quality): Sonnet wins for reason, Haiku for classify.
    s = fresh_sploink()
    s.configure(optimize_for="quality")
    from sploink.route import resolve_route
    r = resolve_route("reason")
    if (r.substrate, r.model) != ("anthropic", "claude-sonnet-4-6"):
        fails.append(f"quality reason: expected anthropic/sonnet, got {r}")
    r = resolve_route("classify")
    if (r.substrate, r.model) != ("anthropic", "claude-haiku-4-5"):
        fails.append(f"quality classify: expected anthropic/haiku, got {r}")

    # 4. configure(latency): LPU wins for low-latency steps.
    s = fresh_sploink()
    s.configure(optimize_for="latency")
    from sploink.route import resolve_route
    r = resolve_route("classify")
    if r.substrate != "groq":
        fails.append(f"latency classify: expected groq (LPU), got {r.substrate}")

    # 5. Step not in index → still falls back to DEFAULT_RULES even when configured.
    s = fresh_sploink()
    s.configure(optimize_for="cost")
    from sploink.route import resolve_route
    r = resolve_route("code_gen")
    if (r.substrate, r.model) != ("groq", "llama-3.3-70b-versatile"):
        fails.append(f"code_gen fallback: expected DEFAULT_RULES groq/70b, got {r}")

    # 6. Dict weights also work.
    s = fresh_sploink()
    s.configure(optimize_for={"cost": 1.0, "latency": 0.0, "quality": 0.0})
    from sploink.route import resolve_route
    r = resolve_route("classify")
    if r.substrate != "ollama":
        fails.append(f"dict weights cost=1.0: expected ollama, got {r.substrate}")

    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: 6 configure() → resolve_route cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
