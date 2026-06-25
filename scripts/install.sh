#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# TestPilot Managed Installer
#
# Creates or updates a managed TestPilot installation:
#   ~/.local/share/testpilot/src       ← managed checkout
#   ~/.local/share/testpilot/.venv     ← runtime virtualenv
#   ~/.local/bin/testpilot             ← wrapper (no source activation needed)
#   ~/.agents/skills/testpilot-normal-test  ← skill sync
#   serialwrap from git                ← serialwrap install/update
#
# Usage:
#   bash scripts/install.sh
#   # Or with overrides:
#   TESTPILOT_REPO_URL=file:///path/to/local/testpilot bash scripts/install.sh
#
# Environment variable overrides:
#   TESTPILOT_REPO_URL       – source repo (default: https://github.com/paulc-arc/testpilot.git)
#   TESTPILOT_REF            – branch/tag/commit, or "latest-release" (default: latest-release)
#   TESTPILOT_HOME           – base for managed install (default: ~/.local/share/testpilot)
#   TESTPILOT_BIN_DIR        – wrapper destination (default: ~/.local/bin)
#   TESTPILOT_SKILLS_DIR     – skill destination (default: ~/.agents/skills)
#   SERIALWRAP_REPO_URL      – serialwrap source (default: https://github.com/paulc-arc/serialwrap.git)
#   SERIALWRAP_INSTALL_DIR   – serialwrap checkout root (default: ~/.local/share/serialwrap)
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
fail()  { echo -e "${RED}[FAIL]${RESET}  $*"; exit 1; }

# ── Defaults ─────────────────────────────────────────────────────────────────
TESTPILOT_REPO_URL="${TESTPILOT_REPO_URL:-https://github.com/paulc-arc/testpilot.git}"
TESTPILOT_REF="${TESTPILOT_REF:-latest-release}"
TESTPILOT_HOME="${TESTPILOT_HOME:-${HOME}/.local/share/testpilot}"
TESTPILOT_BIN_DIR="${TESTPILOT_BIN_DIR:-${HOME}/.local/bin}"
TESTPILOT_SKILLS_DIR="${TESTPILOT_SKILLS_DIR:-${HOME}/.agents/skills}"
SERIALWRAP_REPO_URL="${SERIALWRAP_REPO_URL:-https://github.com/paulc-arc/serialwrap.git}"
SERIALWRAP_INSTALL_DIR="${SERIALWRAP_INSTALL_DIR:-${HOME}/.local/share/serialwrap}"

MANAGED_SRC="${TESTPILOT_HOME}/src"
MANAGED_VENV="${TESTPILOT_HOME}/.venv"
SERIALWRAP_SRC="${SERIALWRAP_INSTALL_DIR}/src"

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v git     >/dev/null 2>&1 || fail "git not found. Please install git."
command -v python3 >/dev/null 2>&1 || fail "python3 not found. Please install Python 3.11+."

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PYTHON_MAJOR="${PYTHON_VER%%.*}"
PYTHON_MINOR="${PYTHON_VER#*.}"
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    fail "Python 3.11+ required, found $PYTHON_VER"
fi
ok "Python $PYTHON_VER"

# Prefer uv
USE_UV=false
if command -v uv >/dev/null 2>&1; then
    USE_UV=true
    ok "uv found (preferred)"
else
    warn "uv not found, using pip/venv"
fi

# ── 2. Resolve latest-release ref ─────────────────────────────────────────────
if [ "$TESTPILOT_REF" = "latest-release" ]; then
    info "Resolving latest-release from $TESTPILOT_REPO_URL ..."
    RESOLVED=$(
        git ls-remote --tags "$TESTPILOT_REPO_URL" 'refs/tags/v[0-9]*.[0-9]*.[0-9]*' \
        | grep -v '\^{}' \
        | awk '{print $2}' \
        | sort -V \
        | tail -1 \
        | sed 's|refs/tags/||'
    )
    if [ -z "$RESOLVED" ]; then
        warn "No stable vX.Y.Z tag found; falling back to main"
        TESTPILOT_REF="main"
    else
        TESTPILOT_REF="$RESOLVED"
        ok "Resolved latest-release → $TESTPILOT_REF"
    fi
fi

info "Installing TestPilot ref: $TESTPILOT_REF from $TESTPILOT_REPO_URL"

# ── 3. Managed checkout ───────────────────────────────────────────────────────
if [ -d "$MANAGED_SRC/.git" ]; then
    info "Updating managed checkout at $MANAGED_SRC ..."
    git -C "$MANAGED_SRC" fetch origin
    git -C "$MANAGED_SRC" checkout "$TESTPILOT_REF"
    # Fast-forward local branch to origin; silently skips for tags/commit SHAs.
    git -C "$MANAGED_SRC" merge --ff-only "origin/$TESTPILOT_REF" 2>/dev/null || \
        warn "testpilot fast-forward failed (expected for tag/SHA refs; diverged branch may need manual reset)"
    ok "Managed checkout updated to $TESTPILOT_REF"
else
    info "Cloning $TESTPILOT_REPO_URL → $MANAGED_SRC ..."
    mkdir -p "$(dirname "$MANAGED_SRC")"
    git clone "$TESTPILOT_REPO_URL" "$MANAGED_SRC"
    git -C "$MANAGED_SRC" checkout "$TESTPILOT_REF"
    ok "Managed checkout created"
fi

# ── 4. Managed virtualenv + TestPilot install ─────────────────────────────────
info "Setting up managed virtualenv at $MANAGED_VENV ..."
if $USE_UV; then
    if [ ! -d "$MANAGED_VENV/bin" ]; then
        uv venv "$MANAGED_VENV"
    fi
    uv pip install --python "$MANAGED_VENV/bin/python" -e "$MANAGED_SRC" \
        -e "$MANAGED_SRC/plugins/wifi_llapi" -e "$MANAGED_SRC/plugins/brcm_fw_upgrade"
else
    if [ ! -d "$MANAGED_VENV/bin" ]; then
        python3 -m venv "$MANAGED_VENV"
    fi
    "$MANAGED_VENV/bin/pip" install -e "$MANAGED_SRC" \
        -e "$MANAGED_SRC/plugins/wifi_llapi" -e "$MANAGED_SRC/plugins/brcm_fw_upgrade"
fi
ok "Managed virtualenv ready"

# ── 5. Wrapper at TESTPILOT_BIN_DIR/testpilot ────────────────────────────────
info "Creating wrapper at $TESTPILOT_BIN_DIR/testpilot ..."
mkdir -p "$TESTPILOT_BIN_DIR"
# Use printf to avoid heredoc quoting issues; hardcode absolute venv path.
CONSOLE_SCRIPT="${MANAGED_VENV}/bin/testpilot"
printf '#!/usr/bin/env sh\nexec "%s" "$@"\n' "$CONSOLE_SCRIPT" > "$TESTPILOT_BIN_DIR/testpilot"
chmod +x "$TESTPILOT_BIN_DIR/testpilot"
ok "Wrapper created (exec $CONSOLE_SCRIPT)"

# ── 6. Skill sync ────────────────────────────────────────────────────────────
SKILL_SRC="$MANAGED_SRC/skills/testpilot-normal-test"
SKILL_DST="$TESTPILOT_SKILLS_DIR/testpilot-normal-test"
if [ -d "$SKILL_SRC" ]; then
    info "Syncing skill testpilot-normal-test → $SKILL_DST ..."
    mkdir -p "$TESTPILOT_SKILLS_DIR"
    rm -rf "$SKILL_DST"
    cp -r "$SKILL_SRC" "$SKILL_DST"
    ok "Skill synced"
else
    warn "Skill source not found at $SKILL_SRC (skip skill sync)"
fi

# ── 7. Serialwrap install/update ──────────────────────────────────────────────
info "Installing/updating serialwrap from $SERIALWRAP_REPO_URL ..."
if [ -d "$SERIALWRAP_SRC/.git" ]; then
    git -C "$SERIALWRAP_SRC" fetch origin
    SERIALWRAP_BRANCH=$(git -C "$SERIALWRAP_SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    if [ -z "$SERIALWRAP_BRANCH" ] || [ "$SERIALWRAP_BRANCH" = "HEAD" ]; then
        SERIALWRAP_BRANCH="main"
    fi
    git -C "$SERIALWRAP_SRC" merge --ff-only "origin/$SERIALWRAP_BRANCH" 2>/dev/null || \
        warn "serialwrap fast-forward failed; manual update may be needed"
    ok "serialwrap updated"
else
    mkdir -p "$(dirname "$SERIALWRAP_SRC")"
    git clone "$SERIALWRAP_REPO_URL" "$SERIALWRAP_SRC"
    ok "serialwrap cloned"
fi

if $USE_UV; then
    uv pip install --python "$MANAGED_VENV/bin/python" -e "$SERIALWRAP_SRC" 2>/dev/null || \
        warn "serialwrap install into managed venv failed (may need manual fix)"
else
    "$MANAGED_VENV/bin/pip" install -e "$SERIALWRAP_SRC" 2>/dev/null || \
        warn "serialwrap install into managed venv failed (may need manual fix)"
fi

# ── 8. Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  TestPilot managed install complete!${RESET}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════${RESET}"
echo ""
echo -e "  Checkout : $MANAGED_SRC"
echo -e "  Venv     : $MANAGED_VENV"
echo -e "  Wrapper  : $TESTPILOT_BIN_DIR/testpilot"
echo -e "  Skill    : $SKILL_DST"
echo ""
echo -e "  Add ${BOLD}$TESTPILOT_BIN_DIR${RESET} to your PATH if not already present."
echo -e "  Then run: testpilot --version"
echo ""
