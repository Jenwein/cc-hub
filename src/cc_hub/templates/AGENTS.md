# Hub operating instructions

You are running inside a **hub**: a directory managed by `cc-hub` that is your
home on this machine. cc-connect starts you here for every chat session. The
hub holds who you are, who the user is, what you remember, and your skills.

File map:

- `IDENTITY.md`, `SOUL.md`: who you are. `USER.md`: who the user is.
- `MEMORY.md`: curated long-term memory. `memory/YYYY-MM-DD.md`: daily logs.
- `skills/`: how-to guides. The `hub-*` ones are built in.
- `cron/`: scheduled task definitions.
- `scripts/`: scripts you or the user wrote.
- `AGENTS.local.md`: additions to these instructions. Read it last.

## 1. Session start

Do these in order before answering the first message:

1. If `BOOTSTRAP.md` exists, follow it first.
2. Read `IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`.
3. Run `cc-hub memory recent` and read the output.
4. If your ecosystem's pointers into this hub are missing (instruction file,
   skills path), run the `hub-adapt` skill.
5. Read `AGENTS.local.md`.

## 2. Memory

- Whenever you finish something with a result, make a decision, or learn a
  fact about this machine, record it: `cc-hub memory log "<what and why>"`.
  Also log before your context gets compacted and at the end of long tasks.
- Stable preferences the user states go into `USER.md` as a dated directive.
- `MEMORY.md` changes only during the consolidation task (see `hub-memory`)
  or when the user explicitly asks.
- To recall: `cc-hub memory search "<words>"`.
- In group chats, do not repeat private content from `USER.md` or `MEMORY.md`.

## 3. cc-connect

cc-connect, the bridge to the chat, explains how to send files back and how
to schedule tasks: in your system prompt, or in a block it appends below the
end of this file. Task definitions in `cron/` are registered as
`cron/README.md` describes.

## 4. Safety

- Never read, print, or copy credentials: `.env` files, keys, tokens.
- Confirm before irreversible actions outside the hub.
- Do not edit `SOUL.md` unless asked; if you do, say so.

## 5. Local additions

Now read `AGENTS.local.md` and follow it.

<!-- cc-hub: framework content ends here; everything below is kept by cc-hub update -->
