---
name: hub-feedback
description: Report a problem or a suggestion about cc-hub or an installed app as an issue on its repository. Use when a cc-hub command or a built-in hub skill misbehaves, when an app's skills, setup or scripts are wrong, or when the user wants to suggest something for cc-hub or an app.
---

# hub-feedback

Opening an issue publishes text on the internet. Nothing is filed until the
user agrees to the exact title and body.

1. **Whose problem.** cc-hub: its commands, `AGENTS.md`, `BOOTSTRAP.md` and
   the built-in skills. An app: anything under `apps/<name>/`. Neither:
   cc-connect, your own runtime, or software an app uses (such as beancount);
   tell the user which project it belongs to and stop.
2. **Where.** `cc-hub feedback` (cc-hub) or `cc-hub feedback --app <name>`
   prints the issue tracker and an environment block. If it names no tracker,
   say what it printed: the app is the user's own, or its tracker is unknown
   and its tap is shown; then stop.
3. **Already known?** If `gh auth status` succeeds, search first:
   `gh issue list -R <owner/repo> --search "<words>" --state all`. If one
   matches, show it and offer to comment there instead of opening a new one.
4. **Draft.** A one-line title. For a problem: what happened, steps to
   reproduce, expected and actual result, and the environment block. For a
   suggestion: what and why.
5. **Remove private data.** Nothing from `USER.md`, `MEMORY.md`, `memory/` or
   app data directories; no credentials, host names, IP addresses or paths
   that contain user names. Quote only the error lines that matter.
6. **Ask.** Show the full title and body. File only after the user agrees:
   with `gh`, write the body to a temporary file and run
   `gh issue create -R <owner/repo> --title "<title>" --body-file <file>`;
   without `gh`, give the user the new-issue link and the text to paste.
7. **Record.** `cc-hub memory log "issue filed: <url>"`.

In a scheduled task or a group chat, only draft: log the draft with
`cc-hub memory log` and bring it up in the next direct chat with the user.
