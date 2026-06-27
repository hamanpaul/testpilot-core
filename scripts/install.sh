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

    # 7. Post-install gate
    info "Running post-install gate: testpilot --verify-install ..."
    "${VENV}/bin/testpilot" --verify-install \
        || fail "Post-install gate FAILED. The installation may be incomplete."
    ok "Post-install gate passed"

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
    trap 'rm -f "$MANIFEST_FILE" "$MANIFEST_PARSE_SCRIPT"' EXIT

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

    [[ -n "$CORE_REPO" ]]    || fail "Failed to parse core.repo from manifest"
    [[ -n "$CORE_VERSION" ]] || fail "Failed to parse core.version from manifest"

    info "Core:       ${CORE_REPO} @ ${CORE_VERSION}"
    [[ -n "$SERIALWRAP_REPO" ]] && info "Serialwrap: ${SERIALWRAP_REPO} @ ${SERIALWRAP_VERSION}"

    # 5. Create managed venv
    _create_venv

    # ── Helper: download wheel or fall back to git+https via GIT_ASKPASS ─────
    # SECURITY: GIT_ASKPASS helper echoes the token to git's password prompt.
    #           The token is NEVER embedded in the URL or echoed to stdout.
    _install_pkg_online() {
        local repo="$1" version="$2" label="$3" is_core="${4:-false}"
        local wheel_dir; wheel_dir="$(mktemp -d)"

        info "Downloading ${label} ${version} from ${repo} ..."

        # Try gh release download first (GH_TOKEN used via env, not URL)
        if gh release download "v${version}" \
                --repo "$repo" \
                --pattern "*.whl" \
                --dir "$wheel_dir" \
                2>/dev/null; then
            ok "Downloaded wheel(s) for ${label}"
            if [[ "$is_core" == "true" ]]; then
                _venv_pip "$wheel_dir"/*.whl
            else
                _venv_pip --no-deps "$wheel_dir"/*.whl
            fi
            ok "${label} installed from wheel"
        else
            # Fallback: git+https with GIT_ASKPASS helper (token never in URL)
            warn "No wheel asset for ${label} ${version}; falling back to git+https"
            local askpass_helper=""
            if [[ -n "${GH_TOKEN:-}" ]]; then
                askpass_helper="$(mktemp /tmp/tp_askpass.XXXXXX)"
                chmod 700 "$askpass_helper"
                # Write a helper that echoes the token; git calls this for password
                printf '#!/bin/sh\necho "%s"\n' "$GH_TOKEN" > "$askpass_helper"
                GIT_ASKPASS="$askpass_helper" \
                    "${VENV}/bin/pip" install \
                    "git+https://github.com/${repo}@v${version}"
                rm -f "$askpass_helper"
            else
                "${VENV}/bin/pip" install \
                    "git+https://github.com/${repo}@v${version}"
            fi
            ok "${label} installed via git+https"
        fi
        rm -rf "$wheel_dir"
    }

    # 6. Install core first (with its deps)
    _install_pkg_online "$CORE_REPO" "$CORE_VERSION" "core" "true"

    # 7. Install selected (or all) plugins with --no-deps
    for plugin_entry in "${PLUGIN_ENTRIES[@]:-}"; do
        [[ -z "$plugin_entry" ]] && continue
        IFS='|' read -r pname prepo pver <<< "$plugin_entry"
        [[ -z "$pname" ]] && continue

        # Filter by --plugins csv if provided
        if [[ -n "$SELECTED_PLUGINS" ]]; then
            if ! echo ",$SELECTED_PLUGINS," | grep -q ",${pname},"; then
                info "Skipping plugin ${pname} (not in --plugins list)"
                continue
            fi
        fi
        _install_pkg_online "$prepo" "$pver" "plugin:${pname}" "false"
    done

    # 8. Install serialwrap with --no-deps
    if [[ -n "$SERIALWRAP_REPO" && -n "$SERIALWRAP_VERSION" ]]; then
        _install_pkg_online "$SERIALWRAP_REPO" "$SERIALWRAP_VERSION" "serialwrap" "false"
    fi

    # 9. Wrapper + skill sync
    _write_wrapper_and_skill "$VENV" "$TESTPILOT_BIN_DIR" "$TESTPILOT_SKILLS_DIR"

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
