# Install and upgrade

## Requirements

- [uv](https://docs.astral.sh/uv/) (single binary; installs Python 3.11+ itself if needed)
- OpenSSH client if you use `cc-hub hosts`
- git (optional; `cc-hub init` initializes a repository in the hub)

## Install

From PyPI (0.2.1 and later):

    uv tool install cc-hub
    cc-hub version

Or a released tag straight from GitHub:

    uv tool install git+https://github.com/Jenwein/cc-hub.git@v0.2.1

Or download the wheel attached to the GitHub release and install that file:

    uv tool install ./cc_hub-0.2.1-py3-none-any.whl

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
Treat the hub as private data: commit it to a private repository if you want
backups. `secrets/`, generated files and agent pointers are already gitignored.

## Connect cc-connect

See [cc-connect.md](cc-connect.md). Then send the agent its first message.

## Check

    cc-hub doctor

Warnings about `bootstrap-pending` and `env-stale` disappear after the first
conversation. When cc-connect runs as a service, make sure it can find
`cc-hub` and `uv`; see the PATH notes in [cc-connect.md](cc-connect.md).

## Upgrade

    uv tool upgrade cc-hub    # installed from PyPI
    uv tool install --force git+https://github.com/Jenwein/cc-hub.git@<new tag>   # from GitHub
    cc-hub update --dry-run   # see what would change
    cc-hub update

`update` replaces only framework-owned files (`AGENTS.md`, `BOOTSTRAP.md`,
`skills/hub-*`, `cron/README.md`, `cron/memory-consolidate.md`, `.gitignore`)
and merges new keys into `hub.toml`. Previous versions are copied to
`.cc-hub/backups/<old version>/`. Read the migration notes in `CHANGELOG.md`
before upgrading across minor versions.
