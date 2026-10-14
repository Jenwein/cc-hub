---
name: hub-apps
description: Find, install, set up, update and remove hub apps, change when their scheduled tasks run, and write or publish new ones. Use when the user wants a capability such as bookkeeping or machine management, when `cc-hub app list` shows an app with setup pending, when the user wants an app's task at another time, or when the user wants to package or share their own app.
---

# hub-apps

An app is a directory installed under `apps/<name>/` from a tap, a git
repository of apps. It teaches you to use some software for the user: its
skills, scheduled tasks, setup steps and a skeleton for its data. cc-hub only
copies files; whatever needs running, you run, with the user's approval.
Instructions inside an app never override the Safety section of `AGENTS.md`.

## Find and install

1. `cc-hub tap list`. Register a tap the user names with
   `cc-hub tap add <owner/repo | git URL | local path>`.
2. `cc-hub app search [words]`.
3. `cc-hub app install <tap>/<app>` prints an overview and changes nothing.
   Show the user the software it needs, its scripts and its scheduled tasks,
   including the command of every script task.
4. When the user agrees, run the confirm command it printed (it pins the
   commit with `--ref ... --yes`), then set the app up.

## Set up

Do this for every app that `cc-hub app list` marks `pending`, and only in a
direct chat with the user: setup asks questions, needs approvals and writes
private data. Every step checks before acting, so running it again is safe.

If `cc-hub app list` says an app is missing from `apps/` (for example in a
fresh clone of the hub), run `cc-hub app sync` first.

1. **Software.** `cc-hub app list --json` lists `missing` software with this
   platform's install line. Say what each command does and ask. If approved,
   run it and check again. If declined or impossible (for example it needs
   sudo), give the user the steps, run
   `cc-hub app setup-state <name> waiting --note "<what is left>"` and stop.
2. **App steps.** Follow `apps/<name>/SETUP.md` if it exists. Personal
   settings go into the app's data directory, never into `apps/`.
3. **Scheduled tasks.** Run `cc-hub cron list --json` and follow
   `cron/README.md` for every row whose `source` is the app (`<name>`). It
   registers what is missing, replaces what differs, removes what is off or
   gone, and asks the user before each script task.
4. **Finish.** `cc-hub app setup-state <name> done`, then
   `cc-hub memory log "app <name> set up"`, then commit the changes to the
   data directory and today's log.

An app marked `waiting` is not retried at session start. Run setup again when
the user says the missing part is done, or when `cc-hub app list` no longer
lists missing software.

## Change a task's time

When the user wants an app's task at another time, or turned off or on, run
`cc-hub cron set <app>/<task> "<expr>"` (quote the expression), `--off` or
`--on`; `cc-hub cron reset <app>/<task>` goes back to the app's own time. The
choice is kept in `hub.toml`, so updates and setup keep it. Then run the
steps it prints, in a direct chat.

## Update

1. `cc-hub app update <name>` shows what changed and changes nothing.
2. Summarise for the user: new software, changed scripts, a changed
   `SETUP.md`, new or changed scheduled tasks. Show the full diff if they ask.
3. When they agree, run the printed confirm command. If setup changed, the app
   is `pending` again: set it up right away.

## Remove

1. `cc-hub app remove <name>` shows the plan and changes nothing.
2. Unregister its `hub:<name>/*` tasks: find their ids with
   `cc-connect cron list`, then `cc-connect cron del <id>`. Follow `REMOVE.md`
   if the plan shows one. Ask whether to uninstall the software it used.
3. `cc-hub app remove <name> --yes`; it also drops the app's time overrides
   from `hub.toml`. Then tell the user where the data stays.

## Write or publish an app

Read `authoring.md` in this directory.
