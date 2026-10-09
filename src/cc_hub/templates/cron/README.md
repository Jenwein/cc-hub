# Scheduled tasks

Each `*.md` file here is one task: YAML frontmatter plus the prompt body.

    ---
    schedule: "0 3 * * *"     # cron expression
    default: true             # registered on each machine by hub-adapt
    session: new_per_run      # reuse | new_per_run (cc-connect --session-mode)
    ---
    Prompt text the agent receives when the task fires.

Scheduling itself belongs to cc-connect. Register a task from the chat that
should receive its results, and name it after its file (`<name>` is the file
name without `.md`) so `cc-connect cron list` shows which ones are registered:

    cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"

`cc-hub update` overwrites `README.md` and `memory-consolidate.md`; files you
add here are yours.
