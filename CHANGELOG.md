# Changelog

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
