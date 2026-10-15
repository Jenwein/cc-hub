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

In the table, `<…>` is a value you must give, `[…]` is optional, and `a|b`
lists the subcommands of a group.

| Command | Purpose |
|---|---|
| `cc-hub init [dir]` | Seed a hub. Existing files are never overwritten. |
| `cc-hub doctor [--fix] [--json]` | Health checks: required files, memory budgets, pointers. |
| `cc-hub update [--dry-run]` | Refresh framework-owned files; user files untouched; backups kept. |
| `cc-hub memory log\|search\|recent` | Daily logs and long-term memory. |
| `cc-hub link <skills-dir>` | Link every hub skill into an agent's skills directory. |
| `cc-hub tap add\|list\|remove` | Register git repositories of apps (taps). |
| `cc-hub app search\|install\|list\|update\|remove\|sync\|setup-state` | Install, update and remove apps from taps. |
| `cc-hub cron list\|set\|reset\|wake\|guard-setup` | Scheduled tasks: list them, change their times, wake on-demand tasks, guard restricted tasks. |
| `cc-hub feedback [--app NAME] [--json]` | Where to report a problem, with an environment block; sends nothing. |
| `cc-hub where` | Print the hub directory and the package location. |
| `cc-hub version` | Print the cc-hub version. |

Examples:

    cc-hub cron list                                # every scheduled task and the time in force
    cc-hub cron set plans/morning "0 7 * * *"       # run the plans app's morning task at 07:00
    cc-hub cron set ledger/prices --off             # turn a task off (--on turns it back on)
    cc-hub cron reset plans/morning                 # back to the time the app's file gives
    cc-hub cron wake mail/triage                    # run an on-demand task now; scripts do this

Quote the cron expression, or the shell splits it. A task's name is its file
name without `.md` for the hub's own tasks (`cron/<name>.md`), and
`<app>/<task>` for an app's. Times you set are kept in `hub.toml`, so
`cc-hub update` and app updates keep them; `set` and `reset` print the steps
that re-register the task with cc-connect, which the agent runs. Usually you
just ask the agent. `cc-hub cron guard-setup` installs the guard for
restricted tasks on Claude Code (see [docs/cc-connect.md](docs/cc-connect.md)).

## Hub layout

    ~/.cc-hub/
    ├── AGENTS.md  AGENTS.local.md  BOOTSTRAP.md      instructions
    ├── SOUL.md  IDENTITY.md  USER.md                 persona and user
    ├── MEMORY.md  memory/YYYY-MM-DD.md               memory
    ├── skills/  cron/  scripts/                      skills, scheduled tasks, your scripts
    ├── apps/  apps.lock                              installed apps and their record
    └── hub.toml                                      configuration and task times you set

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
