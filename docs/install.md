# Install and upgrade

## Requirements

- [uv](https://docs.astral.sh/uv/) (single binary; installs Python 3.11+ itself if needed)
- OpenSSH client if you use `cc-hub hosts`
- git (optional; `cc-hub init` initializes a repository in the hub)

## Install

    uv tool install cc-hub
    cc-hub version

`uv tool install` puts `cc-hub` in `~/.local/bin` (Windows: `%USERPROFILE%\.local\bin`).
Make sure that directory is on your PATH; `uv tool update-shell` can add it.

## Create the hub

    cc-hub init              # ~/.cc-hub
    cc-hub init ~/my-hub     # anywhere else

The hub must not live inside another git repository; `init` refuses that.
Treat the hub as private data: commit it to a private repository if you want
backups. `secrets/`, generated files and agent pointers are already gitignored.

## Connect cc-connect

See [cc-connect.md](cc-connect.md). Then send the agent its first message.

## Check

    cc-hub doctor

Warnings about `bootstrap-pending` and `pointers` disappear after the first
conversation. A `daemon-path` warning means cc-connect, when run as a service,
would not find `cc-hub` or `uv`; fix it in cc-connect's config as described in
[cc-connect.md](cc-connect.md).

## Upgrade

    uv tool upgrade cc-hub
    cc-hub update --dry-run   # see what would change
    cc-hub update

`update` replaces only framework-owned files (`AGENTS.md`, `BOOTSTRAP.md`,
`skills/hub-*`, `cron/README.md`, `cron/memory-consolidate.md`, `.gitignore`)
and merges new keys into `hub.toml`. Previous versions are copied to
`.cc-hub/backups/<old version>/`. Read the migration notes in `CHANGELOG.md`
before upgrading across minor versions.
