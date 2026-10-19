# Manual acceptance checklist

Environment: WSL2, cc-connect running as a service, Claude Code as the agent,
one chat platform (Feishu or any other).

1. Install cc-hub from a regular terminal (see `install.md`), `cc-hub init`,
   `cc-hub doctor`: everything green except `bootstrap-pending` and `git`
   (no remote); `git log` in the hub shows `cc-hub: init`.
2. Configure cc-connect `work_dir` and `env.PATH`, restart cc-connect.
3. Send the first message. The agent runs bootstrap: asks for a name, writes
   `IDENTITY.md` and `USER.md`, runs `hub-adapt` (pointers, skill links,
   `hub:memory-consolidate` registered), deletes `BOOTSTRAP.md` and commits.
4. Add a private remote (`backup.md`); `cc-hub doctor`: all green.
5. Ask the agent to remember something. `memory/` has today's file,
   `cc-hub memory search` finds it, and the task ends with a commit.
6. Point a Codex bot at the same hub and send `/cron setup` in its chat.
   `AGENTS.md` ends with cc-connect's instructions block.
7. Bump the package version and run `cc-hub update`: `AGENTS.md` changes above
   its closing marker and keeps everything below it (the cc-connect block
   included); `SOUL.md`, `USER.md` and `memory/` do not change;
   `.cc-hub/backups/` holds the previous version; there is a
   `cc-hub: update <old> -> <new>` commit.
8. Prepare a test tap whose app has `requires`, `cron/`, `seed/` and
   `SETUP.md`. Ask the agent in the chat to install it: it shows the overview
   first and installs after you agree, asks before installing the software,
   registers `hub:<app>/<task>`, and `cc-hub app list` shows `done`.
9. Change `SETUP.md` in the tap and commit. Ask the agent to update the app:
   it shows the changes first, updates after you agree, and runs setup again.
10. Ask the agent to remove the app: it shows the plan first, unregisters the
    scheduled task, and the data directory stays.
11. Trigger the consolidation task by hand: the remote gets a new commit.
12. Clone the hub to another machine, run `cc-hub app sync`, configure
    cc-connect and send a message: `hub-adapt` registers the default
    scheduled tasks and the app is set up again.
13. Ask the agent to draft an issue about a cc-hub problem: it shows the full
    title and body, without private data, and files it only after you agree.

## Scheduled task times

Same environment, with a test hub and the app from check 8 installed and set
up. Remove `probe` afterwards.

1. Install the new cc-hub, run `cc-hub update` in the test hub and have the
   agent run `hub-adapt` from the direct chat. `cc-hub doctor` is all ok;
   `cc-connect cron info <id>` of `hub:memory-consolidate` shows the pointer
   prompt `Scheduled task hub:memory-consolidate: follow the body of
   cron/memory-consolidate.md in the hub.`
2. Add `cron/probe.md` with `schedule: "*/2 * * * *"`, `default: true`,
   `session: new_per_run` and the body "Reply with one line: hello from
   hub:probe.", then run `hub-adapt` again: it registers `hub:probe` and the
   line arrives every 2 minutes. Change the body: the next run replies with
   the new text without registering again.
3. `cc-hub cron set memory-consolidate "30 2 * * *"`, then run the printed
   steps: `cc-connect cron list` shows `30 2 * * *` for
   `hub:memory-consolidate`, and the hub has a
   `cc-hub: cron set memory-consolidate` commit. Run `cc-hub update` and
   `hub-adapt` again: the time stays.
4. Ask the agent in the direct chat to run the app's task at another time,
   then to turn it off: it runs `cc-hub cron set <app>/<task>` and the
   printed steps; `cc-connect cron list` shows the new time, then no
   `hub:<app>/<task>`. Have the agent set the app up again: the task stays
   off. `cc-hub cron reset <app>/<task>` and its printed steps register it
   again at the app's own time.
5. Append `[cron."gone/task"]` with `enabled = false` to `hub.toml`:
   `cc-hub doctor` warns in `cron` and suggests `cc-hub cron reset gone/task`,
   which removes the table.
6. Delete `cron/probe.md` and run `hub-adapt` again: it deletes `hub:probe`
   from cc-connect. Set a time for the app's task, then have the agent remove
   the app: the `cc-hub: app remove <app>` commit also drops its table from
   `hub.toml`.

## Reports

Same environment, with a native cc-connect, and a test tap whose app has
`reports/daily.md` with a `command` (for example one that prints the date).
Turn the report off again afterwards.

1. Ask the agent in the private chat to turn on the daily report: it runs
   `cc-hub cron set report-daily --on` and the printed steps, and
   `cc-connect cron info <id> silent` of `hub:report-daily` is `true`.
2. Ask the agent to install the test app: setup shows the section's command,
   and runs `cc-hub report approve <app>` after you agree; `cc-hub report
   list` shows the section `approved`.
3. Run the task with `cc-connect cron exec <id>`: the report arrives in the
   private chat with the app's section, no "⏰" line comes before it, and the
   agent's own reply is not sent (it is `NO_REPLY`). The hub has
   `reports/<year>/<date>-daily.md` in a `cc-hub: report daily` commit.
4. Let `hub:memory-consolidate` run: nothing arrives in the chat, and its
   paragraph shows up under the notes of the next daily report.
