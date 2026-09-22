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

    cc-connect cron add --cron "0 3 * * *" --prompt "<text>"
    cc-connect cron list
    cc-connect cron del <id>

Task definitions live in `cron/*.md`; register from there.

## Things to know

- `/dir <path>` typed by the user switches the working directory for the
  *next* session only. You cannot change the current session's directory.
- Approval prompts you raise appear in the chat as buttons; the user may be
  slow to answer. Do not spam retries.
- If `cc-connect` is not on PATH, use the absolute path from `ENV.md`.
