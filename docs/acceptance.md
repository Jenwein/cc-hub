# Manual acceptance checklist

Environment: WSL2, cc-connect running as a service, Claude Code as the agent,
one chat platform (Feishu or any other).

1. Install cc-hub from a regular terminal (see `install.md`), `cc-hub init`,
   `cc-hub doctor`: everything green except `bootstrap-pending`.
2. Configure cc-connect `work_dir` and `env.PATH`, restart cc-connect.
3. Send the first message. The agent runs bootstrap: asks for a name, writes
   `IDENTITY.md` and `USER.md`, runs `hub-adapt`, registers the cron task,
   deletes `BOOTSTRAP.md`.
4. `cc-hub doctor`: all green.
5. Ask the agent to remember something. `memory/` has today's file;
   `cc-hub memory search` finds it.
6. Point a Codex bot at the same hub and send `/cron setup` in its chat.
   `AGENTS.md` ends with cc-connect's instructions block.
7. Bump the package version and run `cc-hub update`: `AGENTS.md` changes above
   its closing marker and keeps everything below it (the cc-connect block
   included); `SOUL.md`, `USER.md` and `memory/` do not change; and
   `.cc-hub/backups/` holds the previous version.
