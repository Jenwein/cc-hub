---
name: hub-adapt
description: Make your own agent ecosystem discover this hub's instructions and skills. Run on first use, after switching agents, or when `cc-hub doctor` reports missing pointers.
---

# hub-adapt

You know which agent runtime you are and where it looks for instruction
files and skills. This skill lists the goals; you choose the files. Every
step is idempotent: re-running must not duplicate anything.

## Goals

1. **Instructions.** Your ecosystem's instruction file must lead to
   `AGENTS.md` in the hub root. If your runtime reads `AGENTS.md` natively,
   do nothing. Otherwise create the smallest pointer file your runtime
   supports (an import line, not a copy).
2. **Skills.** Your skills discovery path must reach the hub's `skills/`
   directory. Any mechanism works: a link, a copy, or a pointer your runtime
   supports. `cc-hub link skills <your skills path>` makes a link, picking
   symlink, junction or copy for this platform, and says which.
3. **Trust.** If your runtime needs a one-time interactive trust step before
   it reads this directory's instructions or skills, tell the user exactly
   what to run and why.

Permissions and sandbox settings belong to the user and your runtime;
do not change them here.

Finish with `cc-hub doctor`, fix what it reports, then
`cc-hub memory log "hub-adapt: <what you created>"`.

## Known ecosystems (may be outdated; your own documentation wins)

| Runtime | Instruction pointer | Skills path | Trust step |
|---|---|---|---|
| Claude Code | `CLAUDE.md` containing `@AGENTS.md` (2.1.277+ reads `AGENTS.md` natively when no CLAUDE.md exists) | `.claude/skills` | none needed for instructions and skills |
| Codex CLI | none needed, reads `AGENTS.md` | `.agents/skills` | mark the directory trusted if Codex asks |

All of these pointer files are gitignored by the hub.
