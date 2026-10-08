# cc-hub

A hub directory convention and CLI for coding agents launched by
[cc-connect](https://github.com/chenhg5/cc-connect).

cc-connect bridges Claude Code, Codex and other agents to chat platforms and
starts the agent in a `work_dir`. cc-hub turns that directory into a **hub**:
the agent's home base on your machine, with a persona, memory, and a registry
of your projects and remote hosts. Permissions and background work stay with
cc-connect and the agent runtime; the hub adds conventions and routing, not
another layer of either.

The hub is agent-agnostic. It ships no Claude- or Codex-specific files; on
first run the agent creates the pointers its own ecosystem needs (`hub-adapt`).

## Quick start

    uv tool install cc-hub
    cc-hub init                     # creates ~/.cc-hub
    cc-hub doctor

Install from a regular terminal; on Windows not from a shell inside the
Claude desktop app (see [docs/install.md](docs/install.md)).

Point cc-connect at the hub (`work_dir = "/home/you/.cc-hub"`, see
[docs/cc-connect.md](docs/cc-connect.md)) and send the first message. The agent
follows `BOOTSTRAP.md`: names itself, learns who you are, registers projects,
adapts to its runtime, and deletes the bootstrap file.

## Commands

| Command | Purpose |
|---|---|
| `cc-hub init [dir]` | Seed a hub. Existing files are never overwritten. |
| `cc-hub doctor [--fix] [--json]` | Health checks: required files, memory budgets, pointers. |
| `cc-hub update [--dry-run]` | Refresh framework-owned files; user files untouched; backups kept. |
| `cc-hub memory log\|search\|recent` | Daily logs and long-term memory. |
| `cc-hub link <src> <dst>` | Symlink, junction or copy (platform decides). |
| `cc-hub where` | Print the hub directory and the package location. |
| `cc-hub version` | Print the cc-hub version. |

## Hub layout

    ~/.cc-hub/
    ├── AGENTS.md  AGENTS.local.md  BOOTSTRAP.md      instructions
    ├── SOUL.md  IDENTITY.md  USER.md                 persona and user
    ├── MEMORY.md  memory/YYYY-MM-DD.md               memory
    ├── projects.toml  hosts.toml  hub.toml           registries and config
    ├── skills/  cron/  scripts/  secrets/            skills, scheduled prompts, your scripts, credentials
    └── ENV.md  env.json                              generated state (gitignored)

Framework-owned files (`AGENTS.md`, `BOOTSTRAP.md`, `skills/hub-*`, `cron/README.md`)
are replaced by `cc-hub update`. Everything else is yours.

## Documentation

- [Install and upgrade](docs/install.md)
- [cc-connect configuration](docs/cc-connect.md)
- [Windows notes](docs/windows.md)
- [Codex sandbox notes](docs/codex-sandbox.md)
- [Manual acceptance checklist](docs/acceptance.md)
- [Design spec](docs/superpowers/specs/2026-09-22-cc-hub-design.md)

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

## License

MIT
