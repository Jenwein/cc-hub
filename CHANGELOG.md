# Changelog

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
