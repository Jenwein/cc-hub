# Scheduled tasks

Each `*.md` file here, except this one, is one task: YAML frontmatter, then a
body. Its name is the file name without `.md`. Installed apps keep their
tasks in `apps/<app>/cron/<task>.md`, named `<app>/<task>`. Scheduling
belongs to cc-connect: every task is registered there with the description
`hub:<name>` (`hub:<app>/<task>` for an app's task).

## Kinds

**Prompt task**: wakes the agent on a schedule.

    ---
    schedule: "0 3 * * *"     # five-field cron expression
    default: true             # registered on every machine; false: only when turned on
    session: new_per_run      # reuse | new_per_run (cc-connect --session-mode)
    silent: true              # optional: no "⏰" line in the chat when it starts
    ---
    What the agent does when the task fires.

**Script task**: runs one command on a schedule without the agent. It is
muted: nothing it prints reaches the chat, or anywhere else.

    ---
    schedule: "*/5 * * * *"
    default: true
    exec: "uv run apps/mail/scripts/mk.py poll"
    timeout_mins: 5           # optional, default 10
    ---
    What the command does, for the user and the agent. Not executed, not sent.

- `exec` is a program and its arguments, nothing else: no `&&`, pipes,
  redirects or nested quotes, and no `"`, `$`, backtick or `\`. Put single
  quotes around an argument with spaces; use `/` in paths.
- It runs in the hub root, through `sh -c` (PowerShell on Windows), with the
  environment and PATH of the cc-connect daemon, not the agent's.
- It takes no `session` and no `allow`; `silent` does not apply.

**On-demand task**: a prompt with no schedule. It runs only when a script
wakes it, and it is always silent.

    ---
    on_demand: true
    default: true
    session: new_per_run
    ---
    What the agent does when a script wakes the task.

**Restricted task**: a prompt or on-demand task with `allow`, a list of
command prefixes. It needs `session: new_per_run`.

    allow:
      - "uv run apps/mail/scripts/mk.py bg"

A run of it may only run commands that start with one of the prefixes and
contain none of `;`, `&`, `|`, backtick, `$`, `<`, `>` or a line break; it
may read files inside the hub except `secrets/` and `.env*`. Everything else
(writing, editing, the web, subagents, MCP tools) is denied. On Claude Code
the guard enforces this: a PreToolUse hook running `cc-hub cron guard`,
which `cc-hub cron guard-setup` adds to `.claude/settings.json` (`hub-adapt`
runs it). Other runtimes have no guard.

## When a task fires

The registered prompt names the definition file:
`Scheduled task hub:<name>: follow the body of <file> in the hub.` Read the
file, skip the frontmatter and do what the body says. If the file does not
exist, do not guess what the task was for: reply that `hub:<name>` has no
definition any more, and that `cc-connect cron list` (find its id) and
`cc-connect cron del <id>` remove it.

## Register

Only in a direct chat with the user: a task reports to the chat it was
registered from. If `cc-connect` is not available, log that this is still
to do. You are sent here for some rows: those whose `source` is `hub`
(`hub-adapt`), or an app's (`hub-apps`).

Before you register a row, ask first where needed:

- **Script task** (`kind: exec`): tell the user the command (`exec`) and
  what the file's body says it does; register it only if they agree. Skip
  this only when the task is already registered with this same command and
  only its time changes. If they decline, do not register it, log that
  (`cc-hub memory log`) and tell them what will not work without it.
- **Restricted task** (non-empty `allow`): on Claude Code, run
  `cc-hub cron guard-setup` first (it changes nothing when the guard is in
  place). On a runtime without the guard, tell the user the task would run
  there without this safety belt, so it could run any command; register it
  only if they agree.

To register a row, run its `commands` in order. A later command contains
`<id>`: use the id that this `cc-connect cron add` printed, the new job's.
If a later command fails, delete the job you just added and tell the user. To delete:
`cc-connect cron del <id>`, with the id from `cc-connect cron list`.

1. Run `cc-hub cron list --json` and `cc-connect cron list`. A row is
   registered when a job's description is the row's `desc` (`hub:<name>`).
2. For each of your rows:
   - With an `error`: tell the user what is wrong (`cc-hub doctor` says how
     to fix it). It is `enabled: false`, so it is treated as below.
   - `enabled: false`: if `hub:<name>` is registered, delete it.
   - `enabled: true`, not registered: register it.
   - `enabled: true`, registered: read the job with `cc-connect cron info <id>`
     and compare it with what the row's `commands` set: the `--cron` time,
     `--prompt`, `--exec`, `--timeout-mins`, `--session-mode`, whether
     `--silent` is given, and the `mute true` or `enabled false` that a
     `cron edit` line sets (without such a line the job is unmuted and
     enabled). If anything differs, delete it and register it again.
3. A registered `hub:` job in your scope that has no row (its file is gone)
   is deleted: `hub:<name>` without a `/` for the hub, `hub:<app>/...` for an
   app. A `hub:<name>` registered more than once: delete every copy, then
   register it once if its row is `enabled: true`.

## Change a time

When the user wants a task to run at another time, or turned off or on:

    cc-hub cron set <name> "<expr>"     # quote the expression
    cc-hub cron set <name> --off
    cc-hub cron set <name> --on
    cc-hub cron reset <name>            # back to the time in the file

The override is kept in `hub.toml` and committed; `cc-hub update`, app
updates and the steps above keep it. An on-demand task has no time: only
`--off` and `--on`. Do not change a time in cc-connect alone; the next
registration puts it back.

Then run the steps the command prints, in a direct chat: find the task's
`<old id>` with `cc-connect cron list` and delete it, then, if the task is
on, run its registration commands. That is a registration like any other.
Before you run any of it, apply "Before you register" above: the user's
consent for a script task's command (unless only the time of a registered
task changes), and the guard or the no-safety-belt warning for a restricted
task. For `<id>` in the commands after `cron add`, use the id that this
`cc-connect cron add` printed; if one of them fails, delete the new job and
tell the user.

## Wake

A script wakes an on-demand task with `cc-hub cron wake <name>`. Exit 0 only
means cc-connect took it, not that the agent has finished: the script
confirms through its own state (for example a mark the agent sets when it is
done) and wakes the task again later if it is not confirmed. Exit 1 says why
on stderr: not an on-demand task, no such task, not registered, turned off,
or cc-connect not found or not running.

`cc-hub update` overwrites `README.md` and `memory-consolidate.md`; files you
add here are yours.
