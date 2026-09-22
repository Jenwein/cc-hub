---
name: hub-projects
description: Find and register the user's local project directories. Use when the user names a project or asks you to work somewhere outside the hub.
---

# hub-projects

`projects.toml` is the registry of directories you work in. Check it before
guessing a path.

## Commands

    cc-hub projects list
    cc-hub projects show <name>
    cc-hub projects add <path> [--name <name>] [--description "..."] [--notes "..."]
    cc-hub projects remove <name>

`add` expands `~`, verifies the directory exists and refuses duplicates.

## Working in a project

- Use absolute paths or `cd` into it; run its own tooling from there.
- Read the project's own instruction files (`AGENTS.md`, `CLAUDE.md`, README)
  before changing anything.
- Put notes about how to run or test it in `notes` (via `projects add --notes`
  or by editing `projects.toml`) so the next session does not rediscover them.
- Never copy project files into the hub.

## Sandboxed runtimes

After registering a project under Codex, repeat hub-adapt goal 4 so the path
becomes writable.
