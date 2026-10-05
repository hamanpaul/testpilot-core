# Serialwrap capture-binding API 1.1 integration

Strict capture admission is opt-in through a plugin's declared run capability
and role-plan request. Core requires a supported API 1.1 provider before plugin
preparation. It does not fall back to API 1.0 on this path. Plugins that do not
request strict capture keep the ordinary legacy run path.

The API 1.1 `capture.binding.begin` receipt carries two ordered per-role token
lists. `binding_tokens` identifies the capture's bound role handles;
`rx_binding_tokens` identifies accepted RX ingress provenance for those roles.
They have separate meanings and Core keeps them in separate private maps. Core
requires both lists to contain one unique 64-character lowercase hexadecimal
token per role in the requested role order. An accepted RX WAL row is checked
against that role's `rx_binding_tokens` value and its `rx_disposition` must be
`accepted`. Core never substitutes the capture-identity token, infers missing
RX provenance, or publishes either token in run artifacts.

The real-provider integration test exercises the public Core run path through
the actual provider CLI, Unix JSON-RPC service, capture-binding implementation,
WAL, and a temporary POSIX PTY. It uses only temporary local state and a
source-pinned provider worktree; it does not start device discovery or connect
to hardware. Set `TESTPILOT_SERIALWRAP_SOURCE_ROOT` to the clean provider Git
worktree pinned in the test before running:

```sh
TESTPILOT_SERIALWRAP_SOURCE_ROOT=/path/to/clean/provider-worktree \
  python -m pytest -q tests/test_serialwrap_provider_api11_integration.py
```

This offline chain test validates protocol compatibility and Core attribution.
It is not a live broker deployment or EIT acceptance result. An API 1.0-only
provider remains unsupported for strict capture until an API 1.1 provider is
deployed through its separately reviewed deployment process.
