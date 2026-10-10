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

The hub keeps task definitions in `cron/*.md`. The `hub-adapt` skill
registers the default ones from the direct chat it runs in, during bootstrap
and again on a new machine:

    cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"

and skips any whose `hub:<name>` is already in `cc-connect cron list`.

## Working directory

`/dir <path>` in the chat switches the working directory for the *next*
session only. Keep `work_dir` on the hub.
