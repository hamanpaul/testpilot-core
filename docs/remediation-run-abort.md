# Run abort on terminal failure

A plugin remediation executor may return `abort_run: true` with an
`abort_reason` after a bounded recovery fails. A plugin may also request a
terminal stop in the current attempt's `_last_failure` snapshot when its own
failure classification proves that continuing is unsafe. That snapshot must
carry the exact current `case_id` and integer `attempt_index`; stale or
unmatched snapshots are ignored. Core bounds the abort reason to a short token
and uses a generic reason when the supplied value is invalid.

Core preserves the failed attempt and remediation trace, stops retries for
that case, and stops the sequential run before starting the next case. The
explicit failure snapshot does not claim that recovery succeeded or that a
command was accepted. Ordinary functional failures continue under the
configured failure policy.

Cleanup normally runs after a failed attempt. A plugin may set the literal
`skip_teardown: true` in the matching current-attempt failure snapshot when
teardown could issue unsafe writes; Core then suppresses teardown for that
attempt. Unknown or ambiguous command outcomes continue to suppress teardown
automatically. The run-abort request is independent of remediation hooks, so
it also applies when the failure occurs on the first or final configured
attempt.

Transport evidence from a failed step, a generic exception's `result` and
`transport_result`, the failure hook payload, and a matching failure snapshot
is projected into the attempt trace. Explicit unknown markers dominate
conflicting benign projections, while identifiers such as `cmd_id` are
retained. An unmatched failure snapshot cannot contribute transport evidence.

The reporter receives only executed case records. The artifact bundle contains
`run-abort.json` with the reason, triggering case, executed/requested counts
and all unexecuted case IDs. Core returns `status: aborted` and `run_abort`
in the run payload. Each trace also exposes the abort flag. Unexecuted cases
receive no fabricated Pass, Fail or Skip verdict.

These optional signals are additive. A plugin that does not return
`abort_run: true` or provide a matching terminal failure snapshot keeps the
existing retry and continue behavior. Readiness checks and the decision to
request an abort remain plugin responsibilities.
