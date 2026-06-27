#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Offline install integration test (REAL installer gate)
#
# Exercises the actual offline-installer code path end to end:
#   1. Build the core wheel locally (uv build --wheel)
#   2. pip download the core's transitive deps into a wheelhouse (needs network)
#   3. Stage a REAL bundle in build-bundle.sh's shape:
#        <stage>/wheelhouse/*.whl
#        <stage>/requirements.txt          (pinned from wheel filenames)
#      tarred as  testpilot-bundle-<ver>-linux-<arch>-cp<pyXY>.tar.gz
#      with a matching  <bundle>.SHA256SUMS  sidecar.
#   4. Run  bash scripts/install.sh --offline <bundle>  into an ISOLATED
#      TESTPILOT_HOME / BIN_DIR / SKILLS_DIR.  This gates the real installer
#      paths: checksum verify, python+arch tag checks, extraction, wheelhouse
#      install, wrapper, skill sync, and the post-install --verify-install gate.
#   5. Assert the managed `testpilot --version` and `testpilot --verify-install`
#      both exit 0.
#
# Network policy:
#   - Staging the bundle needs network ONCE (to pip download deps).
#   - In CI (the CI env var is set) a network/dependency-prep failure is a HARD
#     FAIL — CI runners have network, and a silent skip would hide installer
#     regressions (this is the whole point of the gate).
#   - Run locally with no network: prints an explicit SKIP and exits 0.
#
# Self-contained and idempotent; all artifacts live under a temp dir.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IN_CI="${CI:-}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

WHEELHOUSE="$WORK/stage/wheelhouse"
STAGE="$WORK/stage"
REQ_FILE="$STAGE/requirements.txt"
mkdir -p "$WHEELHOUSE"

echo "[INFO] TestPilot offline install integration test"
echo "[INFO] Repo root: ${REPO_ROOT}"
echo "[INFO] CI mode: ${IN_CI:-<local>}"

# A dependency-prep / network failure is a hard FAIL in CI, but a friendly SKIP
# locally (so the test stays runnable on an air-gapped dev box).
prep_fail_or_skip() {
    local msg="$1"
    if [[ -n "$IN_CI" ]]; then
        echo "[FAIL] ${msg} (hard failure in CI — runners must be able to stage the bundle)"
        exit 1
    fi
    echo "SKIP: ${msg} (local run, treating as genuinely offline)"
    exit 0
}

# ── 1. Build core wheel locally ───────────────────────────────────────────────
echo "[INFO] Building core wheel with uv build --wheel ..."
if ! command -v uv >/dev/null 2>&1; then
    echo "[FAIL] uv not found; cannot build wheel"
    exit 1
fi

(cd "$REPO_ROOT" && uv build --wheel -o "$WHEELHOUSE") \
    || { echo "[FAIL] uv build --wheel failed"; exit 1; }

CORE_WHL="$(ls "$WHEELHOUSE"/*.whl 2>/dev/null | head -1)"
if [[ -z "$CORE_WHL" ]]; then
    echo "[FAIL] No wheel produced in ${WHEELHOUSE}"
    exit 1
fi
echo "[OK] Core wheel built: $(basename "$CORE_WHL")"

# ── 2. Download transitive deps (network required to stage the bundle) ─────────
echo "[INFO] Downloading transitive deps (network required to stage) ..."
if ! python3 -c "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=5)" 2>/dev/null; then
    prep_fail_or_skip "no network — cannot download deps for the offline bundle"
fi

# Bind the download to the SAME interpreter (python3) that tags the bundle and
# (via UV_PYTHON below) creates the managed venv, so the cpXY wheels match.
if ! python3 -m pip download \
        --only-binary=:all: \
        --dest "$WHEELHOUSE" \
        "$CORE_WHL" \
        2>&1; then
    prep_fail_or_skip "pip download of core deps failed"
fi
echo "[OK] Deps downloaded into wheelhouse"

# ── 3. Pin requirements.txt from wheel filenames ──────────────────────────────
echo "[INFO] Generating requirements.txt ..."
python3 - "$WHEELHOUSE" "$REQ_FILE" << 'PYEOF'
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

# ── 4. Assemble the bundle (build-bundle.sh shape) + SHA256SUMS sidecar ───────
VERSION="$(cat "${REPO_ROOT}/VERSION" | tr -d '[:space:]')"
ARCH="$(uname -m)"
PYMINOR="$(python3 -c 'import sys; print(str(sys.version_info.major)+str(sys.version_info.minor))')"
BUNDLE_NAME="testpilot-bundle-${VERSION}-linux-${ARCH}-cp${PYMINOR}.tar.gz"
BUNDLE_PATH="$WORK/${BUNDLE_NAME}"

echo "[INFO] Producing bundle: ${BUNDLE_NAME} ..."
(cd "$STAGE" && tar czf "$BUNDLE_PATH" .)
sha256sum "$BUNDLE_PATH" > "${BUNDLE_PATH}.SHA256SUMS"
echo "[OK] Bundle + SHA256SUMS staged"

# ── 5. Run the REAL offline installer into an isolated managed home ───────────
TP_HOME="$WORK/managed/share/testpilot"
TP_BIN="$WORK/managed/bin"
TP_SKILLS="$WORK/managed/skills"
echo "[INFO] Running scripts/install.sh --offline <bundle> (isolated home) ..."
# Pin uv's venv interpreter to the SAME python3 the bundle was tagged/built for,
# so the cpXY wheels resolve (uv may otherwise default to a different minor).
if ! TESTPILOT_HOME="$TP_HOME" \
     TESTPILOT_BIN_DIR="$TP_BIN" \
     TESTPILOT_SKILLS_DIR="$TP_SKILLS" \
     UV_PYTHON="$(command -v python3)" \
     bash "${REPO_ROOT}/scripts/install.sh" --offline "$BUNDLE_PATH"; then
    echo "[FAIL] scripts/install.sh --offline returned nonzero (real installer gate failed)"
    exit 1
fi
echo "[OK] Offline installer completed (checksum/arch/extract/wrapper/skill/verify gate)"

# ── 6. Smoke the managed wrapper ──────────────────────────────────────────────
WRAPPER="$TP_BIN/testpilot"
[[ -x "$WRAPPER" ]] || { echo "[FAIL] managed wrapper missing/not executable: $WRAPPER"; exit 1; }

echo "[INFO] Smoke: testpilot --version ..."
VERSION_OUT="$("$WRAPPER" --version 2>&1)" || { echo "[FAIL] testpilot --version nonzero: $VERSION_OUT"; exit 1; }
echo "[OUT] ${VERSION_OUT}"

echo "[INFO] Smoke: testpilot --verify-install ..."
VERIFY_OUT="$(TESTPILOT_HOME="$TP_HOME" TESTPILOT_BIN_DIR="$TP_BIN" TESTPILOT_SKILLS_DIR="$TP_SKILLS" "$WRAPPER" --verify-install 2>&1)" \
    || { echo "[FAIL] testpilot --verify-install nonzero:"; echo "$VERIFY_OUT"; exit 1; }
echo "[OK] testpilot --verify-install exited 0"

echo ""
echo "================================================"
echo "  PASS: offline install integration test"
echo "================================================"
