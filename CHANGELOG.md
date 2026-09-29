# Changelog

## Unreleased

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
