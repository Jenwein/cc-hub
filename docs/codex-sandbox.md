# Codex sandbox notes

cc-connect starts Codex with `codex exec --cd <hub> --sandbox workspace-write`
by default. Inside that sandbox only the working directory (the hub) and
`writable_roots` are writable, and the restriction is inherited by every
child process the agent starts.

## Make registered projects writable

Add their paths to `writable_roots` in `.codex/config.toml` inside the hub
(the hub is the Codex project directory, so this file applies once the hub
is trusted):

    [sandbox_workspace_write]
    writable_roots = ["/home/you/dev/project-a", "/home/you/dev/project-b"]

cc-hub does not change Codex's sandbox settings: add the paths yourself, and
again after each `cc-hub projects add`. If Codex rejects the key at project
level, put the same table in `~/.codex/config.toml` instead.

Alternative: pass `--add-dir <path>` through cc-connect's agent options for
each project.

## One-time trust

Run `codex` interactively once in the hub and mark the directory trusted.
Without trust Codex ignores `.codex/config.toml`, so `writable_roots` would
not apply.

## Full access

`--dangerously-bypass-approvals-and-sandbox` (cc-connect `mode = "yolo"`)
removes the sandbox entirely; `writable_roots` no longer matters.
