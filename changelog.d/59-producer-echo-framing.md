---
type: fix
scope: transport
issue: 59
---
Avoid false unknown producer outcomes when UART console echo wraps inside a staged command by splitting the marker literal from its nonce. Preserve strict receipt parsing, no-replay handling, separate script and cleanup statuses, and the 120-byte UTF-8 UART limit including LF.
