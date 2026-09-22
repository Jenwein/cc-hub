# Manual acceptance checklist

Environment: WSL2, cc-connect running as a daemon, Claude Code as the agent,
one chat platform (Feishu or any other).

1. `uv tool install cc-hub`, `cc-hub init`, `cc-hub doctor`: everything green
   except `bootstrap-pending` and `pointers`.
2. Configure cc-connect `work_dir` and `env.PATH`, restart the daemon.
3. Send the first message. The agent runs bootstrap: asks for a name, writes
   `IDENTITY.md` and `USER.md`, runs `hub-adapt`, registers the cron task,
   deletes `BOOTSTRAP.md`.
4. `cc-hub doctor`: all green.
5. Ask the agent to remember something. `memory/` has today's file;
   `cc-hub memory search` finds it.
6. Ask the agent to run the tests of a registered project in the background.
   You receive a job id; asking for progress makes the agent use `jobs status`;
   after completion the memory log has a summary.
7. Ask the agent to run a command with Chinese characters and quotes on a
   registered remote host. Output is correct.
8. Ask the agent to run a command that hits the blocklist but is harmless even
   if the hook failed, for example `git push --force origin main` in a
   throwaway repository with no remote. It is blocked and the agent explains.
9. Ask the agent to send a file back to the chat. It arrives.
10. Bump the package version and run `cc-hub update`: `AGENTS.md` changes,
    `SOUL.md`, `USER.md` and `memory/` do not, and `.cc-hub/backups/` holds
    the previous version.
