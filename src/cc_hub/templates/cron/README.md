# Scheduled tasks

Each `*.md` file here is one task: YAML frontmatter plus the prompt body.

    ---
    schedule: "0 3 * * *"     # cron expression
    default: true             # register during bootstrap
    session: new_per_run      # reuse | new_per_run (cc-connect session_mode)
    ---
    Prompt text the agent receives when the task fires.

Scheduling itself belongs to cc-connect:

    cc-connect cron add --cron "<schedule>" --prompt "<body>"

`cc-hub update` overwrites `README.md` and `memory-consolidate.md`; files you
add here are yours.
