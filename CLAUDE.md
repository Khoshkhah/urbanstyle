# CLAUDE.md

**First rule: answer at once.** Run every long job (build, cut, checks, tests, page) in the background and never wait for it in the
foreground (no `until ...; sleep` loops): end the reply and let the app say when the job is done. Every message from the user is
answered first, in the next reply, before any other work.

The rules for working on this repository are in AGENTS.md, shared with every coding agent:

@AGENTS.md
