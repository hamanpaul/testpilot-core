# SSH command outcome boundary

The built-in SSH transport runs a local `ssh` subprocess. A completed local
process does not always prove that the requested remote command completed.

The transport raises `SshCommandOutcomeUnknown`, a `RuntimeError` with matching
`.result` and `.transport_result` mappings, for these terminal outcomes:

- A local subprocess timeout. Captured stdout/stderr and elapsed time are kept;
  no completed return code is invented.
- Local SSH process exit code `255`. OpenSSH uses this status for SSH errors,
  and a remote command may also exit `255`; this transport cannot distinguish
  those cases. The recorded return code is the local SSH process status, not a
  verified remote status.
- A negative local process return code, which indicates signal termination on
  POSIX. The remote command's completion remains unverified.

The exception receipt uses the fixed uncertainty markers
`status="unknown"`, `outcome="unknown"`, `ambiguous=true`,
`error_code="COMMAND_OUTCOME_UNKNOWN"`, `non_replayable=true`, and
`retryable=false`. The existing ExecutionEngine recognizes those markers and
stops the case before retry and teardown. The transport does not replay the
command, select a fallback transport, claim remote acceptance, or perform
remote recovery or cleanup.

Successful `0` results and completed nonzero statuses `1`–`254` retain the
existing four-key mapping: `returncode`, `stdout`, `stderr`, and `elapsed`.
Those ordinary results are unchanged. Missing binaries and other local errors
that occur before subprocess execution continue to raise their existing errors;
they are not represented as remote acceptance.

Exception messages and formatted tracebacks contain no SSH argv, host, user,
identity path, command text, or raw `TimeoutExpired.cmd`. Partial stdout/stderr
remain available only through the structured exception receipt.
