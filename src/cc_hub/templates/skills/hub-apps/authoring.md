# Writing a hub app

An app is a top-level directory of a tap (a git repository). The directory
name is the app name: lowercase letters, digits and hyphens.

    my-apps/                       the tap
    └── ledger/                    the app
        ├── app.toml               required
        ├── SETUP.md               optional: setup steps only this app needs
        ├── REMOVE.md              optional: what to undo before removal
        ├── skills/<skill>/SKILL.md
        ├── cron/<task>.md         scheduled tasks, same format as the hub's cron/ files
        ├── scripts/               called by the skills, the tasks and SETUP.md
        └── seed/<data dir>/...    copied into the hub once, never overwritten

## app.toml

    [app]
    name = "ledger"                        # equals the directory name
    version = "0.1.0"
    description = "Plain-text bookkeeping with beancount"
    min_hub = "0.4.0"                      # optional
    issues = "https://example.com/issues"  # optional; GitHub taps need none

    [data]
    dirs = ["ledger"]                      # the user's data, kept on update and removal

    [[requires]]
    name = "beancount"
    bin = "bean-check"                     # looked up on PATH, never run by cc-hub
    install = "uv tool install beancount"  # or a table with linux, macos, windows

## Scheduled tasks

`cron/<task>.md` is registered as `hub:<app>/<task>`. The hub's
`cron/README.md` has the full format; there are three kinds:

- **Prompt task** (`schedule`, `session`): wakes the agent on a schedule.
  `silent: true` drops cc-connect's "⏰" line at the start of each run.
- **Script task** (`exec: "uv run apps/<app>/scripts/poll.py"`, `schedule`,
  optional `timeout_mins`, default 10): runs one command without the agent.
  Write a program and its arguments only (no `&&`, pipes, redirects, `"`,
  `$`, backtick or `\`); it runs in the hub root with the cc-connect daemon's
  PATH. Its output is never seen: write your own log in the data directory.
- **On-demand task** (`on_demand: true`, `session`, no `schedule`): runs only
  when a script calls `cc-hub cron wake <app>/<task>`.

Patterns:

- **Poll, then wake.** A script task does the frequent, cheap check and wakes
  an on-demand task only when there is something for the agent. A wake only
  means cc-connect took it: record what is pending, have the agent
  acknowledge it through your script when done, and wake again later for
  anything not acknowledged. Do not let two runs work on the same items.
- **Restricted tasks.** A task that reads outside content (mail, web pages)
  gets `allow:` with command prefixes and `session: new_per_run`; its runs
  may use nothing else. Give such a task a separate read-only command group
  in your script, such as `uv run apps/<app>/scripts/tool.py bg ...`, so one
  `allow` prefix covers exactly what it needs.
- The user can change any task's time (`cc-hub cron set <app>/<task>`).
  `SETUP.md` may ask for a time and run that command.

An app that uses script, on-demand or restricted tasks needs
`min_hub = "0.5.0"`.

## Rules

- Skill names are unique in the hub and must not start with `hub-`.
- A data directory is a relative path; it must not be a hub file or folder
  (`memory`, `skills`, `cron`, `scripts`, `apps`, ...). Each part uses only
  letters, digits, `.`, `_` and `-`, and does not start with `.`.
- File names inside the app do not contain `~`, and no two of them differ
  only in letter case.
- Personal settings live in a file in the data directory, such as
  `ledger/config.toml`. Credentials go in `.env` or `secrets/`, never in the
  data directory, which is committed. For a credential the user gives in
  chat, provide a command that stores it under `secrets/`.
- Every `SETUP.md` step checks before acting, so setup can run again after an
  update. Prefer installs that need no root, such as `uv tool install`, so the
  agent can finish them once the user approves.
- Only regular files: no symlinks, no submodules.

## Develop

    cc-hub app install ~/dev/my-apps/ledger --link --yes

`apps/ledger` then links to the working copy, and edits apply at once.

## Publish

1. Commit and push the tap to a public repository.
2. On GitHub, add the topic `cc-hub-tap` so others find it at
   https://github.com/topics/cc-hub-tap; list the apps and the software they
   need in the README.
3. Others run `cc-hub tap add <owner>/<repo>`, then
   `cc-hub app install <repo>/<app>`.
4. For a new version, raise `version` in `app.toml`, commit and push; users
   run `cc-hub app update <app>`.
