---
name: hub-memory
description: Record, recall and consolidate memory in the hub. Use when something worth remembering happens, when you need to recall past work, or when running the nightly consolidation.
---

# hub-memory

Two layers. `memory/YYYY-MM-DD.md` is the raw daily log, append-only.
`MEMORY.md` is the curated summary read at every session start.

## Recording

`cc-hub memory log "<text>"` appends a timestamped line to today's log.
Log when you:

- finish a task with a concrete result (what, where, outcome);
- make or receive a decision;
- learn something about this machine or a project (paths, commands, quirks);
- are about to lose context (compaction, end of a long task).

Write facts, not feelings. One entry per event. Include paths and commands.

## Recalling

- `cc-hub memory recent` shows today's and yesterday's logs.
- `cc-hub memory search "<words>" --days 30` searches the logs and
  `MEMORY.md`, newest first. Add `--regex` for patterns.
- `cc-hub memory stats` shows sizes against budgets.

## Consolidation (run by the `memory-consolidate` cron task)

1. Run `cc-hub memory recent --days 7` and read everything.
2. For each entry still true and useful beyond the day it was written, add or
   merge a line in the matching `MEMORY.md` section: Decisions, Facts,
   Environment & tools, Pitfalls. Format: `- YYYY-MM-DD: text`.
3. Keep `MEMORY.md` under 200 lines. Merge duplicates, delete entries that
   later entries contradict, drop environment facts that `cc-hub env` has
   since changed.
4. In `USER.md`, mark directives contradicted by newer observations with
   `<!-- superseded: YYYY-MM-DD -->` instead of deleting them.
5. `cc-hub memory log "consolidation: <n> entries promoted, <m> removed"`.

Never put secrets, tokens or passwords in any memory file.
