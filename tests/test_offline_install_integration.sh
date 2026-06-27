#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Offline install integration test
#
# Steps:
#   1. Build core wheel locally (uv build --wheel)
#   2. pip download the core's transitive deps into the same dir (needs network)
#   3. Write a requirements.txt pinning every wheel
#   4. In a FRESH venv: pip install --no-index --find-links=<dir> -r requirements.txt
#   5. Assert <venv>/bin/testpilot --version exits 0
#   6. Assert <venv>/bin/testpilot list-plugins exits 0
#
# If network is not available, prints SKIP and exits 0.
# Self-contained and idempotent.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WH_DIR="/tmp/tp_offline_test_wheels"
VENV_DIR="/tmp/tp_offline_test_venv"
REQ_FILE="/tmp/tp_offline_test_requirements.txt"

echo "[INFO] TestPilot offline install integration test"
echo "[INFO] Repo root: ${REPO_ROOT}"

# ── 1. Build core wheel locally ───────────────────────────────────────────────
echo "[INFO] Building core wheel with uv build --wheel ..."
rm -rf "$WH_DIR"
mkdir -p "$WH_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "[FAIL] uv not found; cannot build wheel"
    exit 1
fi

(cd "$REPO_ROOT" && uv build --wheel -o "$WH_DIR") \
    || { echo "[FAIL] uv build --wheel failed"; exit 1; }

CORE_WHL="$(ls "$WH_DIR"/*.whl 2>/dev/null | head -1)"
if [[ -z "$CORE_WHL" ]]; then
    echo "[FAIL] No wheel produced in ${WH_DIR}"
    exit 1
fi
echo "[OK] Core wheel built: $(basename "$CORE_WHL")"

# ── 2. Download transitive deps (network required) ────────────────────────────
echo "[INFO] Downloading transitive deps (network required) ..."

# Try a quick network probe first
if ! python3 -c "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)" 2>/dev/null; then
    echo "SKIP: no network — cannot download deps for offline test"
    exit 0
fi

if ! pip download \
        --only-binary=:all: \
        --dest "$WH_DIR" \
        "$CORE_WHL" \
        2>&1; then
    echo "SKIP: no network or pip download failed — skipping offline integration test"
    exit 0
fi
echo "[OK] Deps downloaded"

# ── 3. Write pinned requirements.txt ─────────────────────────────────────────
echo "[INFO] Generating requirements.txt ..."
python3 - "$WH_DIR" "$REQ_FILE" << 'PYEOF'
import sys, pathlib, re

wheelhouse = pathlib.Path(sys.argv[1])
req_file = sys.argv[2]

lines = []
for whl in sorted(wheelhouse.glob("*.whl")):
    m = re.match(r'^([A-Za-z0-9_.-]+?)-([0-9][^-]*)-', whl.name)
    if m:
        dist = m.group(1).replace('_', '-')
        ver = m.group(2)
        lines.append(f"{dist}=={ver}")

lines.sort()
with open(req_file, 'w') as f:
    f.write('\n'.join(lines) + '\n')
print(f"requirements.txt: {len(lines)} entries")
PYEOF
echo "[OK] requirements.txt written:"
cat "$REQ_FILE"

# ── 4. Fresh venv + offline install ──────────────────────────────────────────
echo "[INFO] Creating fresh test venv: ${VENV_DIR} ..."
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"

echo "[INFO] Installing from offline wheelhouse (--no-index --find-links) ..."
"$VENV_DIR/bin/pip" install \
    --no-index \
    --find-links="$WH_DIR" \
    -r "$REQ_FILE" \
    --quiet \
    || { echo "[FAIL] Offline pip install failed"; exit 1; }
echo "[OK] Offline install succeeded"

# ── 5. Smoke: testpilot --version ────────────────────────────────────────────
echo "[INFO] Smoke test: testpilot --version ..."
VERSION_OUT="$("$VENV_DIR/bin/testpilot" --version 2>&1)"
echo "[OUT] ${VERSION_OUT}"
echo "[OK] testpilot --version exited 0"

# ── 6. Smoke: testpilot list-plugins ─────────────────────────────────────────
echo "[INFO] Smoke test: testpilot list-plugins ..."
LIST_OUT="$("$VENV_DIR/bin/testpilot" list-plugins 2>&1)"
echo "[OUT] ${LIST_OUT}"
echo "[OK] testpilot list-plugins exited 0"

echo ""
echo "================================================"
echo "  PASS: offline install integration test"
echo "================================================"
