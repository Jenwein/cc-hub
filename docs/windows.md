# Windows notes

## Recommended: WSL2

Run cc-connect, the agent CLIs and the hub inside WSL2. Keep the hub on the
Linux filesystem (`~/.cc-hub`), not under `/mnt/c`, which is slow and has
different permission semantics. Everything in this project behaves as on Linux.

## Native Windows

cc-hub works natively, with these differences:

- **Links.** Creating symlinks needs Developer Mode or administrator rights,
  so `cc-hub link` creates a directory junction instead; if that fails it
  copies and leaves a `.cc-hub-copied` marker. `cc-hub doctor` reports
  `link-stale` when the copy is older than `skills/`; re-run the `hub-adapt`
  skill to refresh it.
- **Shell.** Claude Code uses Git Bash for its Bash tool when Git for Windows
  is installed and PowerShell otherwise; Codex uses PowerShell. The blocklist
  covers both syntaxes (`rm -rf ~` and `Remove-Item -Recurse -Force`).
- **Hooks.** Use the absolute path printed by `cc-hub hook snippet`; it avoids
  `.cmd` shim problems. Codex hooks accept a `commandWindows` field if you need
  a different command on Windows.
- **Encoding.** All cc-hub output is UTF-8. Job logs are stored as raw bytes
  and decoded on read, so GBK output from legacy tools is still readable.
- **Line endings.** Keep hub files LF. Some skill loaders silently drop
  frontmatter when a `SKILL.md` has CRLF endings.
- **Paths.** The hub defaults to `%USERPROFILE%\.cc-hub`. cc-connect's
  `run_as_user` is not available on Windows; use `mode = "default"` approvals.
