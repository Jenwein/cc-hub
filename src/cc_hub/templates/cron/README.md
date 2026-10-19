# Scheduled tasks

Each `*.md` file here, except this one, is one task: YAML frontmatter, then
the body the agent follows when the task fires. Its name is the file name
without `.md`. Installed apps keep their tasks in `apps/<app>/cron/<task>.md`,
named `<app>/<task>`. Scheduling belongs to cc-connect: every task is
registered there with the description `hub:<name>` (`hub:<app>/<task>` for an
app's task).

    ---
    schedule: "0 3 * * *"     # five-field cron expression
    default: true             # registered on every machine; false: only when turned on
    session: new_per_run      # reuse | new_per_run (cc-connect --session-mode)
    ---
    What the agent does when the task fires.

## When a task fires

The registered prompt names the definition file:
`Scheduled task hub:<name>: follow the body of <file> in the hub.` Read the
file, skip the frontmatter and do what the body says. If you cannot, do not
guess what the task is for. If the file is missing, reply that `hub:<name>`
has no definition any more, and that `cc-connect cron list` (find its id)
and `cc-connect cron del <id>` remove it. If the file is broken, reply with
the reason, and that the user can fix it (`cc-hub doctor` says how) or
remove the job the same way.

## Register

Only in a direct chat with the user: a task reports to the chat it was
registered from. If `cc-connect` is not available, log that this is still
to do. You are sent here for some rows: those whose `source` is `hub`
(`hub-adapt`), or an app's (`hub-apps`).

To register a row, run its `command`. To delete a job:
`cc-connect cron del <id>`, with the id from `cc-connect cron list`.

1. Run `cc-hub cron list --json` and `cc-connect cron list`. A row is
   registered when a job's description is the row's `desc` (`hub:<name>`).
2. For each of your rows:
   - With an `error`: leave its registered job, if any, as it is, and tell
     the user what is wrong; `cc-hub doctor` says how to fix it. Such a row
     says `enabled: false` only because it cannot be registered now.
   - Without an `error`, `enabled: false`: if `hub:<name>` is registered,
     delete it.
   - `enabled: true`, not registered: register it.
   - `enabled: true`, registered: read the job with `cc-connect cron info <id>`
     and compare it with what the row's `command` sets: the `--cron` time,
     the `--prompt` and the `--session-mode`; `cc-connect cron info <id> silent`
     must print `true`. If anything differs, delete it and register it again.
3. A registered `hub:` job in your scope that has no row (its file is gone)
   is deleted: `hub:<name>` without a `/` for the hub, `hub:<app>/...` for an
   app. A `hub:<name>` registered more than once whose row has no `error`:
   delete every copy, then register it once if its row is `enabled: true`.

## Change a time

When the user wants a task to run at another time, or turned off or on:

    cc-hub cron set <name> "<expr>"     # quote the expression
    cc-hub cron set <name> --off
    cc-hub cron set <name> --on
    cc-hub cron reset <name>            # back to the time in the file

For example, `cc-hub cron set memory-consolidate "30 2 * * *"` runs the
nightly consolidation at 02:30. The override is kept in `hub.toml` and
committed; `cc-hub update`, app updates and the steps above keep it. Do not
change a time in cc-connect alone; the next registration puts it back.

Then run the steps the command prints, in a direct chat: find the task's
`<old id>` with `cc-connect cron list` and delete it, then, if the task is
on, run its registration command.

`cc-hub update` overwrites `README.md`, `memory-consolidate.md` and the
`report-<period>.md` files; files you add here are yours.

## Reports

`cc-hub report` sends the user a report each day, week, month, quarter or
year. The tasks `report-daily`, `report-weekly`, `report-monthly`,
`report-quarterly` and `report-yearly` are off until the user wants one:

    cc-hub cron set report-<period> --on
    cc-hub cron set report-<period> "<expr>"     # another time, if wanted

Then run the steps it prints, in a direct chat. Before the first one goes on,
run `cc-hub report list --json`: if `language` is null, ask the user which
language the reports are in and run `cc-hub report language <tag>` (such as
`en` or `zh-CN`). An app's section of a period's report is switched with
`cc-hub report section <app> <period> --off` (or `--on`). Approve a command
section switched on with `cc-hub report approve <app>` if the user agrees.

Every task is registered `--silent`: the chat shows only what the agent
replies, and `NO_REPLY` shows nothing. A task that finishes work quietly
leaves its result for a report instead of replying:

    cc-hub report note <period> --from <task> -- '<text>'

Single-quote the text; a single quote inside it must be escaped for the shell
in use. When that prints `kept for ...`, the task replies `NO_REPLY`; if the
note is not kept (exit 3, or an error), it replies with the same words. An
urgent problem is never left as a note; reply with it directly.
