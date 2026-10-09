# Apps

An app adds a capability to the hub, such as bookkeeping or machine
management. It is a directory of files: skills that teach the agent to use
some software, scheduled task definitions, setup steps and a skeleton for its
data. The software itself (for example beancount) is an ordinary program the
agent installs on the machine with your approval. cc-hub copies app files and
never runs anything an app provides.

Apps live in **taps**: git repositories with one top-level directory per app.

## Use apps

    cc-hub tap add you/my-apps              # a GitHub repository; any git URL or local repository works
    cc-hub app search ledger
    cc-hub app install my-apps/ledger       # prints an overview, changes nothing
    cc-hub app install my-apps/ledger --ref <commit> --yes

Usually you ask the agent instead; it runs the same commands, shows you the
overview, and after you agree installs the app and sets it up: installs the
software it needs (asking first), asks for your settings, and registers the
app's scheduled tasks with cc-connect.

`cc-hub app update <name>` shows what changed in the tap; `--yes` applies it.
`cc-hub app remove <name>` shows what removal involves; `--yes` removes the
app and keeps its data. `cc-hub app list` shows each app's setup state on this
machine and any missing software.

Installed apps are in `apps/`, which is not committed. `apps.lock` is: after
cloning the hub to another machine, `cc-hub app sync` restores the apps and
the agent sets them up there.

## Write an app

    my-apps/
    └── ledger/
        ├── app.toml               required
        ├── SETUP.md               optional: setup steps only this app needs
        ├── REMOVE.md              optional: what to undo before removal
        ├── skills/ledger/SKILL.md
        ├── cron/monthly.md        same format as the hub's cron/ files
        ├── scripts/
        └── seed/ledger/main.beancount

`app.toml`:

    [app]
    name = "ledger"                        # equals the directory name
    version = "0.1.0"
    description = "Plain-text bookkeeping with beancount"
    min_hub = "0.4.0"                      # optional
    issues = "https://example.com/issues"  # optional; GitHub taps need none

    [data]
    dirs = ["ledger"]

    [[requires]]
    name = "beancount"
    bin = "bean-check"
    install = "uv tool install beancount"

`install` may also be a table with `linux`, `macos` and `windows` keys.

Rules:

- Names (apps, skills, scheduled tasks, taps) use lowercase letters, digits
  and hyphens; skill names must not start with `hub-` and must be unique in the
  hub.
- Data directories are relative paths outside the hub's own files and
  folders. Files under `seed/` are copied into them once and never
  overwritten. Personal settings belong there too; credentials belong in
  `.env` or `secrets/`.
- `SETUP.md` steps check before they act, so setup can run again after an
  update. Prefer installs without root.
- Only regular files: no symlinks or submodules.

While developing, link your working copy so edits apply at once:

    cc-hub app install ~/dev/my-apps/ledger --link --yes

## Publish

1. Push the tap to a public repository.
2. On GitHub, add the topic `cc-hub-tap`; others browse
   https://github.com/topics/cc-hub-tap. List the apps and the software they
   need in the README.
3. Others run `cc-hub tap add <owner>/<repo>` and
   `cc-hub app install <repo>/<app>`.
4. Release a new version by raising `version` in `app.toml`, committing and
   pushing; users update with `cc-hub app update`.
