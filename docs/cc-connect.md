# cc-connect configuration

Minimal `[[projects]]` entry pointing a Claude Code bot at the hub:

    [[projects]]
    name = "hub"
    admin_from = "<your user id on the platform>"

    [projects.agent]
    type = "claudecode"

    [projects.agent.options]
    work_dir = "/home/you/.cc-hub"     # absolute path
    mode = "default"                    # approvals are relayed to the chat

    [projects.agent.options.env]
    PATH = "/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin"
    PYTHONUTF8 = "1"
    CC_HUB_DIR = "/home/you/.cc-hub"  # only needed when the hub is not ~/.cc-hub

    [[projects.platforms]]
    type = "feishu"

    [projects.platforms.options]
    app_id = "${FEISHU_APP_ID}"
    app_secret = "${FEISHU_APP_SECRET}"
    allow_from = "*"

For Codex use `type = "codex"` with the same `work_dir` and `env`.

## PATH under a service

`cc-connect daemon install` runs cc-connect from systemd, launchd or the
Windows Task Scheduler. Those do not read your shell profile, so PATH is often
just the system directories and `cc-hub` is not found. Put the full PATH in
`[projects.agent.options.env]` as above.

## What cc-connect tells the agent

cc-connect explains its own commands to the agent: sending files back
(`cc-connect send`), scheduled tasks (`cc-connect cron`), timers and relays.

- Claude Code gets this in its system prompt automatically.
- Codex and other agents without system-prompt support get it once you send
  `/cron setup` in the chat: cc-connect appends a block marked
  `<!-- cc-connect-instructions -->` to the hub's `AGENTS.md`. The block sits
  below the hub's closing marker, so `cc-hub update` keeps it.

## Scheduled tasks

The hub keeps task definitions in `cron/*.md`, and installed apps in
`apps/<app>/cron/*.md`. The agent registers them from the direct chat it
runs in: the `hub-adapt` skill the hub's own tasks (during bootstrap and on a
new machine), the `hub-apps` skill an app's tasks during setup. Both follow
the hub's `cron/README.md`: `cc-hub cron list --json` gives every task's
registration command, and the agent compares it with
`cc-connect cron list`, registering what is missing, replacing what differs
and deleting what is turned off or gone. A task is registered with the
description `hub:<name>` and a prompt that points at its definition file:

    cc-connect cron add --cron "0 3 * * *" --prompt "Scheduled task hub:memory-consolidate: follow the body of cron/memory-consolidate.md in the hub." --session-mode new_per_run --desc "hub:memory-consolidate" --silent

so an edited body takes effect at the next run without registering again.
`--silent` stops cc-connect from posting a line in the chat each time a task
fires; the chat shows only what the agent replies.

Change a task's time with `cc-hub cron set` or `cc-hub cron reset` (see the
README), not in cc-connect: the next registration puts the hub's time back.

## Reports

`cc-hub report send` delivers a report itself, so that what the apps' report
commands print reaches the chat without passing through the agent. It runs

    cc-connect send -p <project> -s <session> --stdin

and writes the report to its standard input. `<project>` and `<session>` are
the `CC_PROJECT` and `CC_SESSION_KEY` that cc-connect sets for the agent
process; cc-hub inherits them when the agent runs it, and leaves out one that
is unset. The PATH is inherited the same way, so `cc-connect` must be on the
PATH given to the agent in `[projects.agent.options.env]` (see "PATH under a
service"), next to `cc-hub`. When `cc-connect` is missing or does not answer
within 60 seconds, `send` fails with a message, nothing is recorded, and the
task replies with that error.

Every task is registered with `--silent`, so no line appears when a report
task fires. A reply of exactly `NO_REPLY` makes cc-connect send nothing: a
report task ends with it once the report is sent or when there is nothing to
send, and so does a background task whose result was left as a note for a
report.

A section command that an app provides runs only after the user approved it
on this machine (see [apps.md](apps.md), "Reports").

## Working directory

`/dir <path>` in the chat switches the working directory for the *next*
session only. Keep `work_dir` on the hub.
