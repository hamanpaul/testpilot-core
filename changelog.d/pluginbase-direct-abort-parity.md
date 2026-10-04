---
type: fix
scope: plugin-sdk
---
Make direct `PluginBase.run_pipeline()` honor a current case/attempt plugin terminal-abort snapshot, including literal teardown suppression and explicit result evidence. Unknown transport outcomes retain precedence; stale or malformed abort metadata leaves normal cleanup behavior unchanged.
