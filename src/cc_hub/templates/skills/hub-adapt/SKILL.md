---
name: hub-adapt
description: Make your own agent ecosystem discover this hub's instructions and skills, register the hub's default scheduled tasks, and install the restricted-task guard. Run on first use, after switching agents, on a new machine, after adding or removing a skill, or when `cc-hub doctor` reports missing pointers or a missing guard.
---

# hub-adapt

The hub holds the only copy of its instructions (`AGENTS.md`) and of its
skills (`skills/<name>/`). Your ecosystem reaches them through pointers you
create here. Every step is idempotent: re-running must not duplicate anything.

## Goals

1. **Instructions.** If your ecosystem has an instruction file of its own,
   create it with the single line that imports `AGENTS.md` (see the table)
   and nothing else of yours. If your runtime only reads `AGENTS.md`, do
   nothing.
2. **Skills.** Run `cc-hub link <your skills directory>` with the directory
   relative to the hub (see the table). It gives every skill in `skills/` and
   in installed apps one directory link there and removes links to skills
   that are gone. New skills go in `skills/<name>/`; run the command again
   after adding or removing one. If your skills directory did not exist when
   this session started, your runtime may need a reload or a new session to
   see the skills; tell the user.
3. **Trust.** If your runtime needs a one-time interactive trust step before
   it reads this directory's instructions or skills, tell the user exactly
   what to run and why.
4. **Scheduled tasks.** Only in a direct chat with the user: a task reports
   back to the chat it was registered from. Follow `cron/README.md` for every
   row of `cc-hub cron list --json` whose `source` is `hub`: it registers
   what is missing, replaces what differs, removes what is off or gone, and
   asks the user before a script task. On Claude Code, install the guard
   (goal 5) before you register a restricted task. If `cc-connect` is not
   available, log that this is still to do. Installed apps register their
   own tasks during setup (`hub-apps`).
5. **Guard.** On Claude Code, run `cc-hub cron guard-setup`. It adds the
   restricted-task guard, a PreToolUse hook running `cc-hub cron guard`, to
   `.claude/settings.json` and keeps everything else in that file; running it
   again changes nothing. It applies to sessions started afterwards. Other
   runtimes have no guard; `cron/README.md` says what that means for
   restricted tasks.

Permissions and sandbox settings belong to the user and your runtime;
do not change them here, except the guard hook that
`cc-hub cron guard-setup` adds.

Finish with `cc-hub doctor`, fix what it reports, then
`cc-hub memory log "hub-adapt: <what you created>"`.

## Known ecosystems (may be outdated; your own documentation wins)

| Runtime | Instruction file | Skills directory | Trust step |
|---|---|---|---|
| Claude Code | `CLAUDE.md` containing only `@AGENTS.md` | `.claude/skills` (reload: `/reload-skills`) | none needed for instructions and skills |
| Codex CLI | none, reads `AGENTS.md` | `.agents/skills` | mark the directory trusted if Codex asks |

Claude Code reads `AGENTS.md` only while no `CLAUDE.md` exists, and
cc-connect's `/memory add` creates `CLAUDE.md`. Creating it with the import
line keeps `AGENTS.md` loaded; anything added later goes below that line.

All of these pointer files, and `.claude/settings.json`, are gitignored by
the hub.
