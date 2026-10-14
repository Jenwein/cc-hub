# Apps

An app adds a capability to the hub, such as bookkeeping or machine
management. It is a directory of files: skills that teach the agent to use
some software, scheduled task definitions, setup steps and a skeleton for its
data. The software itself (for example beancount) is an ordinary program the
agent installs on the machine with your approval. cc-hub copies app files and
never runs anything an app provides.

Apps live in **taps**: git repositories with one top-level directory per app.

## Use apps

    cc-hub tap add you/my-apps              # a GitHub repository; any git URL or local repository works
    cc-hub app search ledger
    cc-hub app install my-apps/ledger       # prints an overview, changes nothing
    cc-hub app install my-apps/ledger --ref <commit> --yes

A private tap needs your own git access (a credential helper or an ssh
key); a tap URL with a password or token in it is refused.

Usually you ask the agent instead; it runs the same commands, shows you the
overview, and after you agree installs the app and sets it up: installs the
software it needs (asking first), asks for your settings, and registers the
app's scheduled tasks with cc-connect.

`cc-hub app update <name>` shows what changed in the tap; `--yes` applies it.
`cc-hub app remove <name>` shows what removal involves; `--yes` removes the
app, keeps its data and drops the times you set for its tasks.
`cc-hub app list` shows each app's setup state on this machine and any
missing software.

To run an app's task at another time, or turn it off, ask the agent, or run
the command and let the agent re-register the task:

    cc-hub cron set plans/morning "0 7 * * *"   # <app>/<task>, then a quoted cron expression
    cc-hub cron set ledger/prices --off         # --on turns it back on
    cc-hub cron reset plans/morning             # back to the app's own time

The time is kept in `hub.toml`, so app updates and `cc-hub update` keep it.
`cc-hub cron list` shows every task with the time in force.

Installed apps are in `apps/`, which is not committed. `apps.lock` is: after
cloning the hub to another machine, `cc-hub app sync` restores the apps and
the agent sets them up there.

## Write an app

    my-apps/
    └── ledger/
        ├── app.toml               required
        ├── SETUP.md               optional: setup steps only this app needs
        ├── REMOVE.md              optional: what to undo before removal
        ├── skills/ledger/SKILL.md
        ├── cron/monthly.md        same format as the hub's cron/ files
        ├── scripts/
        └── seed/ledger/main.beancount

`app.toml`:

    [app]
    name = "ledger"                        # equals the directory name
    version = "0.1.0"
    description = "Plain-text bookkeeping with beancount"
    min_hub = "0.4.0"                      # optional
    issues = "https://example.com/issues"  # optional; GitHub taps need none

    [data]
    dirs = ["ledger"]

    [[requires]]
    name = "beancount"
    bin = "bean-check"
    install = "uv tool install beancount"

`install` may also be a table with `linux`, `macos` and `windows` keys.

Rules:

- Names (apps, skills, scheduled tasks, taps) use lowercase letters, digits
  and hyphens; skill names must not start with `hub-` and must be unique in the
  hub.
- Data directories are relative paths outside the hub's own files and
  folders. Each part uses only letters, digits, `.`, `_` and `-`, and does
  not start with `.`. Files under `seed/<data dir>/` are copied into them
  once and never overwritten. Personal settings belong there too;
  credentials belong in `.env` or `secrets/`.
- File names inside the app do not contain `~`, and no two of them differ
  only in letter case.
- `SETUP.md` steps check before they act, so setup can run again after an
  update. Prefer installs without root.
- Only regular files: no symlinks or submodules.

While developing, link your working copy so edits apply at once:

    cc-hub app install ~/dev/my-apps/ledger --link --yes

## Scheduled tasks

Each `cron/<task>.md` is one task, registered with cc-connect as
`hub:<app>/<task>` when the app is set up. The frontmatter decides the kind.

A **prompt task** wakes the agent on a schedule:

    ---
    schedule: "0 9 1 * *"        # five-field cron expression
    default: true                # registered at setup; false: only when the user turns it on
    session: new_per_run         # or reuse: run inside the chat's ongoing session
    silent: true                 # optional: no "⏰" line in the chat when a run starts
    ---
    What the agent does when the task fires.

A **script task** runs one command on a schedule without the agent, and
nothing it prints reaches the chat:

    ---
    schedule: "*/5 * * * *"
    default: true
    exec: "uv run apps/mail/scripts/mk.py poll"
    timeout_mins: 5              # optional, default 10
    ---
    What the command does. The agent shows the user this text and the command,
    and registers the task only if the user agrees.

`exec` is a program and its arguments only: no `&&`, pipes, redirects or
nested quotes, and no `"`, `$`, backtick or `\` (single quotes around an
argument with spaces, `/` in paths). It runs in the hub root through `sh -c`,
or PowerShell on Windows, with the environment of the cc-connect daemon
rather than the agent's, so `uv` and `cc-hub` must be on the daemon's PATH
([cc-connect.md](cc-connect.md#script-tasks-and-path)). Its output is never
seen; write your own log in the app's data directory.

An **on-demand task** has no schedule and runs only when woken. It is always
silent:

    ---
    on_demand: true
    default: true
    session: new_per_run
    ---
    What the agent does when a script wakes the task.

A script wakes it with `cc-hub cron wake <app>/<task>`. Exit status 0 means
cc-connect took the job, not that the agent has finished, so the usual
pattern is: a script task polls cheaply and records what is pending, wakes
the on-demand task when there is something, the agent acknowledges each item
through the app's script when done, and the script wakes the task again
later for anything not acknowledged. Keep two runs from working on the same
items.

A prompt or on-demand task with `allow` is **restricted**: its runs may run
only commands that start with one of the listed prefixes, and may read only
inside the hub (not `secrets/` or `.env*`). It needs `session: new_per_run`.
Use it for a task that reads outside content, such as mail from strangers,
and give that task a separate read-only command group in your script so one
prefix covers it:

    allow:
      - "uv run apps/mail/scripts/mk.py bg"

On Claude Code a hook enforces this even when the agent runs without
approvals ([cc-connect.md](cc-connect.md#restricted-tasks-and-yolo)). An app
that uses script, on-demand or restricted tasks needs `min_hub = "0.5.0"`.

## Publish

1. Push the tap to a public repository.
2. On GitHub, add the topic `cc-hub-tap`; others browse
   https://github.com/topics/cc-hub-tap. List the apps and the software they
   need in the README.
3. Others run `cc-hub tap add <owner>/<repo>` and
   `cc-hub app install <repo>/<app>`.
4. Release a new version by raising `version` in `app.toml`, committing and
   pushing; users update with `cc-hub app update <app>`.

Problems with an app go to its tap's issue tracker: `cc-hub feedback --app
<name>` prints where, and the agent drafts the issue for you to approve.
