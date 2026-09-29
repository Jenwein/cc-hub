# cc-connect configuration

Minimal `[[projects]]` entry pointing a Claude Code bot at the hub:

    [[projects]]
    name = "hub"
    admin_from = "<your user id on the platform>"

    [projects.agent]
    type = "claudecode"

    [projects.agent.options]
    work_dir = "/home/you/.cc-hub"     # absolute path; ~ expansion needs cc-connect > 1.5.1
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

For Codex use `type = "codex"` with the same `work_dir` and `env`, and read
[codex-sandbox.md](codex-sandbox.md).

## PATH under a daemon

`cc-connect daemon install` runs cc-connect from systemd, launchd or the
Windows Task Scheduler. Those do not read your shell profile, so PATH is often
just the system directories and `cc-hub`, `uv`, `claude` or `codex` are not
found. Put the full PATH in `[projects.agent.options.env]` as above.
`ENV.md` lists absolute paths the agent can fall back to.

## What the agent uses

- Attachments you send land in `<hub>/.cc-connect/attachments/<message id>/`;
  cc-connect appends their absolute paths to the prompt.
- The agent sends files back with `cc-connect send --file <absolute path>`
  (`--image`, `--tts`). 50 MB limit.
- Scheduled prompts: `cc-connect cron add --cron "<expr>" --prompt "<text>"`.
  The hub keeps definitions in `cron/*.md`; bootstrap registers the defaults.
- `/dir <path>` in the chat switches the working directory for the *next*
  session only. Keep `work_dir` on the hub and let the agent `cd` into projects.

## Approvals

`mode = "default"` relays every tool approval to the chat. With `/mode yolo`
or "allow all" the decision rests with the agent runtime's own permission
settings; the hub adds no enforcement of its own.

## Sessions and background work

cc-connect keeps one agent process per chat session and ends it, together
with everything it started, on `/new`, `/switch`, a turn that stays silent
longer than `idle_timeout_mins`, or a daemon restart. Background tasks and
subagents the agent starts therefore live as long as that session.
