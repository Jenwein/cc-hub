---
name: hub-hosts
description: Find how to reach remote machines registered in hosts.toml. Use whenever the user refers to another machine, server or NAS.
---

# hub-hosts

`hosts.toml` lists machines reachable over ssh with keys. The hub only
records them; you connect with `ssh` and `scp` yourself.

    cc-hub hosts list           # name, target, shell, notes
    cc-hub hosts list --json    # every field, including port and key

## Connecting

Build the command from the host's fields:

    ssh -o BatchMode=yes [-p <port>] [-i <hub>/<key>] <target> '<command>'
    scp [-P <port>] [-i <hub>/<key>] <local> <target>:<remote>

- `target` is `user@host` or a Host alias from `~/.ssh/config`.
- `key` is relative to the hub root. Pass its path to ssh; never print the key.
- `shell` tells you what runs on the other side: write bash for `bash`,
  PowerShell for `pwsh` or `powershell`.
- `BatchMode=yes` makes a missing key fail fast instead of waiting for a
  password prompt.
- For commands full of quotes, or several lines, send a script on stdin
  instead of quoting it: `ssh <target> 'bash -s' < script.sh`, or
  `ssh <target> 'pwsh -NoProfile -Command -' < script.ps1`.

## Registering a host

There is no `hosts add` yet; edit `hosts.toml` by hand. Add a block:

    [[host]]
    name = "nas"
    target = "user@nas.local"     # or a Host alias from ~/.ssh/config
    port = 22
    shell = "bash"                # bash | pwsh | powershell
    key = "secrets/nas_ed25519"   # optional, relative to the hub

Then check that key login works: `ssh -o BatchMode=yes <target> true`.

## Rules

- Destructive operations on a remote host (deleting, reinstalling, rebooting)
  require an explicit request from the user in this conversation.
- Log outcomes with `cc-hub memory log`.
