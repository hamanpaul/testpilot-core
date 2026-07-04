# testpilot-sample-echo

A minimal, runnable TestPilot plugin — the reference example for the
`testpilot.api` SDK (issue #3). It is a standalone pip distribution that the
host discovers through the `testpilot.plugins` entry-point group.

## What it demonstrates

- `entry_points` registration (`[project.entry-points."testpilot.plugins"]`)
- a `PluginBase` subclass with `api_version = "1.0"`
- a schema-valid case (`cases/echo-hello.yaml`) with a deterministic Pass
- an optional `register_cli` command (`testpilot sample-echo-greet`)
- discovery after a real `pip install` (no monkeypatching)

Production code imports **only** from `testpilot.api`.

## Try it

```bash
pip install testpilot-core          # the host
pip install -e ./examples/sample_echo  # this sample

testpilot list-plugins              # -> sample_echo
testpilot list-cases sample_echo    # -> echo-hello
testpilot run sample_echo --case echo-hello   # -> verdict PASS
testpilot sample-echo-greet --name you        # CLI hook demo
```

## Layout

```
src/testpilot_sample_echo/
  plugin.py            # Plugin(PluginBase) + EchoRunner
  testbed.yaml.example # staged to configs/testbed.yaml by the CLI
  cases/echo-hello.yaml
tests/                 # behaviour smoke + API-boundary guard
```
