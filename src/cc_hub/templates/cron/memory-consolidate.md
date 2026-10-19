---
schedule: "0 3 * * *"
default: true
session: new_per_run
---
Run the memory consolidation procedure described in the hub-memory skill.
Then write one paragraph: what changed in MEMORY.md and whether the hub was
pushed. If the push failed, reply with that paragraph. Otherwise run
`cc-hub report note daily --from memory-consolidate -- '<the paragraph>'`
(a single quote inside the paragraph must be escaped for the shell in use):
if it prints `kept for ...` (exit 0), reply with exactly NO_REPLY; in any
other case (it says no report is on, or it fails), reply with the paragraph.
