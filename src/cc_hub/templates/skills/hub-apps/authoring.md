# Writing a hub app

An app is a top-level directory of a tap (a git repository). The directory
name is the app name: lowercase letters, digits and hyphens.

    my-apps/                       the tap
    └── ledger/                    the app
        ├── app.toml               required
        ├── SETUP.md               optional: setup steps only this app needs
        ├── REMOVE.md              optional: what to undo before removal
        ├── skills/<skill>/SKILL.md
        ├── cron/<task>.md         scheduled tasks, same format as the hub's cron/ files
        ├── reports/<period>.md    sections the app adds to the hub's reports
        ├── scripts/               called by the skills, the tasks and SETUP.md
        └── seed/<data dir>/...    copied into the hub once, never overwritten

## app.toml

    [app]
    name = "ledger"                        # equals the directory name
    version = "0.1.0"
    description = "Plain-text bookkeeping with beancount"
    min_hub = "0.4.0"                      # optional
    issues = "https://example.com/issues"  # optional; GitHub taps need none

    [data]
    dirs = ["ledger"]                      # the user's data, kept on update and removal

    [[requires]]
    name = "beancount"
    bin = "bean-check"                     # looked up on PATH, never run by cc-hub
    install = "uv tool install beancount"  # or a table with linux, macos, windows

## Scheduled tasks

`cron/<task>.md` is registered as `hub:<app>/<task>`, in the format of the
hub's `cron/README.md`: `schedule`, `default` and `session` in the
frontmatter, then the body the agent follows when the task fires. The body
may call the app's scripts.

    ---
    schedule: "0 9 1 * *"
    default: true
    session: new_per_run
    ---
    Run uv run apps/ledger/scripts/lk.py summary and send the user the result.

The user can change any task's time, or turn it off or on
(`cc-hub cron set <app>/<task> "<expr>"`, `--off`, `--on`). `SETUP.md` may
ask for a time and run that command; such an app needs `min_hub = "0.5.0"`.

## Reports

`reports/<period>.md` adds a section to the report of one period: `daily`,
`weekly`, `monthly`, `quarterly` or `yearly`. cc-hub adds the section heading;
`title` is optional and defaults to the app name.

    ---
    command: uv run apps/ledger/scripts/lk.py summary
    title: Money
    ---

With a `command`, the section is a script. cc-hub runs it from the hub root
once the user has approved it on that machine, and pastes its standard output
as it is. Empty output means no section. A failure, or a run over 300 seconds,
shows a one-line failure in the report. The arguments are split the POSIX way,
so write paths with forward slashes. The script gets `CC_HUB_DIR`,
`CC_HUB_REPORT_PERIOD`, `CC_HUB_REPORT_SINCE` and `CC_HUB_REPORT_UNTIL` (ISO
8601 with offset) and `CC_HUB_LANGUAGE` (`en` when unset): write the section
in that language.

Without a `command`, the body tells the agent what to write for the period.
Write it in English, like other agent texts; the agent answers in the user's
language.

A scheduled task of the app that finishes work quietly can leave its result
for a report: `cc-hub report note <period> --from <app>/<task> -- '<text>'`
(see "Reports" in the hub's `cron/README.md`). An app with a `reports/`
directory needs `min_hub = "0.7.0"`.

## Rules

- Skill names are unique in the hub and must not start with `hub-`.
- A data directory is a relative path; it must not be a hub file or folder
  (`memory`, `skills`, `cron`, `reports`, `scripts`, `apps`, ...). Each part
  uses only letters, digits, `.`, `_` and `-`, and does not start with `.`.
- File names inside the app do not contain `~`, and no two of them differ
  only in letter case.
- Personal settings live in a file in the data directory, such as
  `ledger/config.toml`. Credentials go in `.env` or `secrets/`, never in the
  data directory, which is committed.
- Every `SETUP.md` step checks before acting, so setup can run again after an
  update. Prefer installs that need no root, such as `uv tool install`, so the
  agent can finish them once the user approves.
- Only regular files: no symlinks, no submodules.

## Develop

    cc-hub app install ~/dev/my-apps/ledger --link --yes

`apps/ledger` then links to the working copy, and edits apply at once.

## Publish

1. Commit and push the tap to a public repository.
2. On GitHub, add the topic `cc-hub-tap` so others find it at
   https://github.com/topics/cc-hub-tap; list the apps and the software they
   need in the README.
3. Others run `cc-hub tap add <owner>/<repo>`, then
   `cc-hub app install <repo>/<app>`.
4. For a new version, raise `version` in `app.toml`, commit and push; users
   run `cc-hub app update <app>`.
