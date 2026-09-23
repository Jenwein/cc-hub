# Bootstrap

This is a ritual, not a gate. If the user asks for something else, do that
first and come back here. Work through the steps in order; skip a step only
where it says you may.

1. **Environment.** Run `cc-hub env` and read `ENV.md`. If `cc-hub` cannot be
   found, stop and tell the user the installation is incomplete (see
   `docs/install.md` in the cc-hub repository). Nothing below works without it.
2. **Adapt.** Follow the `hub-adapt` skill so your own ecosystem finds this
   hub's instructions, skills and hooks.
3. **Name.** Ask the user what they want to call you. Never pick a name
   yourself. Agree on a one-line vibe and an emoji. Write all three into
   `IDENTITY.md` and put the vibe line under "Core vibe" in `SOUL.md`.
4. **User.** Ask three things: how to address them, which language to reply
   in, and what they mainly work on. Write each as a dated directive in
   `USER.md`, replacing the placeholder lines.
5. **Projects.** Ask for one to three directories they work in most and
   register each with `cc-hub projects add <path>`. May be skipped.
6. **Hosts.** Ask whether there are remote machines you should be able to
   reach. Register each in `hosts.toml`. May be skipped.
7. **Scheduled tasks.** For every file in `cron/` with `default: true`, run
   `cc-connect cron add --cron "<schedule>" --prompt "<body>"`. If
   `cc-connect` is not available, log that this is still to do.
8. **Safety note.** Tell the user, in one or two sentences, that a hook blocks
   catastrophic commands and that cc-connect's approval mode is the first line
   of defense.
9. **Finish.** Write the first entry with
   `cc-hub memory log "Bootstrap completed: <name>, <language>, <projects>"`,
   delete this file, run `cc-hub doctor`, and report the result.
