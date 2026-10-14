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

## Scheduled task kinds

Same environment, with a test hub; cc-connect installed as a service with
`cc-connect daemon install`. Remove `probe` and `hello` afterwards.

1. Install the new cc-hub, run `cc-hub update` in the test hub and have the
   agent run `hub-adapt` from the direct chat. `cc-hub doctor` is all ok;
   `.claude/settings.json` has a PreToolUse hook running
   `"<absolute path of cc-hub>" cron guard`;
   `cc-connect cron info <id>` of `hub:memory-consolidate` shows the pointer
   prompt.
2. **Script task.** Add `cron/probe.md` with `exec: "cc-hub memory log probe"`,
   `schedule: "*/2 * * * *"` and `default: true`, and ask the agent to
   register it: it shows the command and asks first. A `probe` line appears
   in today's log every 2 minutes and nothing appears in the chat. If the log
   stays empty, fix the daemon's PATH and make "Script tasks and PATH" in
   `cc-connect.md` say what worked.
3. **On-demand task.** Add `cron/hello.md` with `on_demand: true`,
   `default: true`, `session: new_per_run` and the body "Reply with one line:
   hello from hub:hello.", have it registered, then run `cc-hub cron wake hello`
   in a shell: it exits 0 right away, and the chat gets the line with no "⏰"
   line before it. Change `probe`'s `exec` to `cc-hub cron wake hello` and
   have it registered again: the line arrives every 2 minutes, so
   `cc-connect` is on the daemon's PATH too. With cc-connect stopped,
   `cc-hub cron wake hello` exits 1 and says cc-connect is not running.
4. **Guard under YOLO.** Set the project's `mode = "bypassPermissions"` and
   restart cc-connect. Give `hello.md` `allow:` with `- "cc-hub memory log"`
   and a body asking the agent to run `cc-hub memory log ok`, then `ls ~`,
   then `cc-hub memory log x; ls`, then to write `x.txt`, Glob `/etc/*` and
   read `secrets/x`, and to report what happened. Wake it: the log line is
   written, everything else is denied with the guard's reasons, and no
   approval request reaches the chat. The first user message in the run's
   transcript starts with `Scheduled task hub:hello:`. In the direct chat,
   `ls ~` still runs.
5. **Time override.** `cc-hub cron set memory-consolidate "30 2 * * *"`, then
   run the printed steps: `cc-connect cron list` shows `30 2 * * *`. Run
   `cc-hub update` and `hub-adapt` again: the time stays.
6. Delete `cron/probe.md` and `cron/hello.md` and run `hub-adapt` again: it
   deletes `hub:probe` and `hub:hello` from cc-connect. Set `mode` back.
