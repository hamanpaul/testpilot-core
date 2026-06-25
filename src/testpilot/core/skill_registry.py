"""Skill package discovery and resolution for agent roles.

A *skill package* is a directory containing a ``SKILL.md`` marker file.
The :class:`SkillRegistry` scans one or more search directories, indexes
discovered packages, and resolves the skills required by an
:class:`~testpilot.core.agent_roles.AgentRole`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from testpilot.core.agent_roles import AgentRole


@dataclass(frozen=True)
class SkillPackage:
    """Immutable descriptor for a discovered skill package."""

    name: str
    path: Path
    description: str = ""
    version: str = ""


class SkillRegistry:
    """Discover and manage skill packages for agent roles."""

    def __init__(self, search_dirs: Sequence[Path | str] = ()) -> None:
        """Initialize with skill search directories."""
        self._search_dirs: list[Path] = [Path(d) for d in search_dirs]
        self._packages: dict[str, SkillPackage] = {}
        self._discovered = False

    def discover(self) -> list[SkillPackage]:
        """Scan search directories for skill packages (dirs with SKILL.md)."""
        self._packages.clear()
        for search_dir in self._search_dirs:
            resolved = Path(search_dir).resolve()
            if not resolved.is_dir():
                continue
            for child in sorted(resolved.iterdir()):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    pkg = self._load_package(child)
                    self._packages[pkg.name] = pkg
        self._discovered = True
        return list(self._packages.values())

    def find(self, name: str) -> SkillPackage | None:
        """Find a skill by name."""
        self._ensure_discovered()
        return self._packages.get(name)

    def resolve_for_role(self, role: AgentRole) -> list[SkillPackage]:
        """Resolve all skill packages needed by an agent role."""
        self._ensure_discovered()
        resolved: list[SkillPackage] = []
        for skill_name in role.skills:
            pkg = self._packages.get(skill_name)
            if pkg is not None:
                resolved.append(pkg)
        return resolved

    def skill_directories(self) -> list[str]:
        """Return list of skill directory paths for CopilotSessionRequest."""
        self._ensure_discovered()
        return [str(pkg.path) for pkg in self._packages.values()]

    # -- Internal helpers -----------------------------------------------------

    def _ensure_discovered(self) -> None:
        if not self._discovered:
            self.discover()

    @staticmethod
    def _load_package(skill_dir: Path) -> SkillPackage:
        """Build a :class:`SkillPackage` from a skill directory."""
        name = skill_dir.name
        description = ""
        version = ""

        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            lines = skill_md.read_text(encoding="utf-8").splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("# ") and not description:
                    description = stripped[2:].strip()
                elif stripped.lower().startswith("version:"):
                    version = stripped.split(":", 1)[1].strip()

        return SkillPackage(
            name=name,
            path=skill_dir,
            description=description,
            version=version,
        )
