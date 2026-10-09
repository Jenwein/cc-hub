# cc-hub

The home directory for coding agents launched by
[cc-connect](https://github.com/chenhg5/cc-connect).

A chat-driven agent has three parts: the chat (a bot on Feishu, WeChat,
Telegram and others), the bridge that connects the chat to your machine
(cc-connect), and a local directory the agent lives in. cc-hub is that
directory, the **hub**: the agent's persona, what it knows about you, its
memory, its operating instructions and its skills, plus a small CLI that
seeds, checks and upgrades them. It plays the role of an OpenClaw workspace.

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
follows `BOOTSTRAP.md`: adapts to its runtime, gets a name, learns how to
address you, registers its scheduled tasks, and deletes the bootstrap file.

## Commands

| Command | Purpose |
|---|---|
| `cc-hub init [dir]` | Seed a hub. Existing files are never overwritten. |
| `cc-hub doctor [--fix] [--json]` | Health checks: required files, memory budgets, pointers. |
| `cc-hub update [--dry-run]` | Refresh framework-owned files; user files untouched; backups kept. |
| `cc-hub memory log\|search\|recent` | Daily logs and long-term memory. |
| `cc-hub link <skills-dir>` | Link every hub skill into an agent's skills directory. |
| `cc-hub tap add\|list\|remove` | Register git repositories of apps (taps). |
| `cc-hub app search\|install\|list\|update\|remove\|sync\|setup-state` | Install, update and remove apps from taps. |
| `cc-hub feedback [--app NAME] [--json]` | Where to report a problem, with an environment block; sends nothing. |
| `cc-hub where` | Print the hub directory and the package location. |
| `cc-hub version` | Print the cc-hub version. |

## Hub layout

    ~/.cc-hub/
    ├── AGENTS.md  AGENTS.local.md  BOOTSTRAP.md      instructions
    ├── SOUL.md  IDENTITY.md  USER.md                 persona and user
    ├── MEMORY.md  memory/YYYY-MM-DD.md               memory
    ├── skills/  cron/  scripts/                      skills, scheduled prompts, your scripts
    ├── apps/  apps.lock                              installed apps and their record
    └── hub.toml                                      configuration

`cc-hub update` replaces only framework-owned files: `AGENTS.md` above its
closing marker, `BOOTSTRAP.md`, `skills/hub-*`, `cron/README.md`,
`cron/memory-consolidate.md`, `.gitignore` and `.gitattributes`. `cc-hub app`
manages `apps/` and `apps.lock`; an app's data, in the directories it
declares, is yours.
Everything else is yours too, including whatever you or cc-connect add below
the closing marker of `AGENTS.md`.

The hub is a git repository: cc-hub commits what its commands change and the
agent commits after each task. See [docs/backup.md](docs/backup.md) for a
private remote.

## Documentation

- [Install and upgrade](docs/install.md)
- [cc-connect configuration](docs/cc-connect.md)
- [Apps and taps](docs/apps.md)
- [Backing up the hub](docs/backup.md)
- [Windows notes](docs/windows.md)
- [Manual acceptance checklist](docs/acceptance.md)
- [Design spec](docs/superpowers/specs/2026-09-22-cc-hub-design.md)

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

## License

MIT
