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
    assert _skill_names() == {"hub-adapt", "hub-apps", "hub-feedback", "hub-memory"}
    for rel in manifest.FRAMEWORK_OWNED:
        if not (rel.startswith("skills/") and rel.endswith("/SKILL.md")):
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
    for line in (".env", "secrets/", "/apps/", ".cc-hub/", ".cc-connect/", "CLAUDE.md", ".claude/"):
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


def test_registration_texts_use_cron_list() -> None:
    for rel in ("cron/README.md", "skills/hub-adapt/SKILL.md", "skills/hub-apps/SKILL.md"):
        text = manifest.render(rel)
        assert "cc-hub cron list --json" in text, rel
        assert '--prompt "<body>"' not in text, rel
    readme = manifest.render("cron/README.md")
    for word in ("schedule:", "default:", "session:", "cc-hub cron set", "cc-hub cron reset"):
        assert word in readme, word


def test_agents_md_never_handles_credentials() -> None:
    text = manifest.render("AGENTS.md")
    assert "- Never read, print, or copy credentials: `.env` files, keys, tokens.\n" in text
    assert len(text.splitlines()) <= 150


def test_cron_readme_registers_from_the_listed_command() -> None:
    """The command comes from `cron list --json`; the README says how to run and compare it."""
    text = " ".join(manifest.render("cron/README.md").split())
    for phrase in ("`command`", "`hub:<name>`", "cc-connect cron list",
                   "cc-connect cron info <id>", "cc-connect cron del <id>", "`enabled: false`",
                   "`--cron`", "`--prompt`", "`--session-mode`", "direct chat"):
        assert phrase in text, phrase


def _section(text: str, heading: str) -> str:
    return " ".join(text.split(heading, 1)[1].split("\n## ", 1)[0].split())


def test_time_changes_are_registered_in_a_direct_chat() -> None:
    readme = manifest.render("cron/README.md")
    change = _section(readme, "## Change a time")
    for phrase in ("`<old id>`", "direct chat", "registration command", "`hub.toml`",
                   'cc-hub cron set <name> "<expr>"', "cc-hub cron reset <name>"):
        assert phrase in change, phrase
    apps = _section(manifest.render("skills/hub-apps/SKILL.md"), "## Change a task's time")
    assert "follow \"Change a time\" in `cron/README.md`" in apps


BROKEN_TASK = (
    "If the file is broken, reply with the reason, and that the user can fix it "
    "(`cc-hub doctor` says how) or remove the job the same way."
)


def test_agents_md_handles_a_task_without_a_definition() -> None:
    text = " ".join(manifest.render("AGENTS.md").split())
    assert "do not guess" in text
    assert "cc-connect cron del <id>" in text
    # only a missing definition is gone for good; a broken one is reported so it can be fixed
    assert "If the file is missing, reply that `hub:<name>` has no definition" in text
    assert BROKEN_TASK in text


def test_cron_readme_tells_a_missing_from_a_broken_definition() -> None:
    fires = _section(manifest.render("cron/README.md"), "## When a task fires")
    assert "do not guess" in fires and "cc-connect cron del <id>" in fires
    assert BROKEN_TASK in fires


def test_cron_readme_keeps_the_registered_job_of_a_row_with_an_error() -> None:
    """A row with an `error` is `enabled: false` only because it cannot be registered now;
    deleting its job would stop a working task over, say, a typo in an override."""
    register = _section(manifest.render("cron/README.md"), "## Register")
    assert (
        "With an `error`: leave its registered job, if any, as it is, and tell the user what "
        "is wrong; `cc-hub doctor` says how to fix it."
    ) in register
    assert "Without an `error`, `enabled: false`: if `hub:<name>` is registered, delete it." in (
        register
    )


def test_hub_adapt_registers_the_hubs_rows() -> None:
    text = " ".join(manifest.render("skills/hub-adapt/SKILL.md").split())
    assert "whose `source` is `hub`" in text
    assert "Follow `cron/README.md`" in text


def test_bootstrap_leaves_scheduled_tasks_to_hub_adapt() -> None:
    text = manifest.render("BOOTSTRAP.md")
    assert "cc-connect cron add" not in text
    assert "scheduled tasks" in text
    assert "5. **Finish.**" in text and "6." not in text


def test_agents_md_has_the_git_rules() -> None:
    text = manifest.render("AGENTS.md")
    assert "## 3. Git" in text
    for phrase in ("git commit", "-- <paths>", "reset --hard", "force push", "hub-memory"):
        assert phrase in text, phrase


def test_consolidation_commits_and_pushes() -> None:
    memory = manifest.render("skills/hub-memory/SKILL.md")
    assert "git push" in memory and "do not pull or merge" in memory
    assert "pushed" in manifest.render("cron/memory-consolidate.md")


REPORT_SCHEDULES = {
    "daily": "0 8 * * *",
    "weekly": "0 20 * * 0",
    "monthly": "0 9 1 * *",
    "quarterly": "10 9 1 1,4,7,10 *",
    "yearly": "20 9 1 1 *",
}


def test_report_tasks_have_the_default_schedules() -> None:
    for period, schedule in REPORT_SCHEDULES.items():
        rel = f"cron/report-{period}.md"
        assert rel in manifest.FRAMEWORK_OWNED
        text = manifest.render(rel)
        m = CRON_FRONTMATTER.match(text)
        assert m, rel
        fields = dict(line.split(": ", 1) for line in m.group("body").splitlines())
        assert fields == {
            "schedule": f'"{schedule}"', "default": "false", "session": "new_per_run",
        }, rel
        body = text[m.end():]
        assert f"cc-hub report plan {period} --json" in body, rel
        assert f"cc-hub report send {period}" in body, rel
        assert f"cc-hub report put {period} <app> --text" in body, rel
        assert body.count("NO_REPLY") == 2, rel
        assert body.startswith(f"{period.capitalize()} report. Run "), rel
        assert all(other not in body for other in REPORT_SCHEDULES if other != period), rel


def test_consolidation_leaves_a_report_note() -> None:
    text = " ".join(manifest.render("cron/memory-consolidate.md").split())
    assert 'cc-hub report note daily --from memory-consolidate -- "<the paragraph>"' in text
    assert "NO_REPLY" in text
    assert "If the push failed, reply with that paragraph." in text
    assert "pushed" in text


def test_cron_readme_covers_reports() -> None:
    readme = manifest.render("cron/README.md")
    register = _section(readme, "## Register")
    assert "cc-connect cron info <id> silent" in register and "`true`" in register
    reports = _section(readme, "## Reports")
    for phrase in ("cc-hub report language", "cc-hub report section", "silent",
                   "cc-hub cron set report-<period> --on", "cc-hub report list --json",
                   "cc-hub report note", "NO_REPLY", "`language`", "urgent"):
        assert phrase in reports, phrase
    section = readme.split("## Reports", 1)[1].split("\n## ", 1)[0]
    assert len(section.strip().splitlines()) + 1 <= 25


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


def test_agents_md_routes_to_apps() -> None:
    text = manifest.render("AGENTS.md")
    for phrase in ("`apps/<name>/`", "`apps.lock`", "cc-hub app list", "`hub-apps`",
                   "never override"):
        assert phrase in text, phrase


def test_hub_apps_skill_covers_the_lifecycle() -> None:
    skill = manifest.render("skills/hub-apps/SKILL.md")
    for phrase in ("--yes", "setup-state", "hub:<name>/*", "cc-connect cron del",
                   "direct chat", "authoring.md", "cc-hub app sync"):
        assert phrase in skill, phrase
    authoring = manifest.render("skills/hub-apps/authoring.md")
    for phrase in ("app.toml", "[[requires]]", "--link", "cc-hub-tap", "seed/"):
        assert phrase in authoring, phrase


def test_hub_adapt_and_cron_readme_mention_app_tasks() -> None:
    adapt = manifest.render("skills/hub-adapt/SKILL.md")
    assert "installed apps" in adapt and "hub-apps" in adapt
    assert "hub:<app>/<task>" in manifest.render("cron/README.md")


def test_hub_feedback_asks_before_filing() -> None:
    skill = manifest.render("skills/hub-feedback/SKILL.md")
    for phrase in ("cc-hub feedback", "gh issue list", "gh issue create", "gh issue comment",
                   "--body-file", "USER.md", "MEMORY.md", "agrees", "group chat",
                   "repository"):
        assert phrase in skill, phrase
    agents = manifest.render("AGENTS.md")
    assert "`hub-feedback`" in agents and "publishes" in agents
    assert "commenting" in agents


def test_gitattributes_keeps_line_endings() -> None:
    assert manifest.template_source(".gitattributes").name == "_gitattributes"
    assert ".gitattributes" in manifest.FRAMEWORK_OWNED
    text = manifest.render(".gitattributes")
    assert "* -text" in text.splitlines()
    assert "\r" not in text


def test_agents_md_undo_recipe_restores_the_version_before_the_change() -> None:
    text = " ".join(manifest.render("AGENTS.md").split())
    assert "git restore --source <commit>~1 -- <path>" in text
    assert "where `<commit>` is the change to undo" in text
    assert "--source <commit> --" not in text



def test_hub_apps_setup_replaces_stale_scheduled_tasks() -> None:
    skill = manifest.render("skills/hub-apps/SKILL.md")
    setup = " ".join(skill.split("## Set up", 1)[1].split("\n## ", 1)[0].split())
    assert "follow `cron/README.md` for every row whose `source` is the app" in setup
    readme = " ".join(manifest.render("cron/README.md").split())
    # a registered task that differs is deleted and added again; one without a row is deleted
    assert "delete it and register it again" in readme
    assert "has no row" in readme
    remove = " ".join(skill.split("## Remove", 1)[1].split("\n## ", 1)[0].split())
    assert "time overrides" in remove


def test_authoring_covers_scheduled_tasks() -> None:
    text = " ".join(manifest.render("skills/hub-apps/authoring.md").split())
    for phrase in ("`hub:<app>/<task>`", "`schedule`, `default` and `session`",
                   "cc-hub cron set <app>/<task>", 'min_hub = "0.5.0"'):
        assert phrase in text, phrase
