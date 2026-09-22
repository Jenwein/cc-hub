---
name: hub-adapt
description: Make your own agent ecosystem discover this hub's instructions, skills and hooks. Run on first use, after switching agents, or when `cc-hub doctor` reports missing pointers.
---

# hub-adapt

You know which agent runtime you are and where it looks for instruction
files, skills, hooks and permission settings. This skill lists the goals;
you choose the files. Every step is idempotent: re-running must not
duplicate anything.

## Goals

1. **Instructions.** Your ecosystem's instruction file must lead to
   `AGENTS.md` in the hub root. If your runtime reads `AGENTS.md` natively,
   do nothing. Otherwise create the smallest pointer file your runtime
   supports (an import line, not a copy).
2. **Skills.** Your skills discovery path must reach the hub's `skills/`
   directory. Create it with `cc-hub link skills <your skills path>`; the
   command picks symlink, junction or copy for this platform and says which.
3. **Hooks.** Run `cc-hub hook snippet` and merge its JSON into your hook
   configuration (pre-tool-use blocks catastrophic commands, post-tool-use
   writes the audit log). Keep existing hooks; add, do not replace.
4. **Permissions.** Deny reads of `secrets/` and `.env` in your permission
   system. Make sure your sandbox or permission rules allow writing to every
   path in `projects.toml`; repeat this after `cc-hub projects add`.
5. **Trust.** If your runtime needs a one-time interactive trust step
   (trusting this directory, trusting hooks), tell the user exactly what to
   run and why.

Finish with `cc-hub doctor`, fix what it reports, then
`cc-hub memory log "hub-adapt: <what you created>"`.

## Known ecosystems (may be outdated; your own documentation wins)

| Runtime | Instruction pointer | Skills path | Hooks file | Deny reads | Trust step |
|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md` containing `@AGENTS.md` (2.1.277+ reads `AGENTS.md` natively when no CLAUDE.md exists) | `.claude/skills` | `hooks` key in `.claude/settings.json` | `permissions.deny`: `Read(./secrets/**)`, `Read(./.env)` | run `claude` once interactively here and accept the trust prompt |
| Codex CLI | none needed, reads `AGENTS.md` | `.agents/skills` | `.codex/hooks.json` | no read rule; add project paths to `[sandbox_workspace_write] writable_roots` in `.codex/config.toml` | run `codex` once here, trust hooks via `/hooks`, mark the directory trusted |

All of these pointer files are gitignored by the hub.
