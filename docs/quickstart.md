# Quickstart

## Prerequisites

Sploink itself doesn't require any credentials — it's just routing and observability code. But it intercepts calls to **your** LLM SDK clients, so you need credentials for whichever providers you actually use.

### Set environment variables for the providers you'll use

```bash
# For the Anthropic example below — get from https://console.anthropic.com/settings/keys
export ANTHROPIC_API_KEY="sk-ant-..."

# For Groq (used in the bench and in routing examples) — get from https://console.groq.com/keys
export GROQ_API_KEY="gsk_..."

# For OpenAI — get from https://platform.openai.com/api-keys
export OPENAI_API_KEY="sk-..."

# For Together — get from https://api.together.xyz/settings/api-keys
export TOGETHER_API_KEY="..."
```

You only need keys for substrates you actually call. **None of these are sploink-specific** — they're the same env vars each SDK already uses.

### For Ollama (local, no API key)

```bash
# Install Ollama from https://ollama.com/download, then:
ollama pull llama3.1:8b   # ~4.7GB; takes a few minutes
```

Make sure Ollama is running (`ollama serve` or the desktop app) before any sploink call that routes to it.

### Storing keys

For local dev: put keys in a `.env` file at your project root (gitignored), and use `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()   # before any sploink / client setup
```

For production / CI: use your platform's secret manager (Vercel envs, AWS Secrets Manager, GitHub Actions secrets, etc.). Sploink doesn't need to know — it inherits whatever the SDK reads from `os.environ`.

---

## Install

```bash
# Core install (just the routing/observability layer)
pip install sploink

# With specific substrate SDKs:
pip install "sploink[anthropic]"
pip install "sploink[groq]"
pip install "sploink[ollama]"

# Everything:
pip install "sploink[all]"
```

Sploink core has only one dependency (Pydantic). The substrate SDKs are optional — install only the ones you actually use.

## Mode 1 — observability only

The simplest thing sploink does is observe every LLM call your agent makes and record a structured trace. You don't change any of your agent code — just call `sploink.wrap()` once at startup.

```python
import sploink
from anthropic import Anthropic

sploink.wrap()   # one line — patches every supported SDK

client = Anthropic()
client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=20,
    messages=[{"role": "user", "content": "is this spam?"}],
)
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=300,
    messages=[{"role": "user", "content": "explain why in detail"}],
)

sploink.trace.print_summary()
```

You get:

```
workflow 9f2c... | 2 calls | $0.0034 | 2400 ms
  tokens: in=80 out=420
  by step:
    classify   1x  $0.0001   200ms
    reason     1x  $0.0033  2200ms
  by hardware:
    frontier_api   2x  $0.0034
```

Every call is also persisted to `~/.sploink/traces/<workflow_id>.jsonl`. You can render the trace as HTML later:

```bash
python -m sploink.report                  # latest trace
python -m sploink.canvas                  # force-directed view
```

## Scoping a workflow — `sploink.workflow()`

When you want to bound a "workflow" explicitly (so calls inside are attributed to one workflow_id and an inferred `Graph` is recoverable on exit), wrap them in `sploink.workflow()`:

```python
import sploink
from anthropic import Anthropic

sploink.wrap()
client = Anthropic()

with sploink.workflow() as wf:
    client.messages.create(...)   # observed
    client.messages.create(...)   # observed
    # ... any number of LLM calls, any SDK ...

# After exit:
print(wf.records())               # the raw CallRecord list
print(wf.graph().topological_layers())   # inferred sploink.Graph
print(wf.summary())               # cost / latency / step-type aggregates
```

Note: don't confuse `sploink.workflow()` with `sploink.step()`.

- **`sploink.workflow()`** — *scopes one workflow.* Use it to mark "everything inside is one agent run."
- **`sploink.step(label)`** — *forces a step label* on calls inside the block. Use it when sploink's prompt-content heuristic misclassifies a call.

```python
with sploink.workflow():
    with sploink.step("classify"):     # any LLM call here is labeled "classify"
        client.chat.completions.create(...)
    client.chat.completions.create(...)  # labeled by heuristic
```

## Mode 2 — routing

Once you've observed your traces and confirmed step types look right, flip on routing to redirect cheap steps to a cheaper substrate:

```python
import sploink

sploink.wrap()
sploink.enable_routing()
```

The default v0 rules ([source](https://github.com/S-3-ai/sploink/blob/main/sploink/router.py)) send classify / rerank / extract / verify to Ollama (free, local) and reasoning steps to Groq (LPU, low-latency). Override the rules for your workflow as needed.

If sploink's prompt-content heuristic can't tell what kind of step a call is, mark it explicitly:

```python
with sploink.step("classify"):
    client.chat.completions.create(...)
```

## Mode 3 — visualize the routing

```bash
python -m sploink.architecture
```

Opens a self-contained HTML showing the workflow ↔ substrate bipartite assignment for the current routing strategy. Use the dropdown to compare strategies.

## Run the bench

If you want to verify the routing thesis on a real benchmark (HotpotQA, multi-hop QA), install the bench extras and run:

```bash
# 1. Install
pip install "sploink[bench]"

# 2. Pull the local model (free, ~4.7GB, takes a few minutes)
ollama pull llama3.1:8b

# 3. Set up credentials. The bench uses Groq for the cloud calls.
#    Either export in your shell:
export GROQ_API_KEY="gsk_..."

#    Or create a .env file at your project root (bench auto-loads it):
cat > .env << EOF
GROQ_API_KEY=gsk_...
EOF

# 4. Run
python -m bench.run --n 30 --graphs parallel_dag --strategy hw_routed
```

Without `GROQ_API_KEY`, the bench will crash on the first Groq call with `KeyError: 'GROQ_API_KEY'`. The `cpu_only` strategy works without it (pure Ollama, no cloud), but `lpu_only` and `hw_routed` both need it.

See [Bench](bench.md) for methodology and current findings.

## Concurrent workflows

Sploink's trace is scoped per-asyncio-task (via `contextvars.ContextVar`) and per-thread. Running many requests concurrently produces correctly-isolated traces with no extra effort:

```python
import asyncio, sploink
sploink.wrap()

async def one_request(question):
    # ... LLM calls here ...
    return sploink.trace.summary()

results = await asyncio.gather(*[one_request(q) for q in questions])
```

Each task gets its own `workflow_id`. The traces don't interleave.

## Common issues

- **`sploink.wrap()` doesn't patch a substrate I'm using.** Make sure the SDK is installed (`pip install sploink[groq]` etc.). Sploink silently skips wrappers for SDKs it can't import — by design, so it doesn't crash on missing optional deps.
- **No traces showing up.** Check `~/.sploink/traces/` — files appear there as calls happen.
- **Routed call fails.** If the routed substrate (e.g. Ollama) is down, sploink currently lets the exception propagate. Graceful fallback to the original substrate is on the roadmap.
