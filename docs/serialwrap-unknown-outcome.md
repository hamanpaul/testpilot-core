# Unknown command outcomes

A CLI timeout, missing submission receipt or failed status query after an
accepted submission cannot establish that the target command stopped.
Transport results retain the known command ID and mark the outcome unknown,
non-replayable and not retryable. An explicit broker rejection, such as a
boot quiet window, retains its rejection evidence instead.

The core engine also honors explicit non-replayable, partial and uncertain
input markers. It preserves structured transport fields in the failure hook
and attempt trace, stops before another attempt, and suppresses teardown
writes that could race a still-running command. The run abort artifact lists
later cases as unexecuted. No automatic attach, reboot or remediation is
performed to resolve an unknown accepted-command outcome.

Operators must reconcile the command's actual terminal status and environment
before starting another run. This is separate from an explicitly rejected
command, for which a plugin can implement a bounded readiness policy.

Session capture startup attaches an already operator-bound identity; command
readiness remains enforced by transport connect and the plugin preflight gate.
The capture setup return value alone is not a READY assertion.
