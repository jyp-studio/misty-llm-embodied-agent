"""Read-only Skill Catalog. Guidance has no robot or execution authority.

Only locally configured directories are read. Discovery returns metadata;
activation reads the body on demand. The caller owns the Episode lifetime.
"""

import logging
from pathlib import Path
import re

import yaml

from misty_agent.agent.layering import mentions_control_parameter

MAX_RESOURCE_BYTES = 64 * 1024
#: Agent Skills names: lowercase words joined by hyphens, matching the directory.
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
log = logging.getLogger(__name__)


class SkillRejected(ValueError):
    """An unavailable or invalid instruction resource, never executable code."""


class _MetadataLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = [key.value for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise SkillRejected("Duplicate Skill metadata keys")
        return super().construct_mapping(node, deep=deep)


def _text(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_RESOURCE_BYTES + 1)
        if len(raw) > MAX_RESOURCE_BYTES:
            raise SkillRejected("Skill resource exceeds the 64 KiB limit")
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillRejected("Skill resource is missing or is not UTF-8 text") from error
    if "\x00" in text:
        raise SkillRejected("Skill resource must be text")
    if mentions_control_parameter(text):
        raise SkillRejected("Skill resource crosses the control-layer boundary")
    return text


def _document(path: Path) -> tuple[dict, str]:
    text = _text(path)
    document = re.fullmatch(r"---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)", text, re.DOTALL)
    if document is None:
        raise SkillRejected("SKILL.md needs YAML frontmatter")
    try:
        metadata = yaml.load(document[1], Loader=_MetadataLoader)
    except (yaml.YAMLError, TypeError, RecursionError) as error:
        raise SkillRejected("Invalid Skill metadata") from error
    if not isinstance(metadata, dict):
        raise SkillRejected("Skill metadata must be a mapping")
    name, description = metadata.get("name"), metadata.get("description")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or len(name) > 64:
        raise SkillRejected("Skill name must be lowercase words separated by hyphens")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise SkillRejected("Skill description must contain 1–1024 characters")
    if name != path.parent.name:
        raise SkillRejected("Skill name must match its directory")
    if not document[2].strip():
        raise SkillRejected("Skill instructions are empty")
    return {"name": name, "description": description.strip()}, document[2].strip()


class SkillCatalog:
    """A catalog, not a registry of executable capabilities."""

    def __init__(self, root: Path):
        self._root = root.resolve()

    def _path(self, name: str) -> Path:
        if not _NAME.fullmatch(name):
            raise SkillRejected("Unknown Skill name")
        directory = self._root / name
        if directory.is_symlink() or (directory / "SKILL.md").is_symlink():
            raise SkillRejected("Skill links are not allowed")
        return directory / "SKILL.md"

    def available(self) -> list[dict]:
        result = []
        if not self._root.is_dir():
            return result
        for directory in sorted(self._root.iterdir()):
            if directory.is_dir():
                try:
                    metadata, _ = _document(self._path(directory.name))
                except SkillRejected as why:
                    log.warning("Skill %r skipped from discovery: %s", directory.name, why)
                    continue
                result.append(metadata)
        return result

    def activate(self, name: str) -> dict:
        metadata, instructions = _document(self._path(name))
        return {"kind": "skill_activation", **metadata, "instructions": instructions}

    def for_episode(self) -> "EpisodeSkills":
        return EpisodeSkills(self)

    def read_resource(self, name: str, resource: str) -> dict:
        directory = self._path(name).parent
        relative = Path(resource)
        if "scripts" in relative.parts or relative.suffix.lower() in {".py", ".sh", ".js", ".bat", ".exe"}:
            raise SkillRejected("Skill scripts are prohibited")
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in {"references", "assets"}:
            raise SkillRejected("Only Skill references/assets may be read")
        path = directory / relative
        if not path.resolve().is_relative_to(directory.resolve()) or any(
            (directory / Path(*relative.parts[:index])).is_symlink()
            for index in range(1, len(relative.parts) + 1)
        ):
            raise SkillRejected("Skill resource links are not allowed")
        return {"kind": "skill_resource", "name": name, "resource": resource, "text": _text(path)}


class EpisodeSkills:
    """One Episode's activation permissions; no context survives its owner."""

    def __init__(self, catalog: SkillCatalog):
        self._catalog = catalog
        self._active: set[str] = set()

    def available(self) -> list[dict]:
        return self._catalog.available()

    def activate(self, name: str) -> dict:
        loaded = self._catalog.activate(name)
        self._active.add(name)
        return loaded

    def read_resource(self, name: str, resource: str) -> dict:
        if name not in self._active:
            raise SkillRejected("Skill must be active in this Episode")
        return self._catalog.read_resource(name, resource)


def bundled_skills() -> SkillCatalog:
    return SkillCatalog(Path(__file__).resolve().parents[1] / "skills")
