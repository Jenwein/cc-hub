# Install and upgrade

## Requirements

- [uv](https://docs.astral.sh/uv/) (single binary; installs Python 3.11+ itself if needed)
- git (history and backups of the hub, and taps for apps; `cc-hub init` creates the repository and the first commit)

## Install

From PyPI:

    uv tool install cc-hub
    cc-hub version

Or a released tag straight from GitHub:

    uv tool install git+https://github.com/Jenwein/cc-hub.git@v0.4.0

Or download the wheel attached to the GitHub release and install that file:

    uv tool install ./cc_hub-0.4.0-py3-none-any.whl

`uv tool install` puts `cc-hub` in `~/.local/bin` (Windows: `%USERPROFILE%\.local\bin`).
Make sure that directory is on your PATH; `uv tool update-shell` can add it.

**Install from a regular terminal** (Windows Terminal, PowerShell, a Linux or
macOS shell). On Windows, a shell running inside the Claude desktop app is part
of a packaged (MSIX) app: new folders it creates under `%APPDATA%` go to the
app's private storage, so a cc-hub installed there is invisible to cc-connect
and to the agents it starts. The symptom is `uv trampoline failed to
canonicalize script path`; reinstall from a regular terminal.

## Create the hub

    cc-hub init              # ~/.cc-hub
    cc-hub init ~/my-hub     # anywhere else

The hub must not live inside another git repository, and it must not be the
root of one either; `init` refuses both. If the hub is not `~/.cc-hub`, set
`CC_HUB_DIR` to its absolute path in cc-connect's
`[projects.agent.options.env]` so every `cc-hub` call finds it from any
working directory.
Treat the hub as private data. It is a git repository with its own history;
to back it up to a private remote, see [backup.md](backup.md). Credentials,
generated files and agent pointers are gitignored.

## Connect cc-connect

See [cc-connect.md](cc-connect.md). Then send the agent its first message.

## Check

    cc-hub doctor

The `bootstrap-pending` warning disappears after the first conversation. When
cc-connect runs as a service, make sure it can find `cc-hub`; see the PATH
notes in [cc-connect.md](cc-connect.md).

## Upgrade

    uv tool upgrade cc-hub    # installed from PyPI
    uv tool install --force git+https://github.com/Jenwein/cc-hub.git@<new tag>   # from GitHub
    cc-hub update --dry-run   # see what would change
    cc-hub update

`update` replaces only framework-owned files (`AGENTS.md` above its closing
marker, `BOOTSTRAP.md`, `skills/hub-*`, `cron/README.md`,
`cron/memory-consolidate.md`, `.gitignore`, `.gitattributes`), removes
framework files the package no longer ships, and merges new keys into
`hub.toml`. Previous versions are copied to `.cc-hub/backups/<old version>/`.
Read `CHANGELOG.md` before upgrading across minor versions.
