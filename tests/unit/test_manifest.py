# -*- coding: utf-8 -*-
import re
import tomllib
from datetime import date

from cc_hub import __version__, manifest

FRONTMATTER = re.compile(
    r"^---\nname: (?P<name>[a-z0-9-]+)\ndescription: (?P<desc>.+)\n---\n", re.S
)
CLI_REF = re.compile(r"`cc-hub ([a-z][a-z-]*)")
SKILL_REF = re.compile(r"(?<!cc-)\bhub-[a-z][a-z-]*")
CRON_FRONTMATTER = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.S)
# Values `cc-connect cron add --session-mode` accepts (core/cron.go, 1.5.0).
SESSION_MODES = ("reuse", "new_per_run")


def _command_names() -> set[str]:
    from cc_hub.cli import app

    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    return names | {g.name for g in app.registered_groups}


def _skill_names() -> set[str]:
    return {rel.split("/")[1] for rel in manifest.FRAMEWORK_OWNED if rel.startswith("skills/")}


def test_every_manifest_entry_has_a_template_file() -> None:
    for rel in manifest.all_templates():
        assert manifest.template_source(rel).is_file(), rel


def test_templates_are_lf_and_have_no_bom() -> None:
    for rel in manifest.all_templates():
        raw = manifest.template_source(rel).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), rel
        assert b"\r\n" not in raw, rel


def test_agents_md_within_budget_and_ends_with_the_tail_marker() -> None:
    text = manifest.render("AGENTS.md")
    assert len(text.splitlines()) <= 150
    assert text.endswith(manifest.TAIL_MARKER + "\n")
    assert text.count(manifest.TAIL_MARKER) == 1
    assert set(manifest.KEEPS_TAIL) <= set(manifest.FRAMEWORK_OWNED)


def test_agents_md_points_at_the_cron_readme() -> None:
    assert "cron/README.md" in manifest.render("AGENTS.md")


def test_user_md_has_a_placeholder_for_each_bootstrap_question() -> None:
    """BOOTSTRAP.md asks how to address the user and which language to use."""
    text = manifest.render("USER.md")
    assert "- Address the user as" in text
    assert "- Reply in" in text
    assert text.count("<!-- observed:") == 2


def test_skills_have_valid_frontmatter_and_budget() -> None:
    assert _skill_names() == {"hub-adapt", "hub-memory"}
    for rel in manifest.FRAMEWORK_OWNED:
        if not rel.startswith("skills/"):
            continue
        text = manifest.render(rel)
        m = FRONTMATTER.match(text)
        assert m, rel
        assert m.group("name") == rel.split("/")[1]
        assert len(text.splitlines()) <= 100, rel


def test_hub_toml_renders_with_version_and_created() -> None:
    text = manifest.render("hub.toml", name="my-hub", created=date(2026, 9, 22))
    data = tomllib.loads(text)
    assert set(data) == {"hub", "memory"}
    assert data["hub"]["name"] == "my-hub"
    assert data["hub"]["template_version"] == __version__
    assert data["hub"]["created"] == date(2026, 9, 22)
    assert data["memory"] == {"max_lines": 200, "recent_days": 2}


def test_gitignore_maps_to_underscore_source() -> None:
    assert manifest.template_source(".gitignore").name == "_gitignore"
    text = manifest.render(".gitignore")
    for line in (".env", "secrets/", ".cc-hub/", ".cc-connect/", "CLAUDE.md", ".claude/"):
        assert line in text.splitlines(), line


def test_ownership_sets_are_disjoint() -> None:
    assert not set(manifest.FRAMEWORK_OWNED) & set(manifest.USER_OWNED)
    assert manifest.HUB_TOML not in manifest.FRAMEWORK_OWNED + manifest.USER_OWNED
    assert set(manifest.ONE_TIME) <= set(manifest.FRAMEWORK_OWNED)
    assert not set(manifest.RETIRED) & set(manifest.all_templates())
    for rel in manifest.RETIRED:
        assert not manifest.template_source(rel).exists(), rel


def test_templates_reference_only_existing_commands_and_skills() -> None:
    commands, skills = _command_names(), _skill_names()
    for rel in manifest.all_templates():
        text = manifest.render(rel)
        assert set(CLI_REF.findall(text)) <= commands, rel
        assert set(SKILL_REF.findall(text)) <= skills, rel


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
    for rel in ("BOOTSTRAP.md", "cron/README.md"):
        text = manifest.render(rel)
        assert "--session-mode <session>" in text, rel
        assert '--desc "hub:<name>"' in text, rel
    # Bootstrap skips tasks that are already registered instead of adding duplicates.
    assert "cc-connect cron list" in manifest.render("BOOTSTRAP.md")


def test_hub_adapt_leaves_permissions_to_the_runtime() -> None:
    assert "do not change them here" in manifest.render("skills/hub-adapt/SKILL.md")


def test_hub_adapt_routes_through_one_line_imports_and_per_skill_links() -> None:
    adapt = manifest.render("skills/hub-adapt/SKILL.md")
    assert "`cc-hub link <your skills directory>`" in adapt
    assert "`CLAUDE.md` containing only `@AGENTS.md`" in adapt
    assert "`skills/<name>/`" in adapt
    assert "`skills/<name>/`" in manifest.render("AGENTS.md")


def test_bootstrap_names_the_hub_adapt_file() -> None:
    """Skills are not routed yet during bootstrap, so the agent opens the file by path."""
    assert "`skills/hub-adapt/SKILL.md`" in manifest.render("BOOTSTRAP.md")
