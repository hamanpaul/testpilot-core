# Serialwrap failure evidence

Serialwrap RPC rejections raise a `RuntimeError` subclass with a `result`
mapping (also exposed as `transport_result`). This retains the broker's
`error_code`, `retry_after_s`, `recommended_action` and execution safety
fields even when the CLI exits nonzero. A malformed or absent JSON response
does not invent broker readiness or replayability information.

Terminal command results preserve those same fields. Plugins can distinguish
a rejected boot-window command from a command that was accepted and has an
ambiguous outcome. A CLI timeout alone is not permission to resubmit a write.

When staging a long command, each script-write shell and the final script shell
emit a per-invocation unpredictable status marker. The transport checks one
complete terminal marker before continuing, reports the target shell's exit
status separately from the broker result, and retains the original broker
receipt. A known failed stage stops before execution; an accepted partial,
unknown, or malformed receipt stops without another command. Final cleanup has
its own status and cannot hide a nonzero script exit. The marker framing is
removed from stdout while preserving the command's output, including real
trailing newlines.

The 120-byte limit is measured on the UTF-8 UART payload, including the LF
that `Bridge.send_command` appends to commands without a terminal LF. Generated
staging and final commands remain single physical lines; a command already
ending in LF is not charged for a second terminator.

Per-case serialwrap log intervals use the exact concatenated decoded text saved
to `DUT.log` and `STA.log`. WAL record boundaries do not add lines; CR, LF, and
CRLF boundaries (including a CRLF split across records) follow the saved text's
`splitlines` behavior. The interval includes the full first and last payload
lines, even when the final record spans multiple lines.

These changes provide evidence for plugin readiness policy; they do not
perform boot-window retries or claim that the target is ready.
