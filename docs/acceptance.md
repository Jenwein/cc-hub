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
