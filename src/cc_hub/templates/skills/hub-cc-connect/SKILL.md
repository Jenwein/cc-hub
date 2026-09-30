---
name: hub-cc-connect
description: Exchange files with the chat and schedule prompts through cc-connect. Use when sending a file, image or audio back to the user, when the user sent attachments, or when setting up a recurring task.
---

# hub-cc-connect

cc-connect is the bridge between the chat platform and you. It runs on this
machine and exposes a CLI you can call.

## Receiving files

Attachments are saved under `.cc-connect/attachments/<message-id>/` and the
message ends with "(Files saved locally, please read them: ...)" listing
absolute paths. Read them from there; do not ask the user to resend.

## Sending files

    cc-connect send --file /absolute/path/report.md
    cc-connect send --image /absolute/path/chart.png
    cc-connect send --tts "short spoken text"

Always use absolute paths. Files over 50 MB are rejected: split or compress
first. For long text output, write it to a file and send the file rather
than pasting it into the chat.

## Scheduling

Task definitions live in `cron/*.md` (format in `cron/README.md`). Register a
task from the chat that should receive its results: cc-connect binds it to
the current session.

    cc-connect cron list
    cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"

`<name>` is the file name without `.md`. Skip a task whose `hub:<name>` is
already in `cron list`. For a one-off schedule the user asks for, give it a
short `--desc` of its own; `--session-mode` defaults to `reuse`.

    cc-connect cron edit <id> <field> <value>   # e.g. session_mode new_per_run
    cc-connect cron del <id>                    # only when the user asks

From the chat the user has `/cron list` and `/cron del <id>`.

## Things to know

- `/dir <path>` typed by the user switches the working directory for the
  *next* session only. You cannot change the current session's directory.
- Approval prompts you raise appear in the chat as buttons; the user may be
  slow to answer. Do not spam retries.
- If `cc-connect` is not on PATH, use the absolute path from `ENV.md`.
