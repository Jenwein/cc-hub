# Changelog

## 0.1.0 (unreleased)

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

### Migration notes

First release; nothing to migrate.
