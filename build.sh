#!/usr/bin/env bash
# Vercel build script for the sploink docs site.
#
# Why a shell script (not an inline `buildCommand`): Vercel enforces a 256-char
# limit on the `buildCommand` field. This script is what `vercel.json` invokes.
#
# Steps:
#   1. Create an ephemeral venv (works around PEP 668 / uv-managed system Python)
#   2. Install sploink (editable, so the CLI modules are importable) + mkdocs
#   3. Generate the two interactive HTML viewers directly into docs/
#   4. Build the static docs site into public/

set -euo pipefail

VENV=/tmp/venv

# 1. Ephemeral venv
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet

# 2. Install the package + docs tooling
"$VENV/bin/pip" install --quiet \
    -e . \
    mkdocs \
    mkdocs-material \
    pymdown-extensions

# 3. Generate live viewers into docs/ so mkdocs ships them with the static site
"$VENV/bin/python" -m sploink.architecture \
    --workflow parallel_dag \
    --out docs/architecture.html \
    --no-open
"$VENV/bin/python" -m sploink.dashboard \
    --results-dir bench/results \
    --out docs/dashboard.html \
    --no-open

# 4. Build the static docs site
"$VENV/bin/mkdocs" build --site-dir public

echo ""
echo "Build complete:"
ls -la public/architecture.html public/dashboard.html
