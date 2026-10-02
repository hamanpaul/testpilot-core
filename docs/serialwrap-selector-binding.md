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
