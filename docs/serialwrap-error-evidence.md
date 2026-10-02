# Serialwrap failure evidence

Serialwrap RPC rejections raise a `RuntimeError` subclass with a `result`
mapping (also exposed as `transport_result`). This retains the broker's
`error_code`, `retry_after_s`, `recommended_action` and execution safety
fields even when the CLI exits nonzero. A malformed or absent JSON response
does not invent broker readiness or replayability information.

Terminal command results preserve those same fields. Plugins can distinguish
a rejected boot-window command from a command that was accepted and has an
ambiguous outcome. A CLI timeout alone is not permission to resubmit a write.

When staging a long command, a failed, partial or non-replayable script-write
result stops staging and is returned to the caller. The transport does not
execute the incomplete script. Successful staging behavior stays the same.

These changes provide evidence for plugin readiness policy; they do not
perform boot-window retries or claim that the target is ready.
