#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TestPilot Managed Installer  (wheel-world model)
#
# Creates or updates a managed TestPilot installation:
#   ~/.local/share/testpilot/.venv     <- runtime virtualenv
#   ~/.local/bin/testpilot             <- wrapper (no source activation needed)
#   ~/.agents/skills/testpilot-normal-test  <- skill sync from installed package
#
# Usage:
#   bash scripts/install.sh [--plugins <csv>] [--offline <bundle.tar.gz>]
#
# Environment variable overrides:
#   TESTPILOT_INSTALL_TOKEN  - GH PAT / OAuth token (preferred)
#   GH_TOKEN                 - fallback token (standard gh CLI env var)
#   TESTPILOT_REF            - git ref to fetch manifest from (default: HEAD)
#   TESTPILOT_HOME           - base for managed install (default: ~/.local/share/testpilot)
#   TESTPILOT_BIN_DIR        - wrapper destination (default: ~/.local/bin)
#   TESTPILOT_SKILLS_DIR     - skill destination (default: ~/.agents/skills)
#   TESTPILOT_MANIFEST       - local file path to override manifest fetch
#
# SECURITY: tokens are NEVER interpolated into URLs or echoed to stdout.
#           GH_TOKEN is exported for `gh` CLI use only.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
# NOTE: xtrace (debug echo) is intentionally NOT enabled — it would expose GH_TOKEN in CI logs.

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

# ── Defaults ─────────────────────────────────────────────────────────────────
TESTPILOT_HOME="${TESTPILOT_HOME:-${HOME}/.local/share/testpilot}"
TESTPILOT_BIN_DIR="${TESTPILOT_BIN_DIR:-${HOME}/.local/bin}"
TESTPILOT_SKILLS_DIR="${TESTPILOT_SKILLS_DIR:-${HOME}/.agents/skills}"
TESTPILOT_REF="${TESTPILOT_REF:-}"
TESTPILOT_MANIFEST="${TESTPILOT_MANIFEST:-}"

VENV="${TESTPILOT_HOME}/.venv"
# Offline rollback cache: install.sh preserves used wheels here so that
# `testpilot --update` rollback can reinstall the last-good set with
# --no-index / --find-links and NEVER reach a public index.
WHEEL_CACHE="${TESTPILOT_HOME}/.wheel-cache"

# ── Arg parsing ───────────────────────────────────────────────────────────────
OFFLINE_BUNDLE=""
SELECTED_PLUGINS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --plugins)
            SELECTED_PLUGINS="${2:-}"
            shift 2
            ;;
        --offline)
            OFFLINE_BUNDLE="${2:-}"
            shift 2
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

# ── Helper: create/refresh managed venv ───────────────────────────────────────
_create_venv() {
    info "Setting up managed virtualenv at ${VENV} ..."
    mkdir -p "$TESTPILOT_HOME"
    if command -v uv >/dev/null 2>&1; then
        uv venv "$VENV" 2>/dev/null || true
    else
        python3 -m venv "$VENV" 2>/dev/null || true
    fi
    # `|| true` keeps creation idempotent (re-running over an existing venv is
    # fine) but must NOT mask a genuinely broken venv: assert the interpreter
    # actually exists and is executable before proceeding.
    [[ -x "${VENV}/bin/python" ]] \
        || fail "Virtualenv creation failed: ${VENV}/bin/python is missing or not executable."
    ok "Virtualenv ready: ${VENV}"
}

# ── Helper: pip install into managed venv ────────────────────────────────────
_venv_pip() {
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "${VENV}/bin/python" "$@"
    else
        "${VENV}/bin/pip" install "$@"
    fi
}

# ── Helper: write wrapper + sync skill (shared by both modes) ─────────────────
_write_wrapper_and_skill() {
    local venv="$1"
    local bin_dir="$2"
    local skills_dir="$3"

    # Wrapper
    info "Creating wrapper at ${bin_dir}/testpilot ..."
    mkdir -p "$bin_dir"
    local console_script="${venv}/bin/testpilot"
    printf '#!/usr/bin/env sh\nexec "%s" "$@"\n' "$console_script" > "${bin_dir}/testpilot"
    chmod +x "${bin_dir}/testpilot"
    ok "Wrapper created (exec ${console_script})"

    # Skill sync via importlib.resources from the installed package (no source tree needed)
    local skill_dst="${skills_dir}/testpilot-normal-test"
    info "Syncing packaged skill -> ${skill_dst} ..."
    mkdir -p "$skills_dir"
    "${venv}/bin/python" -c "
import importlib.resources as r, shutil, pathlib, sys
dst = pathlib.Path(sys.argv[1])
try:
    pkg = r.files('testpilot') / '_skills' / 'testpilot-normal-test'
    if dst.exists():
        shutil.rmtree(str(dst))
    shutil.copytree(str(pkg), str(dst))
except Exception as e:
    print('Skill sync skipped:', e, file=sys.stderr)
    sys.exit(1)
" "$skill_dst" 2>&1 && ok "Skill synced" || warn "Skill not found in installed package (skip)"
}

# ── Helper: migrate legacy installs to the wheel model (best-effort, non-fatal) ─
# Detects and cleans up old user-site / pipx / git-checkout installs so the
# managed venv is the single source of truth. Failures here never abort install.
_run_legacy_migration() {
    local venv="$1"
    info "Checking for legacy testpilot installs to migrate ..."
    "${venv}/bin/testpilot" install-migrate || true
}

# ── Helper: shared post-install verify gate (online AND offline) ──────────────
# The gate MUST run on both paths so a resolved-latest incompatible plugin can
# never be installed by the default online path without a hard failure.
_post_install_gate() {
    local venv="$1"
    info "Running post-install gate: testpilot --verify-install ..."
    "${venv}/bin/testpilot" --verify-install \
        || fail "Post-install gate FAILED. The installation may be incomplete."
    ok "Post-install gate passed"
}

# ── Helper: SDK api_version compatibility (PluginLoader rule) ─────────────────
# compatible iff major equal AND provided(core) minor >= requested(plugin) minor
_api_compatible() {
    local plugin_api="$1" core_api="$2"
    [[ -n "$plugin_api" && -n "$core_api" ]] || return 1
    local p_major="${plugin_api%%.*}" p_minor="${plugin_api#*.}"
    local c_major="${core_api%%.*}" c_minor="${core_api#*.}"
    [[ "$p_major" == "$c_major" ]] || return 1
    [[ "$c_minor" -ge "$p_minor" ]] 2>/dev/null || return 1
}

# ── Helper: read the installed core's SDK API_VERSION from the managed venv ───
# Always returns 0 (empty output = unknown); callers guard with `|| CORE_API=""`.
_installed_core_api() {
    local venv="$1"
    "${venv}/bin/python" -c 'import testpilot.api as a; print(a.API_VERSION)' 2>/dev/null \
        | tr -d '[:space:]' || true
}

# ── Helper: resolve a repo's latest release tag (sans leading v) ──────────────
# Prints the version on success; on failure prints to stderr and returns 1 so
# callers can react deterministically (NOT via `set -e` on a command-sub, which
# bash does not reliably propagate for `var=$(...)` without inherit_errexit).
_resolve_latest_version() {
    local repo="$1" tag
    tag="$(gh release view --repo "$repo" --json tagName --jq .tagName 2>/dev/null)" || tag=""
    if [[ -z "$tag" ]]; then
        echo "[FAIL]  Could not resolve latest release for ${repo} (no release / no access)." >&2
        return 1
    fi
    printf '%s\n' "${tag#v}"
}

# ── Helper: read a release's published api_version metadata (empty if none) ───
# Primary compatibility signal: an `api-version.txt` asset on the plugin release.
# Always returns 0 — a missing asset is a normal "no metadata" outcome.
_read_release_api_version() {
    local repo="$1" tag="$2"
    gh release download "$tag" --repo "$repo" --pattern 'api-version.txt' --output - 2>/dev/null \
        | tr -d '[:space:]' || true
}

# ── Helper: resolve newest API-compatible plugin release ─────────────────────
# Prints the chosen version (sans v) on success. On no-compatible-release it
# prints a detailed reason to stderr and returns 1 (caller aborts). Behavior:
#   - metadata present on candidates: pick newest compatible; else return 1.
#   - no metadata anywhere: fall back to latest (the post-install gate verifies).
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
                printf '%s\n' "${tag#v}"
                return 0
            fi
        fi
    done
    if [[ "$saw_metadata" == "true" ]]; then
        echo "[FAIL]  No API-compatible release for ${repo} (core provides SDK API ${core_api:-unknown}); pin a compatible version with --plugins ${repo##*/}@<ver> or update core." >&2
        return 1
    fi
    # No per-release metadata published yet: install latest; the post-install
    # gate (testpilot --verify-install) is the compatibility backstop.
    _resolve_latest_version "$repo"
}

# ══════════════════════════════════════════════════════════════════════════════
# OFFLINE MODE
# ══════════════════════════════════════════════════════════════════════════════
if [[ -n "$OFFLINE_BUNDLE" ]]; then
    info "Running in OFFLINE mode with bundle: ${OFFLINE_BUNDLE}"
    [[ -f "$OFFLINE_BUNDLE" ]] || fail "Bundle file not found: ${OFFLINE_BUNDLE}"

    # 1. Verify SHA256SUMS sidecar
    # Compare checksums directly using the absolute bundle path (avoids cwd dependency).
    SUMS_FILE="${OFFLINE_BUNDLE}.SHA256SUMS"
    [[ -f "$SUMS_FILE" ]] || fail "SHA256SUMS sidecar not found: ${SUMS_FILE}"
    info "Verifying bundle checksum..."
    EXPECTED_HASH="$(awk 'NR==1{print $1}' "$SUMS_FILE")"
    ACTUAL_HASH="$(sha256sum "$OFFLINE_BUNDLE" | awk '{print $1}')"
    if [[ "$EXPECTED_HASH" != "$ACTUAL_HASH" ]]; then
        fail "Bundle checksum verification FAILED (expected=${EXPECTED_HASH}, got=${ACTUAL_HASH}). Bundle may be corrupt or tampered."
    fi
    ok "Bundle checksum verified"

    # 2. Assert python minor version matches cp<XY> token in bundle name
    BUNDLE_BASENAME="$(basename "$OFFLINE_BUNDLE")"
    if [[ "$BUNDLE_BASENAME" =~ cp([0-9]+) ]]; then
        BUNDLE_PYMINOR="${BASH_REMATCH[1]}"
        # e.g. cp311 -> "311"; compare to running python's "3.11" -> "311"
        RUNNING_PYMINOR="$(python3 -c 'import sys; print(str(sys.version_info.major)+str(sys.version_info.minor))' 2>/dev/null || echo "0")"
        if [[ "$BUNDLE_PYMINOR" != "$RUNNING_PYMINOR" ]]; then
            RUNNING_DOT="$(python3 -c 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))' 2>/dev/null)"
            fail "Python version mismatch: bundle requires cp${BUNDLE_PYMINOR} but running python is ${RUNNING_DOT} (cp${RUNNING_PYMINOR}). Install the correct python version or obtain a matching bundle."
        fi
        ok "Python version matches bundle (cp${BUNDLE_PYMINOR})"
    else
        warn "Bundle name has no cp<XY> token; skipping python version check."
    fi

    # 2b. Assert the bundle's linux-<arch> tag matches this machine's arch
    #     (fail fast BEFORE extraction — a wrong-arch wheelhouse cannot install).
    RUNNING_ARCH="$(uname -m)"
    if [[ "$BUNDLE_BASENAME" =~ linux-([A-Za-z0-9_]+)-cp ]]; then
        BUNDLE_ARCH="${BASH_REMATCH[1]}"
        if [[ "$BUNDLE_ARCH" != "$RUNNING_ARCH" ]]; then
            fail "Architecture mismatch: bundle is for linux-${BUNDLE_ARCH} but this machine is ${RUNNING_ARCH}. Obtain a bundle built for ${RUNNING_ARCH}."
        fi
        ok "Architecture matches bundle (linux-${BUNDLE_ARCH})"
    else
        warn "Bundle name has no linux-<arch> token; skipping architecture check."
    fi

    # 3. Extract bundle
    EXTRACT_DIR="$(mktemp -d)"
    trap 'rm -rf "$EXTRACT_DIR"' EXIT
    info "Extracting bundle to ${EXTRACT_DIR} ..."
    tar -xzf "$OFFLINE_BUNDLE" -C "$EXTRACT_DIR"
    ok "Bundle extracted"

    # Find the wheelhouse inside the extracted dir (may be nested one level)
    WHEELHOUSE=""
    REQ_FILE=""
    if [[ -d "${EXTRACT_DIR}/wheelhouse" ]]; then
        WHEELHOUSE="${EXTRACT_DIR}/wheelhouse"
        REQ_FILE="${EXTRACT_DIR}/requirements.txt"
    else
        # Try one directory level deeper
        for d in "${EXTRACT_DIR}"/*/; do
            if [[ -d "${d}wheelhouse" ]]; then
                WHEELHOUSE="${d}wheelhouse"
                REQ_FILE="${d}requirements.txt"
                break
            fi
        done
    fi
    [[ -n "$WHEELHOUSE" ]] || fail "Could not find 'wheelhouse/' inside extracted bundle."
    [[ -f "$REQ_FILE"   ]] || fail "Could not find 'requirements.txt' inside extracted bundle."

    # 4. Create managed venv
    _create_venv

    # 5. Install from wheelhouse — NO network, NO token
    info "Installing packages from offline wheelhouse (--no-index --find-links) ..."
    _venv_pip --no-index --find-links="$WHEELHOUSE" -r "$REQ_FILE"
    ok "Packages installed from offline bundle"

    # 6. Wrapper + skill sync
    _write_wrapper_and_skill "$VENV" "$TESTPILOT_BIN_DIR" "$TESTPILOT_SKILLS_DIR"

    # 6b. Migrate legacy installs (best-effort, non-fatal)
    _run_legacy_migration "$VENV"

    # 7. Post-install gate (shared with the online path)
    _post_install_gate "$VENV"

else
# ══════════════════════════════════════════════════════════════════════════════
# ONLINE MODE
# ══════════════════════════════════════════════════════════════════════════════

    # 1. Prerequisites
    info "Checking prerequisites..."
    command -v python3 >/dev/null 2>&1 || fail "python3 not found. Please install Python 3.11+."
    command -v gh     >/dev/null 2>&1 || fail "gh (GitHub CLI) not found. Install from https://cli.github.com/"

    PYTHON_VER="$(python3 -c 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))' 2>/dev/null || echo "0.0")"
    PYTHON_MAJOR="${PYTHON_VER%%.*}"
    PYTHON_MINOR="${PYTHON_VER#*.}"
    if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 11 ]]; }; then
        fail "Python 3.11+ required, found ${PYTHON_VER}"
    fi
    ok "Python ${PYTHON_VER}"

    if command -v uv >/dev/null 2>&1; then
        ok "uv found (preferred)"
    else
        warn "uv not found, falling back to pip/venv"
    fi

    # 2. Token handling — NEVER interpolate into URLs; export for gh CLI only
    GH_TOKEN="${TESTPILOT_INSTALL_TOKEN:-${GH_TOKEN:-}}"
    if [[ -n "$GH_TOKEN" ]]; then
        export GH_TOKEN
        ok "GH_TOKEN set (from TESTPILOT_INSTALL_TOKEN or GH_TOKEN env)"
    else
        warn "No GH_TOKEN / TESTPILOT_INSTALL_TOKEN found; gh CLI will use its own auth"
    fi

    # 3. Fetch or use local manifest
    MANIFEST_FILE="$(mktemp)"
    MANIFEST_PARSE_SCRIPT="$(mktemp /tmp/tp_parse.XXXXXX.py)"
    # ASKPASS_HELPER is removed by the EXIT trap so the token-passing helper is
    # cleaned up even when pip fails under `set -euo pipefail` (a function-scoped
    # RETURN trap does NOT fire on a set -e abort; an EXIT trap does).
    ASKPASS_HELPER=""
    # ONLINE_WHEEL_TMP tracks the current per-package wheel download dir so it is
    # removed even when `pip` aborts under `set -euo pipefail` (a function-scoped
    # RETURN trap does NOT fire on a set -e abort; this EXIT trap does).
    ONLINE_WHEEL_TMP=""
    trap 'rm -f "$MANIFEST_FILE" "$MANIFEST_PARSE_SCRIPT" "$ASKPASS_HELPER"; rm -rf "$ONLINE_WHEEL_TMP"' EXIT

    if [[ -n "$TESTPILOT_MANIFEST" ]]; then
        info "Using local manifest override: ${TESTPILOT_MANIFEST}"
        cp "$TESTPILOT_MANIFEST" "$MANIFEST_FILE"
    else
        # Uses GH_TOKEN env internally — token never embedded in URL
        _CORE_REPO_DEFAULT="hamanpaul/testpilot-core"
        REF_PARAM=""
        [[ -n "$TESTPILOT_REF" ]] && REF_PARAM="?ref=${TESTPILOT_REF}"
        info "Fetching install-manifest.yaml from ${_CORE_REPO_DEFAULT}${TESTPILOT_REF:+ @ ${TESTPILOT_REF}}..."
        gh api "repos/${_CORE_REPO_DEFAULT}/contents/install-manifest.yaml${REF_PARAM}" \
            -H "Accept: application/vnd.github.raw" \
            > "$MANIFEST_FILE" \
            || fail "Failed to fetch install-manifest.yaml from ${_CORE_REPO_DEFAULT}"
    fi
    ok "Manifest loaded"

    # 4. Parse manifest with a temp python script (avoids shell quoting issues)
    # Output format (one value per line, prefixed by key):
    #   CORE_REPO=<value>
    #   CORE_VERSION=<value>
    #   PLUGIN=<name>|<repo>|<version>
    #   SW_REPO=<value>
    #   SW_VERSION=<value>
    cat > "$MANIFEST_PARSE_SCRIPT" << 'PYEOF'
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

    # Detect top-level section
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

    PARSED="$(python3 "$MANIFEST_PARSE_SCRIPT" "$MANIFEST_FILE")"

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

    # core version is optional in the manifest: absent => resolve latest release.
    if [[ -z "$CORE_VERSION" ]]; then
        info "core: no pinned version; resolving latest release of ${CORE_REPO} ..."
        CORE_VERSION="$(_resolve_latest_version "$CORE_REPO")" \
            || fail "Could not resolve latest core release for ${CORE_REPO}."
    fi
    info "Core:       ${CORE_REPO} @ ${CORE_VERSION}"

    # serialwrap stays pinned: a declared serialwrap repo MUST carry a version.
    if [[ -n "$SERIALWRAP_REPO" ]]; then
        [[ -n "$SERIALWRAP_VERSION" ]] \
            || fail "serialwrap must be pinned in install-manifest.yaml (missing version)."
        info "Serialwrap: ${SERIALWRAP_REPO} @ ${SERIALWRAP_VERSION} (pinned)"
    fi

    # 5. Create managed venv
    _create_venv

    # ── Helper: download wheel or fall back to git+https via GIT_ASKPASS ─────
    # SECURITY: GIT_ASKPASS helper echoes the token to git's password prompt.
    #           The token is NEVER embedded in the URL or echoed to stdout.
    # with_deps=true  -> install the package WITH its dependency closure
    # with_deps=false -> install with --no-deps (plugins depend on core, which is
    #                    installed first; resolving their deps would re-pull core)
    _install_pkg_online() {
        local repo="$1" version="$2" label="$3" with_deps="${4:-false}"
        local wheel_dir; wheel_dir="$(mktemp -d)"
        # Track for EXIT-trap cleanup so a pip failure under set -e cannot leak it.
        ONLINE_WHEEL_TMP="$wheel_dir"
        local nodeps_flag=""
        [[ "$with_deps" == "true" ]] || nodeps_flag="--no-deps"

        info "Downloading ${label} ${version} from ${repo} ..."

        # Try gh release download first (GH_TOKEN used via env, not URL)
        if gh release download "v${version}" \
                --repo "$repo" \
                --pattern "*.whl" \
                --dir "$wheel_dir" \
                2>/dev/null; then
            ok "Downloaded wheel(s) for ${label}"
            if [[ "$with_deps" == "true" ]]; then
                _venv_pip "$wheel_dir"/*.whl
            else
                _venv_pip --no-deps "$wheel_dir"/*.whl
            fi
            # Preserve the installed wheel(s) into the offline rollback cache so
            # `testpilot --update` rollback can reinstall this set with
            # --no-index (NEVER a public index). Best-effort; never fatal.
            mkdir -p "$WHEEL_CACHE"
            cp "$wheel_dir"/*.whl "$WHEEL_CACHE"/ 2>/dev/null || true
            ok "${label} installed from wheel"
        else
            # Fallback: git+https with GIT_ASKPASS helper (token never in URL)
            warn "No wheel asset for ${label} ${version}; falling back to git+https"
            if [[ -n "${GH_TOKEN:-}" ]]; then
                # Use the script-global ASKPASS_HELPER (cleaned by the EXIT trap)
                # so the helper is removed even if pip fails under set -e.
                ASKPASS_HELPER="$(mktemp /tmp/tp_askpass.XXXXXX)"
                chmod 700 "$ASKPASS_HELPER"
                # Helper reads the token from the EXPORTED env at call time;
                # the literal secret is NEVER written into the helper file.
                printf '#!/bin/sh\nexec printf '\''%%s\\n'\'' "$GH_TOKEN"\n' > "$ASKPASS_HELPER"
                GH_TOKEN="$GH_TOKEN" GIT_ASKPASS="$ASKPASS_HELPER" \
                    "${VENV}/bin/pip" install ${nodeps_flag} \
                    "git+https://github.com/${repo}@v${version}"
                rm -f "$ASKPASS_HELPER"
                ASKPASS_HELPER=""
            else
                "${VENV}/bin/pip" install ${nodeps_flag} \
                    "git+https://github.com/${repo}@v${version}"
            fi
            ok "${label} installed via git+https"
        fi
        rm -rf "$wheel_dir"
        ONLINE_WHEEL_TMP=""
    }

    # 6. Install core first (with its deps), then read its SDK API_VERSION so
    #    plugins can be resolved to the newest release compatible with THIS core.
    _install_pkg_online "$CORE_REPO" "$CORE_VERSION" "core" "true"
    CORE_API="$(_installed_core_api "$VENV")" || CORE_API=""
    if [[ -n "$CORE_API" ]]; then
        info "Core SDK API: ${CORE_API}"
    else
        warn "Could not read core SDK API_VERSION; plugin compatibility relies on the post-install gate"
    fi

    # 7. Install selected (or all) plugins with --no-deps.
    #    Version precedence:  --plugins name@ver  >  manifest version:  >  resolve newest compatible.
    for plugin_entry in "${PLUGIN_ENTRIES[@]:-}"; do
        [[ -z "$plugin_entry" ]] && continue
        IFS='|' read -r pname prepo pver <<< "$plugin_entry"
        [[ -z "$pname" ]] && continue

        # Filter by --plugins (csv of name or name@ver); PIN_VER is the @ver override.
        PIN_VER=""
        if [[ -n "$SELECTED_PLUGINS" ]]; then
            SELECTED="false"
            _OLDIFS="$IFS"; IFS=','
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

        USE_VER="$pver"
        [[ -n "$PIN_VER" ]] && USE_VER="$PIN_VER"
        if [[ -z "$USE_VER" ]]; then
            info "plugin:${pname}: resolving newest compatible release of ${prepo} ..."
            USE_VER="$(_resolve_compatible_plugin "$prepo" "$CORE_API")" \
                || fail "No installable API-compatible release for plugin ${pname} (${prepo}); leaving install unchanged."
        fi
        _install_pkg_online "$prepo" "$USE_VER" "plugin:${pname}" "false"
    done

    # 8. Install serialwrap WITH deps (public; pinned — not flow-latest)
    if [[ -n "$SERIALWRAP_REPO" && -n "$SERIALWRAP_VERSION" ]]; then
        _install_pkg_online "$SERIALWRAP_REPO" "$SERIALWRAP_VERSION" "serialwrap" "true"
    fi

    # 9. Wrapper + skill sync
    _write_wrapper_and_skill "$VENV" "$TESTPILOT_BIN_DIR" "$TESTPILOT_SKILLS_DIR"

    # 10. Migrate legacy installs (best-effort, non-fatal)
    _run_legacy_migration "$VENV"

    # 11. Post-install gate (shared with the offline path) — compatibility backstop
    _post_install_gate "$VENV"

fi  # end ONLINE/OFFLINE branch

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}================================================${RESET}"
echo -e "${BOLD}${GREEN}  TestPilot managed install complete!${RESET}"
echo -e "${BOLD}${GREEN}================================================${RESET}"
echo ""
echo -e "  Venv    : ${VENV}"
echo -e "  Wrapper : ${TESTPILOT_BIN_DIR}/testpilot"
echo -e "  Skills  : ${TESTPILOT_SKILLS_DIR}"
echo ""
echo -e "  Add ${BOLD}${TESTPILOT_BIN_DIR}${RESET} to your PATH if not already present."
echo -e "  Then run: testpilot --version"
echo ""
