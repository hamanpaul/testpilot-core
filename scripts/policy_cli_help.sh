#!/usr/bin/env bash
set -euo pipefail

repo_key="$(pwd | sha256sum | cut -d' ' -f1)"
venv_dir="${TMPDIR:-/tmp}/testpilot-policy-cli-${repo_key}"

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi

"${venv_dir}/bin/python" -m pip install --disable-pip-version-check -e ".[dev]" >/dev/null

"${venv_dir}/bin/python" -m testpilot.cli "$@" | sed 's#Usage: python -m testpilot.cli#Usage: testpilot#g'
