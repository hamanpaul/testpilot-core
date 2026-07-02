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

[[ -n "$CORE_REPO" ]] || fail "Failed to parse core.repo from manifest"

# ── Helper: resolve a repo's latest release tag (sans leading v) ──────────────
# core/plugins may be unpinned in the manifest: resolve latest at build time so
# the bundle snapshots the current release set. serialwrap stays pinned.
# Compatibility of the resolved set is enforced by the dry-run gate below and by
# the post-install verify gate when the bundle is later installed offline.
# Prints version on success; on failure prints to stderr and returns 1 (callers
# guard with `|| fail` — `set -e` does not reliably abort on `var=$(...)`).
_resolve_latest_version() {
    local repo="$1" tag
    tag="$(gh release view --repo "$repo" --json tagName --jq .tagName 2>/dev/null)" || tag=""
    if [[ -z "$tag" ]]; then
        echo "[FAIL]  Could not resolve latest release for ${repo} (no release / no access)." >&2
        return 1
    fi
    printf '%s\n' "${tag#v}"
}

# SDK api_version compatibility (PluginLoader rule): major equal AND core.minor >= plugin.minor.
_api_compatible() {
    local plugin_api="$1" core_api="$2"
    [[ -n "$plugin_api" && -n "$core_api" ]] || return 1
    local p_major="${plugin_api%%.*}" p_minor="${plugin_api#*.}"
    local c_major="${core_api%%.*}" c_minor="${core_api#*.}"
    [[ "$p_major" == "$c_major" ]] || return 1
    [[ "$c_minor" -ge "$p_minor" ]] 2>/dev/null || return 1
}

# Read core's SDK API_VERSION from a downloaded core wheel (no install). Always returns 0.
_read_wheel_api_version() {
    python3 - "$1" <<'PY' 2>/dev/null || true
import sys, zipfile, re
try:
    with zipfile.ZipFile(sys.argv[1]) as z:
        for n in z.namelist():
            if n.endswith("testpilot/api/__init__.py"):
                m = re.search(r'API_VERSION\s*=\s*["\']([0-9]+\.[0-9]+)', z.read(n).decode("utf-8", "replace"))
                if m:
                    print(m.group(1)); break
except Exception:
    pass
PY
}

# Read a plugin release's published api_version metadata asset (empty if none). Always returns 0.
_read_release_api_version() {
    gh release download "$2" --repo "$1" --pattern 'api-version.txt' --output - 2>/dev/null \
        | tr -d '[:space:]' || true
}

# Resolve the newest API-compatible plugin release (sans v). Prints version, else return 1 + stderr.
_resolve_compatible_plugin() {
    local repo="$1" core_api="$2"
    local -a tags
    mapfile -t tags < <(gh release list --repo "$repo" --json tagName --jq '.[].tagName' 2>/dev/null)
    if [[ "${#tags[@]}" -eq 0 ]]; then
        echo "[FAIL]  Could not list releases for ${repo} (no release / no access)." >&2
        return 1
    fi
    local saw_metadata="false" tag api
    for tag in "${tags[@]}"; do
        api="$(_read_release_api_version "$repo" "$tag")"
        if [[ -n "$api" ]]; then
            saw_metadata="true"
            if _api_compatible "$api" "$core_api"; then
                printf '%s\n' "${tag#v}"; return 0
            fi
        fi
    done
    if [[ "$saw_metadata" == "true" ]]; then
        echo "[FAIL]  No API-compatible release for ${repo} (core provides SDK API ${core_api:-unknown})." >&2
        return 1
    fi
    _resolve_latest_version "$repo"   # no metadata anywhere: fall back to latest (gate backstops)
}

if [[ -z "$CORE_VERSION" ]]; then
    info "core: no pinned version; resolving latest release of ${CORE_REPO} ..."
    CORE_VERSION="$(_resolve_latest_version "$CORE_REPO")" \
        || fail "Could not resolve latest core release for ${CORE_REPO}."
fi
info "Core: ${CORE_REPO} @ ${CORE_VERSION}"

if [[ -n "$SERIALWRAP_REPO" ]]; then
    [[ -n "$SERIALWRAP_VERSION" ]] \
        || fail "serialwrap must be pinned in install-manifest.yaml (missing version)."
    info "Serialwrap: ${SERIALWRAP_REPO} @ ${SERIALWRAP_VERSION} (pinned)"
fi

# Records "name|repo|version" for the resolved plugin set (provenance manifest).
declare -a RESOLVED_PLUGINS=()

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

# Core — download first, then read its SDK API_VERSION so plugins resolve to the
# newest release compatible with THIS core (mirrors the installer's resolution).
_download_wheel "$CORE_REPO" "$CORE_VERSION" "core"
CORE_API=""
CORE_WHEEL="$(ls "$WHEELHOUSE"/testpilot_core-*.whl 2>/dev/null | head -1 || true)"
[[ -n "$CORE_WHEEL" ]] && CORE_API="$(_read_wheel_api_version "$CORE_WHEEL")"
if [[ -n "$CORE_API" ]]; then
    info "Core SDK API: ${CORE_API}"
else
    warn "Could not read core SDK API_VERSION from wheel; unpinned plugins fall back to latest (build-time gate backstops)"
fi

# Plugins — pinned version wins; otherwise resolve newest API-compatible release.
for plugin_entry in "${PLUGIN_ENTRIES[@]:-}"; do
    [[ -z "$plugin_entry" ]] && continue
    IFS='|' read -r pname prepo pver <<< "$plugin_entry"
    [[ -z "$pname" ]] && continue

    # Selection filter accepts `name` or `name@ver` (the @ver suffix pins), matching install.sh.
    PIN_VER=""
    if [[ -n "$SELECTED_PLUGINS" ]]; then
        SELECTED="false"; _OLDIFS="$IFS"; IFS=','
        for _sel in $SELECTED_PLUGINS; do
            _sname="${_sel%@*}"
            if [[ "$_sname" == "$pname" ]]; then
                SELECTED="true"
                [[ "$_sel" == *@* ]] && PIN_VER="${_sel#*@}"
                break
            fi
        done
        IFS="$_OLDIFS"
        if [[ "$SELECTED" != "true" ]]; then
            info "Skipping plugin ${pname} (not in --plugins list)"
            continue
        fi
    fi
    [[ -n "$PIN_VER" ]] && pver="$PIN_VER"
    if [[ -z "$pver" ]]; then
        info "plugin:${pname}: resolving newest compatible release of ${prepo} ..."
        pver="$(_resolve_compatible_plugin "$prepo" "$CORE_API")" \
            || fail "No installable API-compatible release for plugin ${pname} (${prepo})."
    fi
    _download_wheel "$prepo" "$pver" "plugin:${pname}"
    RESOLVED_PLUGINS+=("${pname}|${prepo}|${pver}")
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

# ── resolved-manifest.yaml — provenance of the exact versions this bundle pins ─
info "Writing resolved-manifest.yaml (provenance) ..."
{
    echo "# Auto-generated by build-bundle.sh — exact versions snapshotted in this bundle."
    echo "core:"
    echo "  repo: ${CORE_REPO}"
    echo "  version: \"${CORE_VERSION}\""
    echo "plugins:"
    for _entry in "${RESOLVED_PLUGINS[@]:-}"; do
        [[ -z "$_entry" ]] && continue
        IFS='|' read -r _rp_name _rp_repo _rp_ver <<< "$_entry"
        echo "  - name: ${_rp_name}"
        echo "    repo: ${_rp_repo}"
        echo "    version: \"${_rp_ver}\""
    done
    if [[ -n "$SERIALWRAP_REPO" ]]; then
        echo "serialwrap:"
        echo "  repo: ${SERIALWRAP_REPO}"
        echo "  version: \"${SERIALWRAP_VERSION}\""
    fi
} > "${STAGE_DIR}/resolved-manifest.yaml"
ok "resolved-manifest.yaml written"

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

# ── BUILD-TIME API-COMPAT GATE ────────────────────────────────────────────────
# Enforce plugin<->core SDK API compatibility on the RESOLVED wheels now, so an
# incompatible latest plugin fails the build rather than only the air-gapped
# target. Loads each installed plugin entry point and applies the PluginLoader
# rule against the installed core API_VERSION.
info "Build-time plugin API-compat gate ..."
if ! "$DRY_VENV/bin/python" - <<'PYEOF'
import sys
from importlib.metadata import entry_points
try:
    from testpilot.api import API_VERSION
    from testpilot.core.plugin_loader import _check_api_compat
    from testpilot.core.plugin_base import IncompatiblePluginError
except Exception as exc:  # core import failure is itself a bundle defect
    print(f"cannot import core SDK: {exc}", file=sys.stderr)
    sys.exit(1)
bad = []
for ep in entry_points(group="testpilot.plugins"):
    try:
        cls = ep.load()
        _check_api_compat(ep.name, getattr(cls, "api_version", None), API_VERSION)
    except IncompatiblePluginError as exc:
        bad.append(str(exc))
    except Exception as exc:
        bad.append(f"{ep.name}: load error: {exc}")
if bad:
    print("; ".join(bad), file=sys.stderr)
    sys.exit(1)
PYEOF
then
    fail "BUILD-TIME API-COMPAT GATE FAILED: a resolved plugin is not API-compatible with the resolved core. Bundle NOT produced. Pin a compatible plugin or update core."
fi
ok "Build-time API-compat gate passed"
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
