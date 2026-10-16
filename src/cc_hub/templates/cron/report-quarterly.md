---
schedule: "10 9 1 1,4,7,10 *"
default: false
session: new_per_run
---
Quarterly report. Run `cc-hub report plan quarterly --json`.

- If `empty` is true, reply with exactly NO_REPLY and stop.
- For each section whose `kind` is `instruction`: read its `file`, skip the
  frontmatter, and write the section as the body says, in the user's
  language, for the time from `since` to `until`. Store it with
  `cc-hub report put quarterly <app>`, passing the section on standard input
  (for example a here-document with a quoted delimiter), never inside double
  quotes. If there is nothing to say, store nothing.
- Do not run any section's command and do not read the hub's `reports/`
  archive: command sections reach the user without passing through you.
- Run `cc-hub report send quarterly`. If it fails, reply with its error.
  Otherwise reply with exactly NO_REPLY.
