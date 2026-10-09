# Changelog

## 0.4.0 - 2026-10-09

### Added

- Apps. `cc-hub tap add|list|remove` registers git repositories of apps
  (taps; `owner/repo` means a GitHub repository), and `cc-hub app
  search|install|list|update|remove|sync|setup-state` manages apps in
  `apps/<name>/`. Install, update and remove print what will happen and act
  only with `--yes`. `apps.lock` records taps and installed apps and is
  committed; `apps/` is gitignored and `cc-hub app sync` restores it.
- The `hub-apps` skill: setting apps up (software with the user's approval,
  `SETUP.md`, scheduled tasks named `hub:<app>/<task>`), updating, removing,
  and writing and publishing apps (`skills/hub-apps/authoring.md`).
- `cc-hub feedback [--app NAME]` prints where to report a problem and an
  environment block. The `hub-feedback` skill drafts the issue or comment and
  posts it only after the user agrees.
- `doctor` checks `apps` and `git`.
- `docs/apps.md` and `docs/backup.md`.

### Changed

- The hub's git repository is used. `init` makes the first commit and sets a
  repository-local identity when git has none; `update`, `tap`, `app` and
  `doctor --fix` commit the paths they change. `AGENTS.md` has a Git section:
  the agent commits after each task and never rewrites history. The nightly
  memory-consolidate task pushes when the hub has a remote.
- `hub-adapt` registers the hub's default scheduled tasks, so they are
  registered on every machine; `BOOTSTRAP.md` has five steps.
- `cc-hub link` and the `doctor` check `pointers` include the skills of
  installed apps.
- `cc-hub link` replaces an agent skills directory that is itself a link to
  the hub's `skills/` with a real directory of per-skill links.
- `.gitignore` ignores `apps/`.

### Migration notes

- Run `cc-hub update`. In a hub without commits it first commits everything
  that is not ignored (`cc-hub: init`), then the update.
- Then have the agent run `hub-adapt` so the new `hub-apps` and
  `hub-feedback` skills are linked; `cc-hub doctor` lists what is missing.
- A hub that was bootstrapped keeps its registered `hub:memory-consolidate`
  task. To back the hub up, add a private remote (`docs/backup.md`).

## 0.3.1 - 2026-10-09

### Changed

- `cc-hub link <skills-dir>` replaces `cc-hub link <src> <dst>`. It gives
  every skill in `skills/` its own directory link in an agent's skills
  directory (a symlink, or a junction on Windows), removes links to skills
  that are gone, and leaves other entries alone. It no longer copies when a
  link cannot be made.
- `hub-adapt` creates `CLAUDE.md` containing only `@AGENTS.md` for Claude
  Code, links skills with `cc-hub link`, and runs it again after a skill is
  added or removed.
- `doctor` `pointers` reports a missing `CLAUDE.md`, skills that are not
  linked, and links to skills that are gone. The `link-stale` check is
  removed.
- `BOOTSTRAP.md` names `skills/hub-adapt/SKILL.md`; `AGENTS.md` says new
  skills go in `skills/<name>/`.

### Migration notes

- Run `cc-hub update`, then have the agent run `hub-adapt`; `cc-hub doctor`
  lists what is missing.
- A skills directory that links to the whole `skills/` directory keeps
  working. A copied one has to be deleted before `cc-hub link`.

## 0.3.0 - 2026-10-08

### Removed

- `cc-hub env`, and the `ENV.md` and `env.json` it wrote.
- `cc-hub projects` with `projects.toml`, and `cc-hub hosts` with `hosts.toml`.
- The `hub-projects`, `hub-hosts` and `hub-cc-connect` skills.
- `doctor` checks `projects`, `hosts`, `env-stale` and `stale-hooks`.
- The `secrets/` directory is no longer created; it stays in `.gitignore`.
- Dependencies `psutil` and `charset-normalizer`.

### Changed

- `AGENTS.md` ends with a closing marker. `update` replaces only what is above
  it and keeps everything below, such as the block cc-connect appends for
  Codex after `/cron setup`. In a file without the marker, `update` keeps
  cc-connect's `<!-- cc-connect-instructions -->` block.
- `BOOTSTRAP.md` has six steps and asks only for a name, how to address the
  user, and the reply language.
- `hub.toml` has no `[env]` table.

### Migration notes

- `cc-hub update` backs up and removes the three skills, `ENV.md` and
  `env.json`; the backups are in `.cc-hub/backups/0.2.1/`.
- `cc-hub update` does not touch `projects.toml`, `hosts.toml`, `secrets/` or
  the `[env]` table in `hub.toml`; nothing reads them any more.

## 0.2.1 - 2026-09-30

Template fixes; no command changes. The cron guidance is now checked against
the cc-connect 1.5.0 source. First release published on PyPI:
`uv tool install cc-hub`.

### Fixed

- Cron tasks now get the session mode they declare. `BOOTSTRAP.md`,
  `cron/README.md` and `hub-cc-connect` register a task with
  `--session-mode <session> --desc "hub:<name>"`, where `<name>` is the file
  name without `.md`. Bootstrap checks `cc-connect cron list` first and skips
  tasks that are already registered. Before this, the `session` field was
  never passed on, so `memory-consolidate` ran inside the reused chat session.
- `hub-cc-connect` lists and edits schedules with `cc-connect cron list`,
  `cron edit` and `cron del`. It only deletes a schedule when the user asks.
  It also says a task belongs to the chat it was registered from.
- `hub-projects` no longer points at "hub-adapt goal 4", which 0.2.0 removed.
  After `projects add` under Codex, the agent tells the user to add the path
  to `writable_roots` (`docs/codex-sandbox.md`) and leaves the sandbox alone.
- `AGENTS.md` refers to `hub-cc-connect` for scheduling instead of repeating
  an incomplete command.

### Migration notes

- Run `cc-hub update` to get the fixed `AGENTS.md`, `BOOTSTRAP.md`,
  `cron/README.md` and skills.
- A hub bootstrapped with 0.1.0 or 0.2.0 registered `memory-consolidate`
  without a session mode or description. Ask the agent to fix it, or do it
  yourself: find the task's id with `cc-connect cron list` (it shows the start
  of the prompt), then run
  `cc-connect cron edit <id> session_mode new_per_run` and
  `cc-connect cron edit <id> description hub:memory-consolidate`.

## 0.2.0 - 2026-09-29

The hub is a convention and a router. Permissions and background work belong
to cc-connect and the agent runtime, so the hub no longer duplicates them.

### Removed

- `cc-hub hook` (pre-tool-use blocklist, post-tool-use audit log, `snippet`,
  `test`) and the `[hooks]` table in `hub.toml`. Approvals stay with
  cc-connect's `mode`, and permissions with the agent runtime's own settings.
  A live test on native Windows also showed the hook failing open under both
  Claude Code and Codex.
- `cc-hub jobs` and the `hub-jobs` skill. Long-running work uses the agent
  runtime's own background facilities, which cc-connect ends together with
  the chat session (`/new`, `/switch`, idle timeout, daemon restart).
- `doctor` checks `jobs-lost` and the hook part of `pointers`.
- `cc-hub hosts check|run|push|pull`. `hosts.toml` and `hosts list` remain the
  registry; the agent connects with `ssh` and `scp` itself (`hub-hosts`).
- `cc-hub memory stats`; `doctor` already reports the memory budgets.
- `doctor` check `daemon-path` and the daemon-visibility note in `ENV.md`: the
  PATH cc-connect gives the agent is cc-connect's configuration.
- The permissions goal of `hub-adapt` (deny reads, Codex `writable_roots`).
  Permissions and sandbox settings are left to the user and the runtime; see
  `docs/codex-sandbox.md` for making projects writable under Codex.

### Added

- `doctor` check `stale-hooks`: warns when a hook configuration in the hub
  still calls `cc-hub hook`.
- `update` backs up and removes framework files that are no longer shipped
  (`skills/hub-jobs/SKILL.md`).
- `projects list --json` and `projects show --json` include `resolved`, the
  absolute path; stored paths stay portable (`~/...`).

### Fixed

- `doctor` `pointers` judges only runtimes set up in this hub, so an installed
  but unused agent is no longer a warning. `CLAUDE.md` is optional, as
  `hub-adapt` says; one without `@AGENTS.md` is reported because it hides
  `AGENTS.md`.
- `where` prints the package location even when no hub is found (exit 1).
- `memory search` ignores HTML comments, such as template notes.
- `update` edits `hub.toml` in place and keeps your comments and layout.
- `projects list` and `projects show` print absolute paths instead of `~/...`.
- Install docs no longer point at PyPI, where cc-hub is not published yet, and
  warn against installing from a shell inside the Claude desktop app on
  Windows. The release workflow publishes to PyPI only when the repository
  variable `PUBLISH_PYPI` is `true`.

### Migration notes

- Run `cc-hub update`. It removes `skills/hub-jobs/SKILL.md`; the backup is in
  `.cc-hub/backups/<old version>/`.
- Remove the `cc-hub hook ...` entries from `.claude/settings.json` and
  `.codex/hooks.json`, or ask the agent to run the `hub-adapt` skill;
  `cc-hub doctor` lists leftovers as `stale-hooks`. Until then every tool call
  runs a command that no longer exists, and on Linux and macOS Claude Code
  treats its exit status as a block.
- The `jobs/` and `logs/` directories and the `[hooks]` table in `hub.toml`
  are no longer used and can be deleted.

## 0.1.0 - 2026-09-23

### Added

- `cc-hub init`, `doctor`, `update`: seed, check and upgrade a hub directory.
- `cc-hub env`: machine probe written to `ENV.md` / `env.json`.
- `cc-hub memory`: daily logs, search, recent, stats.
- `cc-hub projects`: registry of local project directories.
- `cc-hub jobs`: detached background jobs with a supervising runner.
- `cc-hub hosts`: ssh/scp with base64-wrapped remote commands.
- `cc-hub hook`: pre-tool-use blocklist, post-tool-use audit log, snippet.
- Blocklist rule `find-delete` for recursive deletes of root or home via `find`.
- `cc-hub link`: symlink / junction / copy.
- Hub templates: `AGENTS.md`, `BOOTSTRAP.md`, persona files, six `hub-*` skills,
  `cron/memory-consolidate.md`.

### Known limitations

- The Codex hook payload shape is inferred from the documentation, not verified
  against a real Codex run; the fixtures in `tests/fixtures` encode that guess.
- The native-Windows code paths (junctions, `taskkill`, `.cmd` shims) are
  reasoned about rather than CI-executed: CI runs the suite on windows-latest,
  but the jobs and kill paths are not exercised there.

### Migration notes

First release; nothing to migrate.
