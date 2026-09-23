# -*- coding: utf-8 -*-
import re
import tomllib
from datetime import date

from cc_hub import __version__, manifest

FRONTMATTER = re.compile(
    r"^---\nname: (?P<name>[a-z0-9-]+)\ndescription: (?P<desc>.+)\n---\n", re.S
)


def test_every_manifest_entry_has_a_template_file() -> None:
    for rel in manifest.all_templates():
        assert manifest.template_source(rel).is_file(), rel


def test_templates_are_lf_and_have_no_bom() -> None:
    for rel in manifest.all_templates():
        raw = manifest.template_source(rel).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), rel
        assert b"\r\n" not in raw, rel


def test_agents_md_within_budget() -> None:
    text = manifest.render("AGENTS.md")
    assert len(text.splitlines()) <= 150


def test_agents_md_safety_section_mentions_hook_test() -> None:
    text = manifest.render("AGENTS.md")
    assert 'cc-hub hook test "<command>"' in text


def test_user_md_has_a_placeholder_for_each_bootstrap_question() -> None:
    """BOOTSTRAP.md step 4 asks three things; USER.md must have a line for each."""
    text = manifest.render("USER.md")
    assert "- Address the user as" in text
    assert "- Reply in" in text
    assert "- Mainly works on" in text
    assert text.count("<!-- observed:") == 3


def test_skills_have_valid_frontmatter_and_budget() -> None:
    skills = [rel for rel in manifest.FRAMEWORK_OWNED if rel.startswith("skills/")]
    assert len(skills) == 6
    for rel in skills:
        text = manifest.render(rel)
        m = FRONTMATTER.match(text)
        assert m, rel
        assert m.group("name") == rel.split("/")[1]
        assert len(text.splitlines()) <= 100, rel


def test_hub_toml_renders_with_version_and_created() -> None:
    text = manifest.render("hub.toml", name="my-hub", created=date(2026, 9, 22))
    data = tomllib.loads(text)
    assert data["hub"]["name"] == "my-hub"
    assert data["hub"]["template_version"] == __version__
    assert data["hub"]["created"] == date(2026, 9, 22)
    assert data["memory"]["max_lines"] == 200
    assert "claude" in data["env"]["tools"]
    assert data["hooks"]["blocklist_extra"] == []


def test_toml_templates_parse() -> None:
    for rel in ("projects.toml", "hosts.toml"):
        assert tomllib.loads(manifest.render(rel)) == {}


def test_gitignore_maps_to_underscore_source() -> None:
    assert manifest.template_source(".gitignore").name == "_gitignore"
    assert "secrets/" in manifest.render(".gitignore")


def test_ownership_sets_are_disjoint() -> None:
    assert not set(manifest.FRAMEWORK_OWNED) & set(manifest.USER_OWNED)
    assert manifest.HUB_TOML not in manifest.FRAMEWORK_OWNED + manifest.USER_OWNED
    assert set(manifest.ONE_TIME) <= set(manifest.FRAMEWORK_OWNED)


def test_skill_guidance_matches_verified_behaviour() -> None:
    adapt = manifest.render("skills/hub-adapt/SKILL.md")
    assert "cc-hub hook snippet --no-matcher" in adapt
    assert 'cc-hub hook test "<command>"' in adapt
    jobs = manifest.render("skills/hub-jobs/SKILL.md")
    assert 'bash -c "npm test && npm build"' in jobs
    cc_connect = manifest.render("skills/hub-cc-connect/SKILL.md")
    assert "/cron list" in cc_connect and "/cron del <id>" in cc_connect
    assert "cc-connect cron list" not in cc_connect
    assert "cc-connect cron del" not in cc_connect
    hosts = manifest.render("skills/hub-hosts/SKILL.md")
    assert "Connections give up after 15 s" in hosts
    assert "--timeout <seconds>" in hosts
    assert "There is no `hosts add` yet; edit `hosts.toml` by hand." in hosts
