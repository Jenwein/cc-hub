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


def test_agents_md_leaves_background_work_to_the_runtime() -> None:
    text = manifest.render("AGENTS.md")
    assert "your own runtime's background facilities" in text
    assert "`/new`" in text


def test_user_md_has_a_placeholder_for_each_bootstrap_question() -> None:
    """BOOTSTRAP.md step 4 asks three things; USER.md must have a line for each."""
    text = manifest.render("USER.md")
    assert "- Address the user as" in text
    assert "- Reply in" in text
    assert "- Mainly works on" in text
    assert text.count("<!-- observed:") == 3


def test_skills_have_valid_frontmatter_and_budget() -> None:
    skills = [rel for rel in manifest.FRAMEWORK_OWNED if rel.startswith("skills/")]
    assert len(skills) == 5
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
    assert "hooks" not in data


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
    assert not set(manifest.RETIRED) & set(manifest.FRAMEWORK_OWNED + manifest.USER_OWNED)
    assert "skills/hub-jobs/SKILL.md" in manifest.RETIRED


def test_templates_do_not_mention_removed_commands() -> None:
    for rel in manifest.all_templates():
        text = manifest.render(rel)
        assert "cc-hub jobs" not in text, rel
        assert "hub-jobs" not in text, rel
        assert "hook snippet" not in text and "hook test" not in text, rel
        assert "blocklist" not in text, rel
        for sub in ("hosts run", "hosts check", "hosts push", "hosts pull", "memory stats"):
            assert f"cc-hub {sub}" not in text, (rel, sub)


def test_skill_guidance_matches_verified_behaviour() -> None:
    adapt = manifest.render("skills/hub-adapt/SKILL.md")
    assert "cc-hub hook" in adapt  # only as the leftover to remove
    cc_connect = manifest.render("skills/hub-cc-connect/SKILL.md")
    # cc-connect 1.5.0 has `cron list|edit|del` on its CLI (cmd/cc-connect/cron.go).
    assert "cc-connect cron list" in cc_connect
    assert "cc-connect cron del <id>" in cc_connect
    assert "/cron list" in cc_connect  # what the user types in the chat
    hosts = manifest.render("skills/hub-hosts/SKILL.md")
    assert "ssh -o BatchMode=yes" in hosts
    assert "There is no `hosts add` yet; edit `hosts.toml` by hand." in hosts


CRON_FRONTMATTER = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.S)
# Values `cc-connect cron add --session-mode` accepts (core/cron.go, 1.5.0).
SESSION_MODES = ("reuse", "new_per_run")


def test_cron_definitions_have_schedule_default_and_session() -> None:
    crons = [
        rel for rel in manifest.FRAMEWORK_OWNED
        if rel.startswith("cron/") and rel != "cron/README.md"
    ]
    assert crons
    for rel in crons:
        m = CRON_FRONTMATTER.match(manifest.render(rel))
        assert m, rel
        fields = dict(line.split(": ", 1) for line in m.group("body").splitlines())
        assert {"schedule", "default", "session"} <= set(fields), rel
        assert fields["session"] in SESSION_MODES, rel


def test_cron_registration_passes_session_mode_and_desc() -> None:
    """A task's `session` only takes effect when the registration command passes it."""
    for rel in ("BOOTSTRAP.md", "cron/README.md", "skills/hub-cc-connect/SKILL.md"):
        text = manifest.render(rel)
        assert "--session-mode <session>" in text, rel
        assert '--desc "hub:<name>"' in text, rel
    # Bootstrap skips tasks that are already registered instead of adding duplicates.
    assert "cc-connect cron list" in manifest.render("BOOTSTRAP.md")


def test_templates_do_not_cite_hub_adapt_goals_by_number() -> None:
    for rel in manifest.all_templates():
        assert not re.search(r"hub-adapt goal \d", manifest.render(rel)), rel
    projects = manifest.render("skills/hub-projects/SKILL.md")
    assert "writable_roots" in projects and "docs/codex-sandbox.md" in projects


def test_hub_adapt_leaves_permissions_to_the_runtime() -> None:
    adapt = manifest.render("skills/hub-adapt/SKILL.md")
    for word in ("permissions.deny", "writable_roots", "Deny reads"):
        assert word not in adapt, word
    assert "do not change them here" in adapt
