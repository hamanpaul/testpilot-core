#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TestPilot Offline Bundle Builder
#
# Produces a self-contained offline install bundle:
#   testpilot-bundle-<version>-linux-<arch>-cp<pyminor>.tar.gz
#   testpilot-bundle-<version>-linux-<arch>-cp<pyminor>.tar.gz.SHA256SUMS
#
# Usage:
#   bash scripts/build-bundle.sh [--manifest <path>] [--plugins <csv>]
#
# Requirements:
#   - Runs on a networked Linux box matching the target python minor
#   - gh CLI authenticated (GH_TOKEN or gh auth login)
#   - python3 (3.11+), pip, uv (optional)
#
# SECURITY: wheels are downloaded from GitHub Releases — NEVER rebuilt locally.
#           Reason: hatchling is not byte-reproducible; only pinned release
#           artifacts can be reliably verified offline.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

info()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
fail()  { echo -e "${RED}[FAIL]${RESET}  $*" >&2; exit 1; }

# ── Arg parsing ───────────────────────────────────────────────────────────────
MANIFEST_PATH=""
SELECTED_PLUGINS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest)
            MANIFEST_PATH="${2:-}"
            shift 2
            ;;
        --plugins)
            SELECTED_PLUGINS="${2:-}"
            shift 2
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

# ── Default manifest to repo root ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
[[ -z "$MANIFEST_PATH" ]] && MANIFEST_PATH="${REPO_ROOT}/install-manifest.yaml"
[[ -f "$MANIFEST_PATH" ]] || fail "Manifest not found: ${MANIFEST_PATH}"

# ── Prerequisites ─────────────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || fail "python3 not found"
command -v pip    >/dev/null 2>&1 || fail "pip not found"
command -v gh     >/dev/null 2>&1 || fail "gh (GitHub CLI) not found"
command -v tar    >/dev/null 2>&1 || fail "tar not found"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum not found"
ok "Prerequisites satisfied"

# ── Python minor version (for bundle filename) ────────────────────────────────
PYMINOR="$(python3 -c 'import sys; print(str(sys.version_info.major)+str(sys.version_info.minor))')"
ARCH="$(uname -m)"

# ── Parse manifest ────────────────────────────────────────────────────────────
info "Parsing manifest: ${MANIFEST_PATH}"

PARSE_SCRIPT="$(mktemp /tmp/tp_bundle_parse.XXXXXX.py)"
trap 'rm -f "$PARSE_SCRIPT"' EXIT

cat > "$PARSE_SCRIPT" << 'PYEOF'
import re, sys

manifest_path = sys.argv[1]
text = open(manifest_path).read()

section = None
core = {}
plugins = []
cur_plugin = {}
serialwrap = {}

for raw_line in text.split('\n'):
    line = raw_line

    if re.match(r'^core:', line):
        if cur_plugin:
            plugins.append(cur_plugin); cur_plugin = {}
        section = 'core'; continue
    if re.match(r'^plugins:', line):
        if cur_plugin:
            plugins.append(cur_plugin); cur_plugin = {}
        section = 'plugins'; continue
    if re.match(r'^serialwrap:', line):
        if cur_plugin:
            plugins.append(cur_plugin); cur_plugin = {}
        section = 'serialwrap'; continue

    if section == 'core':
        m = re.match(r'\s+repo:\s+(\S+)', line)
        if m: core['repo'] = m.group(1)
        m = re.match(r'\s+version:\s+["\']?([0-9][^\s"\']*)["\']?', line)
        if m: core['version'] = m.group(1)

    elif section == 'plugins':
        m = re.match(r'\s+-\s+name:\s+(\S+)', line)
        if m:
            if cur_plugin: plugins.append(cur_plugin)
            cur_plugin = {'name': m.group(1)}
            continue
        if cur_plugin:
            m = re.match(r'\s+repo:\s+(\S+)', line)
            if m: cur_plugin['repo'] = m.group(1)
            m = re.match(r'\s+version:\s+["\']?([0-9][^\s"\']*)["\']?', line)
            if m: cur_plugin['version'] = m.group(1)

    elif section == 'serialwrap':
        m = re.match(r'\s+repo:\s+(\S+)', line)
        if m: serialwrap['repo'] = m.group(1)
        m = re.match(r'\s+version:\s+["\']?([0-9][^\s"\']*)["\']?', line)
        if m: serialwrap['version'] = m.group(1)

if cur_plugin:
    plugins.append(cur_plugin)

print(f"CORE_REPO={core.get('repo','')}")
print(f"CORE_VERSION={core.get('version','')}")
for p in plugins:
    print(f"PLUGIN={p.get('name','')}|{p.get('repo','')}|{p.get('version','')}")
if serialwrap:
    print(f"SW_REPO={serialwrap.get('repo','')}")
    print(f"SW_VERSION={serialwrap.get('version','')}")
PYEOF

PARSED="$(python3 "$PARSE_SCRIPT" "$MANIFEST_PATH")"

CORE_REPO=""
CORE_VERSION=""
SERIALWRAP_REPO=""
SERIALWRAP_VERSION=""
declare -a PLUGIN_ENTRIES=()

while IFS= read -r parsed_line; do
    case "$parsed_line" in
        CORE_REPO=*)      CORE_REPO="${parsed_line#CORE_REPO=}" ;;
        CORE_VERSION=*)   CORE_VERSION="${parsed_line#CORE_VERSION=}" ;;
        PLUGIN=*)         PLUGIN_ENTRIES+=("${parsed_line#PLUGIN=}") ;;
        SW_REPO=*)        SERIALWRAP_REPO="${parsed_line#SW_REPO=}" ;;
        SW_VERSION=*)     SERIALWRAP_VERSION="${parsed_line#SW_VERSION=}" ;;
    esac
done <<< "$PARSED"

[[ -n "$CORE_REPO" ]]    || fail "Failed to parse core.repo from manifest"
[[ -n "$CORE_VERSION" ]] || fail "Failed to parse core.version from manifest"

info "Core: ${CORE_REPO} @ ${CORE_VERSION}"
[[ -n "$SERIALWRAP_REPO" ]] && info "Serialwrap: ${SERIALWRAP_REPO} @ ${SERIALWRAP_VERSION}"

# ── Stage dir ─────────────────────────────────────────────────────────────────
BUNDLE_NAME="testpilot-bundle-${CORE_VERSION}-linux-${ARCH}-cp${PYMINOR}"
STAGE_DIR="$(mktemp -d)"
WHEELHOUSE="${STAGE_DIR}/wheelhouse"
mkdir -p "$WHEELHOUSE"
info "Staging dir: ${STAGE_DIR}"

# Ensure stage dir is cleaned on failure (but NOT on success — we tar it)
CLEANUP_STAGE=true
trap 'if $CLEANUP_STAGE; then rm -rf "$STAGE_DIR"; fi; rm -f "$PARSE_SCRIPT"' EXIT

# ── Download release wheels (NEVER rebuild — hatchling is not byte-reproducible)
_download_wheel() {
    local repo="$1" version="$2" label="$3"
    info "Downloading wheel: ${label} ${version} from ${repo} ..."
    gh release download "v${version}" \
        --repo "$repo" \
        --pattern "*.whl" \
        --dir "$WHEELHOUSE" \
        || fail "Failed to download wheel for ${label} ${version} from ${repo}"
    ok "Wheel downloaded: ${label}"
}

# Core
_download_wheel "$CORE_REPO" "$CORE_VERSION" "core"

# Plugins
for plugin_entry in "${PLUGIN_ENTRIES[@]:-}"; do
    [[ -z "$plugin_entry" ]] && continue
    IFS='|' read -r pname prepo pver <<< "$plugin_entry"
    [[ -z "$pname" ]] && continue

    if [[ -n "$SELECTED_PLUGINS" ]]; then
        if ! echo ",$SELECTED_PLUGINS," | grep -q ",${pname},"; then
            info "Skipping plugin ${pname} (not in --plugins list)"
            continue
        fi
    fi
    _download_wheel "$prepo" "$pver" "plugin:${pname}"
done

# Serialwrap
if [[ -n "$SERIALWRAP_REPO" && -n "$SERIALWRAP_VERSION" ]]; then
    _download_wheel "$SERIALWRAP_REPO" "$SERIALWRAP_VERSION" "serialwrap"
fi

# ── Download third-party deps (binary only, for current platform) ─────────────
# The closure is resolved for the active platform and python version.
# Known direct dependencies of testpilot-core; transitive deps resolved by pip.
THIRD_PARTY_DEPS="pyyaml click rich openpyxl ruamel.yaml"
info "Downloading third-party deps (binary only): ${THIRD_PARTY_DEPS}"
pip download --only-binary=:all: --dest "$WHEELHOUSE" $THIRD_PARTY_DEPS \
    || warn "Some third-party deps could not be downloaded as binary wheels (may need to build from source on target)"

# ── Generate pinned requirements.txt ─────────────────────────────────────────
# Derive from wheel filenames: <name>-<version>-*.whl -> name==version
info "Generating pinned requirements.txt from wheelhouse..."
REQ_FILE="${STAGE_DIR}/requirements.txt"
python3 - "$WHEELHOUSE" "$REQ_FILE" << 'PYEOF'
import sys, pathlib, re

wheelhouse = pathlib.Path(sys.argv[1])
req_file = sys.argv[2]

lines = []
for whl in sorted(wheelhouse.glob("*.whl")):
    # Wheel filename: {distribution}-{version}-{python}-{abi}-{platform}.whl
    m = re.match(r'^([A-Za-z0-9_.-]+?)-([0-9][^-]*)-', whl.name)
    if m:
        # Normalize distribution name (replace _ with - per PEP 427)
        dist = m.group(1).replace('_', '-')
        ver = m.group(2)
        lines.append(f"{dist}=={ver}")

lines.sort()
with open(req_file, 'w') as f:
    f.write('\n'.join(lines) + '\n')
print(f"requirements.txt written ({len(lines)} entries)")
PYEOF
ok "requirements.txt generated: ${REQ_FILE}"

# ── Copy packaged skill (if present in repo) ──────────────────────────────────
SKILL_SRC="${REPO_ROOT}/skills/testpilot-normal-test"
if [[ -d "$SKILL_SRC" ]]; then
    info "Copying skill: testpilot-normal-test ..."
    cp -r "$SKILL_SRC" "${STAGE_DIR}/testpilot-normal-test"
    ok "Skill copied"
else
    warn "Skill not found at ${SKILL_SRC} (will not be included in bundle)"
fi

# ── Copy testbed.yaml.example (if present) ────────────────────────────────────
# HARD-EXCLUDE configs/testbed.yaml (operator live config), root *.xlsx, compare-*
TESTBED_EXAMPLE=""
for candidate in \
        "${REPO_ROOT}/plugins/wifi_llapi/testbed.yaml.example" \
        "${REPO_ROOT}/testbed.yaml.example"; do
    if [[ -f "$candidate" ]]; then
        TESTBED_EXAMPLE="$candidate"
        break
    fi
done
if [[ -n "$TESTBED_EXAMPLE" ]]; then
    info "Copying testbed.yaml.example ..."
    cp "$TESTBED_EXAMPLE" "${STAGE_DIR}/testbed.yaml.example"
    ok "testbed.yaml.example copied"
fi

# ── DRY-RUN GATE: verify the wheelhouse actually installs cleanly ─────────────
info "Dry-run gate: testing offline install in a throwaway venv..."
DRY_VENV="$(mktemp -d)/dryrun_venv"
python3 -m venv "$DRY_VENV"

# If this fails, abort WITHOUT producing a tarball
if ! "$DRY_VENV/bin/pip" install \
        --no-index \
        --find-links="$WHEELHOUSE" \
        -r "$REQ_FILE" \
        --quiet; then
    fail "DRY-RUN GATE FAILED: offline install check did not succeed. Bundle NOT produced. Fix missing wheels and retry."
fi
ok "Dry-run gate passed"
rm -rf "$(dirname "$DRY_VENV")"

# ── Produce tarball ───────────────────────────────────────────────────────────
TARBALL="${BUNDLE_NAME}.tar.gz"
info "Producing bundle tarball: ${TARBALL} ..."
(cd "$STAGE_DIR" && tar czf "${OLDPWD}/${TARBALL}" .)
ok "Bundle created: ${TARBALL}"

# ── SHA256SUMS sidecar ────────────────────────────────────────────────────────
SUMS_FILE="${TARBALL}.SHA256SUMS"
sha256sum "$TARBALL" > "$SUMS_FILE"
ok "SHA256SUMS written: ${SUMS_FILE}"

# Do not cleanup stage on success
CLEANUP_STAGE=false

echo ""
echo -e "${BOLD}${GREEN}================================================${RESET}"
echo -e "${BOLD}${GREEN}  Bundle build complete!${RESET}"
echo -e "${BOLD}${GREEN}================================================${RESET}"
echo ""
echo -e "  Bundle   : ${TARBALL}"
echo -e "  Checksum : ${SUMS_FILE}"
echo -e "  Python   : cp${PYMINOR}"
echo -e "  Arch     : ${ARCH}"
echo ""
echo -e "  Install with:"
echo -e "    bash scripts/install.sh --offline ${TARBALL}"
echo ""
