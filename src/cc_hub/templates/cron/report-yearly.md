---
schedule: "20 9 1 1 *"
default: false
session: new_per_run
---
Yearly report. Run `cc-hub report plan yearly --json`.

- If `empty` is true, reply with exactly NO_REPLY and stop.
- For each section whose `kind` is `instruction`: read its `file`, skip the
  frontmatter, and write the section as the body says, in the user's
  language, for the time from `since` to `until`. Store it with
  `cc-hub report put yearly <app> --text "<the section>"`. If there is
  nothing to say, store nothing.
- Do not run any section's command and do not read `reports/`: command
  sections reach the user without passing through you.
- Run `cc-hub report send yearly`. If it fails, reply with its error.
  Otherwise reply with exactly NO_REPLY.
