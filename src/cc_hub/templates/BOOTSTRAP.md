# Bootstrap

This is a ritual, not a gate. If the user asks for something else, do that
first and come back here. Work through the steps in order.

1. **Check.** Run `cc-hub version`. If `cc-hub` cannot be found, stop and tell
   the user the installation is incomplete: cc-hub must be installed and on
   the PATH cc-connect gives you. Nothing below works without it.
2. **Adapt.** Read `skills/hub-adapt/SKILL.md` and follow it so your own
   ecosystem finds this hub's instructions and skills, and the hub's default
   scheduled tasks are registered.
3. **Name.** Ask the user what they want to call you. Never pick a name
   yourself. Agree on a one-line vibe and an emoji. Write all three into
   `IDENTITY.md` and put the vibe line under "Core vibe" in `SOUL.md`.
4. **User.** Ask how to address them and which language to reply in. Write
   each as a dated directive in `USER.md`, replacing the placeholder lines.
5. **Finish.** Write the first entry with
   `cc-hub memory log "Bootstrap completed: <name>, <language>"`, delete this
   file, commit (see "Git" in `AGENTS.md`), run `cc-hub doctor`, and report
   the result.
