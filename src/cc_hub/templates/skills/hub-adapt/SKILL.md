---
name: hub-adapt
description: Make your own agent ecosystem discover this hub's instructions and skills, and register the hub's default scheduled tasks. Run on first use, after switching agents, on a new machine, after adding or removing a skill, or when `cc-hub doctor` reports missing pointers.
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
   relative to the hub (see the table). It gives every skill in `skills/` one
   directory link there and removes links to skills that are gone. New skills
   go in `skills/<name>/`; run the command again after adding or removing
   one. If your skills directory did not exist when this session started,
   your runtime may need a reload or a new session to see the skills; tell
   the user.
3. **Trust.** If your runtime needs a one-time interactive trust step before
   it reads this directory's instructions or skills, tell the user exactly
   what to run and why.
4. **Scheduled tasks.** Only in a direct chat with the user: a task reports
   back to the chat it was registered from. Run `cc-connect cron list`. For
   every file in `cron/` with `default: true` whose `hub:<name>` (`<name>` is
   the file name without `.md`) is not listed yet, run:

       cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"

   If `cc-connect` is not available, log that this is still to do.

Permissions and sandbox settings belong to the user and your runtime;
do not change them here.

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

All of these pointer files are gitignored by the hub.
