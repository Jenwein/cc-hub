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

    cc-connect cron add --cron "0 3 * * *" --prompt "Scheduled task hub:memory-consolidate: follow the body of cron/memory-consolidate.md in the hub." --session-mode new_per_run --desc "hub:memory-consolidate"

so an edited body takes effect at the next run without registering again.

Change a task's time with `cc-hub cron set` or `cc-hub cron reset` (see the
README), not in cc-connect: the next registration puts the hub's time back.

## Working directory

`/dir <path>` in the chat switches the working directory for the *next*
session only. Keep `work_dir` on the hub.
