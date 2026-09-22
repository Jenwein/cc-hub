---
name: hub-jobs
description: Run long tasks, tests, builds or delegated coding as detached background jobs and report on them. Use for anything longer than a few minutes or that must survive the chat session.
---

# hub-jobs

Background jobs outlive your session. cc-connect resets idle sessions and
some runtimes have no background mode of their own, so use jobs for
anything long.

## When

- Test suites, builds, data processing, downloads.
- Coding work delegated to another agent instance.
- Anything the user may ask about later ("is it done?").

Short commands (seconds) run inline as usual.

## Commands

    cc-hub jobs start --cwd <dir> --name <short-name> -- <command ...>
    cc-hub jobs status [<id>]
    cc-hub jobs log <id> --tail 50
    cc-hub jobs stop <id> [--force]
    cc-hub jobs clean --older-than 7d

`start` returns immediately with the id and log path. Tell the user the id.

## Delegating a coding task

1. `git -C <repo> worktree add <repo>-wt-<topic> -b <topic>`
2. `cc-hub jobs start --cwd <repo>-wt-<topic> --name <topic> -- codex exec "<task>"`
   (or `claude -p "<task>"`; use whichever runtime `ENV.md` says is installed).
3. Report the id. When asked, check `status` and `log`.
4. When done: review the diff in the worktree, merge or open a PR as the user
   prefers, then `git worktree remove`.

Never run delegated work inside the hub directory or the user's live checkout.

## Reporting

On completion, summarize outcome and exit code to the user and
`cc-hub memory log "job <id> <name>: <outcome>"`.

## Sandboxed runtimes

Under Codex the job inherits the sandbox: writes outside `writable_roots`
fail. Register project paths (hub-adapt goal 4) before starting jobs there.
