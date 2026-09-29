# Manual acceptance checklist

Environment: WSL2, cc-connect running as a daemon, Claude Code as the agent,
one chat platform (Feishu or any other).

1. `uv tool install cc-hub`, `cc-hub init`, `cc-hub doctor`: everything green
   except `bootstrap-pending` and `env-stale`.
2. Configure cc-connect `work_dir` and `env.PATH`, restart the daemon.
3. Send the first message. The agent runs bootstrap: asks for a name, writes
   `IDENTITY.md` and `USER.md`, runs `hub-adapt`, registers the cron task,
   deletes `BOOTSTRAP.md`.
4. `cc-hub doctor`: all green.
5. Ask the agent to remember something. `memory/` has today's file;
   `cc-hub memory search` finds it.
6. Ask the agent to run the tests of a registered project by name. It finds
   the path in `projects.toml`, runs them there, and logs the outcome.
7. Ask the agent to run a command on a registered remote host by name. It
   finds the target, port and key in `hosts.toml` and connects with ssh.
8. Ask the agent to send a file back to the chat. It arrives.
9. Bump the package version and run `cc-hub update`: `AGENTS.md` changes,
   `SOUL.md`, `USER.md` and `memory/` do not, and `.cc-hub/backups/` holds
   the previous version.
