---
type: fix
scope: transport
---
Treat SSH subprocess timeouts, exit status 255, and local signal termination as structured, non-replayable unknown outcomes. Stop Engine retries and teardown without exposing SSH command argv in exception formatting; keep successful and known nonzero result behavior unchanged.
