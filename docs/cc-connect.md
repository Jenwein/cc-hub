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
registration commands, and the agent compares them with
`cc-connect cron list`, registering what is missing, replacing what differs
and deleting what is turned off or gone. A task is registered with the
description `hub:<name>` and a prompt that points at its definition file:

    cc-connect cron add --cron "0 3 * * *" --prompt "Scheduled task hub:memory-consolidate: follow the body of cron/memory-consolidate.md in the hub." --session-mode new_per_run --desc "hub:memory-consolidate"

so an edited body takes effect at the next run without registering again. A
script task is registered with `--exec` and then muted
(`cc-connect cron edit <id> mute true`). An on-demand task is registered
with `--silent` and then disabled; `cc-hub cron wake <task>` runs it with
`cc-connect cron exec <id>`, which runs disabled jobs too.

Change a task's time with `cc-hub cron set` or `cc-hub cron reset` (see the
README), not in cc-connect: the next registration puts the hub's time back.

## Script tasks and PATH

The cc-connect daemon runs a script task's command itself, in the project's
`work_dir` (the hub, so `cc-hub` finds it without `CC_HUB_DIR`). The command
inherits the daemon's environment, not `[projects.agent.options.env]`, which
only reaches the agent, and it gets no `CC_SESSION_KEY` or `CC_PROJECT`.
Under a service the daemon's PATH is whatever the service definition sets,
and `uv`, `cc-hub` and `cc-connect` (which `cc-hub cron wake` calls) must all
be on it.

<!-- To confirm on the acceptance machine (docs/acceptance.md, "Scheduled
task kinds" check 2): correct the steps below to what worked there, then
remove this comment. -->

`cc-connect daemon install` writes the PATH of the shell you run it from
into the service definition (systemd unit, launchd plist, or the start
script of the Windows task) and restarts the service. So the simplest way is
to install from a terminal in which all three are found, and to install
again whenever that PATH changes:

    command -v uv cc-hub cc-connect      # Windows: where.exe uv cc-hub cc-connect
    cc-connect daemon install

To set the PATH by hand instead:

- **Linux and WSL**, systemd user service `cc-connect`: run
  `systemctl --user edit cc-connect`, add

      [Service]
      Environment="PATH=/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin"

  and run `systemctl --user restart cc-connect`. This drop-in file overrides
  the PATH in the unit and stays when the unit is installed again. Check
  with `systemctl --user show cc-connect --property=Environment`.
- **macOS**, launchd agent `com.cc-connect.service`: set `PATH` under
  `EnvironmentVariables` in
  `~/Library/LaunchAgents/com.cc-connect.service.plist`, then run
  `cc-connect daemon stop` and `cc-connect daemon start`, which reload the
  file (`restart` does not). `cc-connect daemon install` rewrites this file.
- **Windows**, Task Scheduler task `cc-connect`: the task runs
  `%USERPROFILE%\.cc-connect\cc-connect-daemon.ps1`, whose
  `$env:PATH = '...'` line sets the PATH. Edit that line and run
  `cc-connect daemon restart`. `cc-connect daemon install` rewrites this
  file.

To check, register a script task with `exec: "cc-hub memory log probe"` and
a schedule a few minutes ahead: the line appears in today's log.

## Restricted tasks and YOLO

Scheduled prompt and on-demand tasks run while nobody watches. With
`mode = "bypassPermissions"` (YOLO) the agent runs every tool call without
asking, so a task that reads outside content, such as mail from strangers,
could be talked into running anything. A restricted task (one with `allow`
in its definition, see [apps.md](apps.md#scheduled-tasks)) is held to its
list by the guard:

- The guard is a Claude Code PreToolUse hook running `cc-hub cron guard`
  before every tool call, in every permission mode. `hub-adapt` installs it
  with `cc-hub cron guard-setup`, which adds it to the hub's
  `.claude/settings.json` and leaves your other settings alone. `.claude/` is
  not committed, so this happens on every machine.
- The hook command names cc-hub by its absolute path, with forward slashes
  and in double quotes, for example
  `"/home/you/.local/bin/cc-hub" cron guard`, so it runs whatever PATH
  Claude Code has. Run `cc-hub cron guard-setup` again after cc-hub moves:
  it rewrites the command of the guard entry instead of adding another.
- The hook recognises a restricted task's run by its first message, the
  task's pointer prompt (`Scheduled task hub:<name>: ...`). In such a run a
  Bash command must start with one of the `allow` prefixes and contain none
  of `;`, `&`, `|`, backtick, `$`, `<`, `>` or a line break; Read, Glob and
  Grep may only look inside the hub, or inside the directory an app
  installed with `--link` points to, never at `secrets/` or `.env*`; Glob
  and Grep must be given a subfolder as `path`, not the whole hub; every
  other tool is denied, with the reason. What it allows it allows outright,
  so a restricted run never asks for approval in the chat under
  `mode = "default"` either.
- In every other session it prints nothing and the normal permission flow
  applies. A run whose pointer names a task that is broken or does not exist
  gets every tool denied; so does a chat whose first message itself contains
  such `Scheduled task hub:<name>:` text (start a new session with `/new`).
- If the program the hook names no longer exists, for example after cc-hub
  was installed somewhere else, Claude Code cannot start the hook and
  carries on without it: the guard does nothing. `cc-hub doctor` warns about
  that, and when a restricted task exists but the hook is not installed; the
  fix is to run `hub-adapt` or `cc-hub cron guard-setup` again.
- Codex and other agents have no guard. Before registering a restricted task
  there, the agent tells you that the task would run without this safety belt
  and registers it only if you agree.

## Working directory

`/dir <path>` in the chat switches the working directory for the *next*
session only. Keep `work_dir` on the hub.
