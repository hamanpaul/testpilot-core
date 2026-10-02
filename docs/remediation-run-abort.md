# Unrecovered environment abort

A plugin remediation executor may return `abort_run: true` with an
`abort_reason` after a bounded recovery fails. Core preserves the failed
attempt and remediation trace, stops retries for that case, and stops the
sequential run before starting the next case. Ordinary functional failures
continue under the configured failure policy.

The reporter receives only executed case records. The artifact bundle contains
`run-abort.json` with the reason, triggering case, executed/requested counts
and all unexecuted case IDs. Core returns `status: aborted` and `run_abort`
in the run payload. Each trace also exposes the abort flag. Unexecuted cases
receive no fabricated Pass, Fail or Skip verdict.

This optional executor response is additive. A plugin that does not return
`abort_run: true` keeps the existing retry and continue behavior. Readiness
checks and the decision to request an abort remain plugin responsibilities.
