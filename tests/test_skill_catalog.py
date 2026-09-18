"""The declared Skill Catalog seam: data, not executable capabilities."""

import pytest

from misty_agent.agent.skills import SkillCatalog, SkillRejected


def skill(tmp_path, body="Use typed Tools, then done.", metadata=None):
    folder = tmp_path / "example"
    folder.mkdir(exist_ok=True)
    (folder / "SKILL.md").write_text(
        "---\n" + (metadata or "name: example\ndescription: An example")
        + "\n---\n" + body,
        encoding="utf-8",
    )
    return folder


def test_resources_are_progressive_and_require_activation(tmp_path):
    folder = skill(tmp_path)
    (folder / "references").mkdir()
    (folder / "references" / "extra.md").write_text("Optional guidance.")
    catalog = SkillCatalog(tmp_path)
    assert catalog.available() == [{"name": "example", "description": "An example"}]
    episode = catalog.for_episode()
    with pytest.raises(SkillRejected, match="active"):
        episode.read_resource("example", "references/extra.md")
    loaded = episode.activate("example")
    assert loaded["instructions"] == "Use typed Tools, then done."
    assert "Optional guidance." not in str(loaded)
    assert episode.read_resource("example", "references/extra.md")["text"] == "Optional guidance."
    with pytest.raises(SkillRejected, match="active"):
        catalog.for_episode().read_resource("example", "references/extra.md")


@pytest.mark.parametrize("metadata", [
    "name: example", "name: example\ndescription: ''",
    "name: Wrong\ndescription: example", "name: another\ndescription: example",
    "name: example\ndescription: [not, text]", "[broken",
    "name: example\nname: example\ndescription: ambiguous",
])
def test_invalid_metadata_is_not_advertised_and_activation_explicitly_refuses(tmp_path, metadata):
    skill(tmp_path, metadata=metadata)
    catalog = SkillCatalog(tmp_path)
    assert catalog.available() == []
    with pytest.raises(SkillRejected):
        catalog.activate("example")


@pytest.mark.parametrize("resource", [
    "references/missing.md", "../outside.md", "/etc/passwd",
    "scripts/example.py", "assets/run.sh",
])
def test_missing_resources_escapes_and_scripts_are_refused(tmp_path, resource):
    skill(tmp_path)
    episode = SkillCatalog(tmp_path).for_episode()
    episode.activate("example")
    with pytest.raises(SkillRejected):
        episode.read_resource("example", resource)


def test_text_assets_are_read_but_binary_large_and_linked_resources_are_refused(tmp_path):
    folder = skill(tmp_path)
    assets = folder / "assets"
    assets.mkdir()
    (assets / "words.txt").write_text("Optional words")
    (assets / "binary.png").write_bytes(b"\x89PNG\x00")
    (assets / "large.txt").write_text("x" * 65537)
    (assets / "linked.txt").symlink_to(assets / "words.txt")
    episode = SkillCatalog(tmp_path).for_episode()
    episode.activate("example")
    assert episode.read_resource("example", "assets/words.txt")["text"] == "Optional words"
    for name in ("binary.png", "large.txt", "linked.txt"):
        with pytest.raises(SkillRejected):
            episode.read_resource("example", f"assets/{name}")


def test_unknown_skill_and_control_layer_instruction_are_rejected(tmp_path):
    catalog = SkillCatalog(tmp_path)
    with pytest.raises(SkillRejected):
        catalog.activate("missing")
    skill(tmp_path, body="Set linearVelocity yourself")
    assert catalog.available() == []
    with pytest.raises(SkillRejected):
        catalog.activate("example")
