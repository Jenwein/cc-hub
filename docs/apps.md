# Apps

An app adds a capability to the hub, such as bookkeeping or machine
management. It is a directory of files: skills that teach the agent to use
some software, scheduled task definitions, setup steps and a skeleton for its
data. The software itself (for example beancount) is an ordinary program the
agent installs on the machine with your approval. cc-hub copies app files and
runs nothing an app provides, except the commands of its report sections that
you approved on that machine (see "Reports" below).

Apps live in **taps**: git repositories with one top-level directory per app.

## Use apps

    cc-hub tap add you/my-apps              # a GitHub repository; any git URL or local repository works
    cc-hub app search ledger
    cc-hub app install my-apps/ledger       # prints an overview, changes nothing
    cc-hub app install my-apps/ledger --ref <commit> --yes

A private tap needs your own git access (a credential helper or an ssh
key); a tap URL with a password or token in it is refused.

Usually you ask the agent instead; it runs the same commands, shows you the
overview, and after you agree installs the app and sets it up: installs the
software it needs (asking first), asks for your settings, shows you the
commands of its report sections to approve, and registers the app's scheduled
tasks with cc-connect.

`cc-hub app update <name>` shows what changed in the tap; `--yes` applies it.
A report command that changed needs your approval again.
`cc-hub app remove <name>` shows what removal involves; `--yes` removes the
app, keeps its data and drops the times you set for its tasks, its report
settings and this machine's approvals of its report commands.
`cc-hub app list` shows each app's setup state on this machine and any
missing software.

To run an app's task at another time, or turn it off, ask the agent, or run
the command and let the agent re-register the task:

    cc-hub cron set plans/morning "0 7 * * *"   # <app>/<task>, then a quoted cron expression
    cc-hub cron set ledger/prices --off         # --on turns it back on
    cc-hub cron reset plans/morning             # back to the app's own time

The time is kept in `hub.toml`, so app updates and `cc-hub update` keep it.
`cc-hub cron list` shows every task with the time in force.

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
        ├── reports/<period>.md    optional: a section of the hub's report (see Reports)
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
  folders. Each part uses only letters, digits, `.`, `_` and `-`, and does
  not start with `.`. Files under `seed/<data dir>/` are copied into them
  once and never overwritten. Personal settings belong there too;
  credentials belong in `.env` or `secrets/`.
- File names inside the app do not contain `~`, and no two of them differ
  only in letter case.
- `SETUP.md` steps check before they act, so setup can run again after an
  update. Prefer installs without root.
- Only regular files: no symlinks or submodules.

While developing, link your working copy so edits apply at once:

    cc-hub app install ~/dev/my-apps/ledger --link --yes

## Scheduled tasks

Each `cron/<task>.md` is one task, registered with cc-connect as
`hub:<app>/<task>` when the app is set up:

    ---
    schedule: "0 9 1 * *"        # five-field cron expression
    default: true                # registered at setup; false: only when the user turns it on
    session: new_per_run         # or reuse: run inside the chat's ongoing session
    ---
    What the agent does when the task fires.

The task is registered with a prompt that points at this file, so the agent
reads the body each time the task fires, and a new version of the app takes
effect at the next run. The body may call the app's scripts. Users pick
their own times with `cc-hub cron set` (see above); `SETUP.md` may ask for a
time and run `cc-hub cron set <app>/<task> "<expr>"`, which needs
`min_hub = "0.5.0"`.

## Reports

A report is a digest the hub sends to the user's chat each day, week, month,
quarter or year. `reports/<period>.md` adds a section to the report of one
period: `daily`, `weekly`, `monthly`, `quarterly` or `yearly`. cc-hub adds the
section heading; `title` is optional and defaults to the app name.

    ---
    command: uv run apps/ledger/scripts/lk.py summary
    title: Money
    ---

With a `command`, the section is a script. cc-hub runs it from the hub root
once the user has approved it on that machine, and pastes its standard output
into the report as it is, without the agent seeing it. Empty output means no
section; output beyond 20000 characters is cut with a marker. A failure, or a
run over 300 seconds, shows a one-line failure in the report, with the first
line of standard error (at most 300 characters). A section file that cannot
be read shows its error the same way until it is fixed or switched off. An
approval is for the exact command text: a version of the app that changes it
asks the user again.

The command is not run through a shell: its arguments are split the POSIX way
(write paths with forward slashes), and there are no pipes and no `$VAR`
expansion. The script gets `CC_HUB_DIR`, `CC_HUB_REPORT_PERIOD`,
`CC_HUB_REPORT_SINCE` and `CC_HUB_REPORT_UNTIL` (ISO 8601 with offset) and
`CC_HUB_LANGUAGE` (`en` when unset) in its environment: read them there, and
write the section in that language. Put the `command` value in double quotes
if it contains `#`; unquoted, a `#` that follows a space starts a comment.

Without a `command`, the body tells the agent what to write for the period.
Write it in English, like other agent texts; the agent answers in the user's
language.

A scheduled task of the app that finishes work quietly can leave its result
for a report: `cc-hub report note <period> --from <app>/<task> -- '<text>'`.
When no report is on, the note is not kept and the task replies with the
text itself. An app with a `reports/` directory needs `min_hub = "0.7.0"`.

During setup the agent shows the user each report command and approves it
(`cc-hub report approve <app>`) once they agree; until then the report holds
a line saying the command is not approved in place of that section. The user
can leave an app out of one period (`cc-hub report section <app> <period>
--off`), and `cc-hub report list` shows every period, section and approval.

## Publish

1. Push the tap to a public repository.
2. On GitHub, add the topic `cc-hub-tap`; others browse
   https://github.com/topics/cc-hub-tap. List the apps and the software they
   need in the README.
3. Others run `cc-hub tap add <owner>/<repo>` and
   `cc-hub app install <repo>/<app>`.
4. Release a new version by raising `version` in `app.toml`, committing and
   pushing; users update with `cc-hub app update <app>`.

Problems with an app go to its tap's issue tracker: `cc-hub feedback --app
<name>` prints where, and the agent drafts the issue for you to approve.
