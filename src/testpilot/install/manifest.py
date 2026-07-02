from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass(frozen=True)
class Core:
    distribution: str
    repo: str | None = None
    # version is optional: absent => resolve the newest API-compatible release
    # at install/build time; present => pin that exact version.
    version: str | None = None
    private: bool = True

@dataclass(frozen=True)
class Plugin:
    name: str
    repo: str
    api_version: str
    # version is optional: absent => resolve newest compatible; present => pin.
    version: str | None = None
    private: bool = True

@dataclass(frozen=True)
class Serialwrap:
    # serialwrap has no SDK API contract, so it stays pinned: version required.
    repo: str
    version: str
    private: bool = False

@dataclass(frozen=True)
class InstallManifest:
    core: Core
    plugins: list[Plugin] = field(default_factory=list)
    serialwrap: Serialwrap | None = None
    def selected(self, specs: list[str] | None) -> list[Plugin]:
        if not specs:
            return list(self.plugins)
        out: list[Plugin] = []
        for spec in specs:
            name, _, ver = spec.partition("@")
            base = next((p for p in self.plugins if p.name == name), None)
            if base is None:
                raise KeyError(f"unknown plugin {name!r}")
            out.append(
                base
                if not ver
                else Plugin(
                    name=base.name,
                    repo=base.repo,
                    api_version=base.api_version,
                    version=ver,
                    private=base.private,
                )
            )
        return out

def load_manifest(path: str | Path) -> InstallManifest:
    data = yaml.safe_load(Path(path).read_text()) or {}

    def _opt_version(d: dict) -> str | None:
        v = d.get("version")
        return str(v) if v is not None else None

    c = data["core"]
    core = Core(
        distribution=c["distribution"],
        repo=c.get("repo"),
        version=_opt_version(c),
        private=c.get("private", True),
    )
    plugins = [
        Plugin(
            name=p["name"],
            repo=p["repo"],
            api_version=str(p["api_version"]),
            version=_opt_version(p),
            private=p.get("private", True),
        )
        for p in data.get("plugins", [])
    ]
    sw = data.get("serialwrap")
    serialwrap = None
    if sw:
        if sw.get("version") is None:
            raise ValueError(
                "serialwrap must declare a pinned 'version' in install-manifest.yaml "
                "(serialwrap is not flow-latest)"
            )
        serialwrap = Serialwrap(
            repo=sw["repo"],
            version=str(sw["version"]),
            private=sw.get("private", False),
        )
    return InstallManifest(core=core, plugins=plugins, serialwrap=serialwrap)
