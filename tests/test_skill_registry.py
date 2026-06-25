"""Tests for skill_registry — discovery, lookup, and role resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.core.agent_roles import AgentRole
from testpilot.core.skill_registry import SkillPackage, SkillRegistry


# -- helpers ------------------------------------------------------------------

def _make_skill(tmp: Path, name: str, *, description: str = "", version: str = "") -> Path:
    """Create a minimal skill directory with a SKILL.md marker."""
    skill_dir = tmp / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if description:
        lines.append(f"# {description}")
    if version:
        lines.append(f"version: {version}")
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return skill_dir


def _role(name: str, skills: tuple[str, ...] = ()) -> AgentRole:
    return AgentRole(name=name, description="", hooks=frozenset(), skills=skills)


# -- discovery ----------------------------------------------------------------

def test_discover_empty_dir(tmp_path: Path) -> None:
    """Empty search directory yields no packages."""
    reg = SkillRegistry(search_dirs=[tmp_path])
    assert reg.discover() == []


def test_discover_nonexistent_dir(tmp_path: Path) -> None:
    """Non-existent search directory is silently skipped."""
    reg = SkillRegistry(search_dirs=[tmp_path / "no_such_dir"])
    assert reg.discover() == []


def test_discover_finds_skill_with_marker(tmp_path: Path) -> None:
    """Directories containing SKILL.md are discovered as skill packages."""
    _make_skill(tmp_path, "my-skill", description="My Skill", version="1.0")
    reg = SkillRegistry(search_dirs=[tmp_path])
    pkgs = reg.discover()
    assert len(pkgs) == 1
    assert pkgs[0].name == "my-skill"
    assert pkgs[0].description == "My Skill"
    assert pkgs[0].version == "1.0"


def test_discover_ignores_dirs_without_marker(tmp_path: Path) -> None:
    """Directories without SKILL.md are not treated as skill packages."""
    (tmp_path / "not-a-skill").mkdir()
    _make_skill(tmp_path, "real-skill")
    pkgs = SkillRegistry(search_dirs=[tmp_path]).discover()
    assert [p.name for p in pkgs] == ["real-skill"]


def test_discover_multiple_search_dirs(tmp_path: Path) -> None:
    """Packages from multiple search directories are aggregated."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _make_skill(dir_a, "skill-a")
    _make_skill(dir_b, "skill-b")
    pkgs = SkillRegistry(search_dirs=[dir_a, dir_b]).discover()
    names = sorted(p.name for p in pkgs)
    assert names == ["skill-a", "skill-b"]


# -- find ---------------------------------------------------------------------

def test_find_existing(tmp_path: Path) -> None:
    _make_skill(tmp_path, "target")
    reg = SkillRegistry(search_dirs=[tmp_path])
    pkg = reg.find("target")
    assert pkg is not None
    assert pkg.name == "target"


def test_find_missing(tmp_path: Path) -> None:
    reg = SkillRegistry(search_dirs=[tmp_path])
    assert reg.find("nonexistent") is None


# -- resolve_for_role ---------------------------------------------------------

def test_resolve_for_role_with_matching_skills(tmp_path: Path) -> None:
    _make_skill(tmp_path, "serialwrap-mcp")
    _make_skill(tmp_path, "ebpf-ftrace")
    reg = SkillRegistry(search_dirs=[tmp_path])
    role = _role("executor", skills=("serialwrap-mcp", "ebpf-ftrace"))
    resolved = reg.resolve_for_role(role)
    assert [p.name for p in resolved] == ["serialwrap-mcp", "ebpf-ftrace"]


def test_resolve_for_role_skips_missing(tmp_path: Path) -> None:
    _make_skill(tmp_path, "available")
    reg = SkillRegistry(search_dirs=[tmp_path])
    role = _role("executor", skills=("available", "missing"))
    resolved = reg.resolve_for_role(role)
    assert [p.name for p in resolved] == ["available"]


def test_resolve_for_role_no_skills(tmp_path: Path) -> None:
    reg = SkillRegistry(search_dirs=[tmp_path])
    role = _role("observer")
    assert reg.resolve_for_role(role) == []


# -- skill_directories --------------------------------------------------------

def test_skill_directories_returns_strings(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "beta")
    reg = SkillRegistry(search_dirs=[tmp_path])
    dirs = reg.skill_directories()
    assert len(dirs) == 2
    assert all(isinstance(d, str) for d in dirs)
    assert all(Path(d).is_dir() for d in dirs)


# -- lazy discover ------------------------------------------------------------

def test_lazy_discover_on_find(tmp_path: Path) -> None:
    """find() triggers discovery automatically if not yet done."""
    _make_skill(tmp_path, "lazy")
    reg = SkillRegistry(search_dirs=[tmp_path])
    assert reg.find("lazy") is not None


# -- SkillPackage frozen ------------------------------------------------------

def test_skill_package_is_frozen() -> None:
    pkg = SkillPackage(name="x", path=Path("/tmp/x"))
    with pytest.raises(AttributeError):
        pkg.name = "y"  # type: ignore[misc]
