from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass(frozen=True)
class Core:
    distribution: str
    version: str
    repo: str | None = None
    private: bool = True

@dataclass(frozen=True)
class Plugin:
    name: str
    repo: str
    version: str
    api_version: str
    private: bool = True

@dataclass(frozen=True)
class Serialwrap:
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
            out.append(base if not ver else Plugin(base.name, base.repo, ver, base.api_version, base.private))
        return out

def load_manifest(path: str | Path) -> InstallManifest:
    data = yaml.safe_load(Path(path).read_text()) or {}
    c = data["core"]
    core = Core(c["distribution"], str(c["version"]), c.get("repo"), c.get("private", True))
    plugins = [Plugin(p["name"], p["repo"], str(p["version"]), str(p["api_version"]), p.get("private", True)) for p in data.get("plugins", [])]
    sw = data.get("serialwrap")
    serialwrap = Serialwrap(sw["repo"], str(sw["version"]), sw.get("private", False)) if sw else None
    return InstallManifest(core=core, plugins=plugins, serialwrap=serialwrap)
