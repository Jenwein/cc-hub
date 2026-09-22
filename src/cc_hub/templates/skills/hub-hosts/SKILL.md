---
name: hub-hosts
description: Run commands and copy files on remote machines registered in hosts.toml. Use whenever the user refers to another machine, server or NAS.
---

# hub-hosts

`hosts.toml` lists machines reachable over ssh with keys. `cc-hub hosts`
wraps ssh and scp so you never hand-quote remote commands: the command is
base64-encoded and decoded on the other side according to the host's shell.

## Commands

    cc-hub hosts list
    cc-hub hosts check <name>                  # does key-based login work?
    cc-hub hosts run <name> -- <command ...>   # run there, print output
    cc-hub hosts run <name> --timeout 600 -- <command ...>
    cc-hub hosts push <name> <local> <remote>
    cc-hub hosts pull <name> <remote> <local>

Write the remote command exactly as you would type it on that host; do not
add quoting for ssh. Exit code and output are passed through.

## Registering a host

Add a block to `hosts.toml`:

    [[host]]
    name = "nas"
    target = "user@nas.local"     # or a Host alias from ~/.ssh/config
    port = 22
    shell = "bash"                # bash | pwsh | powershell
    key = "secrets/nas_ed25519"   # optional, relative to the hub

Then `cc-hub hosts check nas`. Passwords are not supported; keys only.

## Rules

- Destructive operations on a remote host (deleting, reinstalling, rebooting)
  require an explicit request from the user in this conversation.
- The blocklist hook only sees local commands. Apply the same caution remotely.
- Log outcomes with `cc-hub memory log`.
