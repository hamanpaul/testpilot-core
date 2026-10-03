# Combined result-stability core verification

The feature integration branch is frozen at `db50f9b68163ac418ae3891dc19acce6bad53aaa` for code verification. It combines terminal-command safety from `4477c867`, bounded serialwrap recovery and the complete execute-time estimator (`fa95a0ad`), installed-wheel plugin health verification (`a31656be`), and operator project-root binding/SDK API 1.3 (`a35ede3`, compatibility fixture `57c6733`). Package version remains 0.3.9; SDK API version is independent.

## Validation

The complete pytest suite passed **840 passed, 1 skipped in 31.57s** with the worktree's own Python 3.11 environment, matching PATH, and this worktree's core source. The installed plugin input was the immutable candidate-06 wheel (plugin source `a3ec1d4583eaf177a41d815bacecd7861daef379`, SHA-256 `815d3dfad91a0e1d51a303b08321b2c485ec3ee543bdaceccc31d1052cfcd77f`). Root plugin source changes cannot mutate that input. Policy check: 25 pass, 0 fail, 1 pre-existing R-22 advisory.

An earlier run used a PATH that omitted the operator CLI directory. It failed with 28 failures and 2 errors (810 passed, 1 skipped), including missing serialwrap and uv binaries. Correcting PATH resolved the full suite; the earlier run is not acceptance evidence.

## 2026-10-03 installed-module ownership follow-up

The combined core source is now frozen at `b05faed` after integrating reviewed commits `6dc314e` and `60ecedd`. Wheel health verification checks both the entry-point shim and the Plugin class implementation against distribution RECORD membership or the editable installation's PEP 610 source root. A shim owned by the distribution cannot authorize a class imported from an unowned module. The regression also verifies imported implementation modules are removed after checking. These are module-origin checks, not content-hash validation of every installed dependency.

The complete combined suite passed **845 passed, 1 skipped in 24.76s**, using the same immutable plugin wheel input and matching Python 3.11/PATH/source binding as above. Policy check: **25 pass, 0 fail, 1 pre-existing R-22 advisory**. The independent exact-commit review found no blocking findings within the assigned ownership/root-binding/isolated-verification scope. Live EIT acceptance of this final core remains pending.

## Live candidate boundary

The EIT interim candidate uses core `0f358be4` and plugin `a3ec1d45`, before the root-binding/API 1.3 integration. Its explicit serialwrap 0.3.0 client matches the existing 0.3.0 daemon. Installed-wheel `--verify-install` executes the plugin hook and reports all checks passed with no warnings when SERIALWRAP_BIN points to that existing CLI. An earlier omitted-binary invocation produced warnings and is not proof of daemon health. These checks did not restart the daemon or establish candidate UART compatibility beyond the current pinned client.

The combined core commit still needs the final matching plugin integration and EIT case acceptance. No GitLab issue is closed by these offline results.
