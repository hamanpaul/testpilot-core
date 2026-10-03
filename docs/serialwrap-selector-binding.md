# Logical serialwrap session identities

Run startup forwards each configured DUT/STA `selector` to session setup.
An explicit selector must resolve uniquely to an existing operator-bound
session with a `device_by_id`. Startup attaches that session, then assigns
its configured alias. It does not replace the binding from a `serial_port`
setting or USB enumeration order. Missing, ambiguous or repeated identities
are rejected before any session attach/bind begins.

Legacy callers that provide no selector retain physical-port discovery.
Operators must bind logical DUT/STA identities explicitly before a normal
run. Swapping USB enumeration cannot silently swap those roles during startup.

Offline regression covers a stale physical port pointing at the wrong device
and an unbound selector rejected before any write. Hardware acceptance still
requires startup against the operator's actual bound sessions.

`SerialWrapTransport.connect()` also validates the current session-list record
against every configured non-empty profile. When a selector, alias, or session
ID is supplied together with `serial_port`, the selected session must match
that same physical identity: a by-id path must equal `device_by_id`, a COM or
vtty value must match the corresponding session field, and a tty path may be
resolved through serialwrap's read-only device list. Missing or conflicting
identity metadata fails before attach or transport commands; an attach response
must still name the selected session and satisfy the same constraints. The
older serial-port-only discovery path, including its ttyUSB-to-COM fallback,
remains unchanged.

Before `recover()` and before the safe `SESSION_NOT_READY` attach/retry path,
the transport refreshes the session list and requires the current selector,
profile, and physical identity to match the session accepted by `connect()`.
Missing, ambiguous, or changed metadata clears the connection and prevents the
recovery, attach, or command replay. Ordinary command submissions do not each
perform a new session-list query.
Session and device metadata lookups are read-only and do not themselves trigger
automatic attach retries; a failed physical-identity lookup fails closed.
The execute-budget estimator includes the fresh session-list timeout and, for
an explicitly selected non-COM physical path, up to two device-list timeouts
per possible safe attach/retry (pre-attach and attach-response validation).

These checks validate a session-list snapshot before the following operation;
they do not atomically bind that operation to the metadata. Serialwrap's
current command interface carries no expected-device identity token, so a
concurrent daemon-side rebind after validation remains a race outside this
client-side guard.
