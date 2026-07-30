# Notes for Claude sessions in wan-graph-synthesizer

`CLAUDE.md` at the repository root carries the standing conventions in
short form and is read at the start of every session. These files carry
the longer versions: the reasoning, the incidents that produced each rule,
and the details needed occasionally rather than constantly. One note per
topic, so a session can read the one rule it needs.

These were kept as local memory files until 2026-07-29 and were committed
so they survive the machine they were written on. The local copies have
been deleted, so these files are the only version there is. A convention
learned in a session belongs here — a paragraph in `CLAUDE.md` and a
topic file in this directory, linked from both indexes. Keep in the
session tool's local memory only what is true of one machine alone.

## Working practice

- [verification-in-ci-only](verification-in-ci-only.md) — nothing runs
  locally; push and read the run
- [commit-straight-to-main](commit-straight-to-main.md) — direct commits,
  no branches and no pull requests
- [markdown-is-not-hard-wrapped](markdown-is-not-hard-wrapped.md) — no
  column limit on `.md` files or on issue and pull-request bodies

## Tests

- [tdd-workflow](tdd-workflow.md) — the test is written before the code,
  in the same commit
- [read-test-tenets-first](read-test-tenets-first.md) — read
  `docs/tenets/tests/` before implementing, and cover every tier the
  change touches
- [tenets-are-generic](tenets-are-generic.md) — the tenets name no tool,
  language or directory; the repository follows them, not the reverse

## CI workflows

- [seed-races-routing-deploy](seed-races-routing-deploy.md) — a new
  tenant resource can 403 in `seed` before `api_common_routing` publishes
  its route
- [seed-skip-cascade-needs-guards](seed-skip-cascade-needs-guards.md) —
  a skipped gate silently skips every descendant without a status-check
  `if`
- [config-only-commits-skip-the-tests](config-only-commits-skip-the-tests.md)
  — a push touching only `data/` or `etc/` skips every test tier; force
  them with `workflow_dispatch`
