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
- [find-a-run-by-the-full-hash](find-a-run-by-the-full-hash.md) — `gh run list --commit` returns nothing for a short hash, and says nothing about why
- [commit-straight-to-main](commit-straight-to-main.md) — direct commits,
  no branches and no pull requests
- [a-rejected-push-is-fixed-forward](a-rejected-push-is-fixed-forward.md) — a failed run is answered with a follow-up commit, never an amended force-push
- [markdown-is-not-hard-wrapped](markdown-is-not-hard-wrapped.md) — no
  column limit on `.md` files or on issue and pull-request bodies
- [how-issues-are-written](how-issues-are-written.md) — six fixed sections for the program, two for everything else, plain English, telecom vocabulary
- [write-the-exact-name](write-the-exact-name.md) — name the file, function and line everywhere, in chat as much as in issues; never a coined collective noun
- [lead-with-what-it-is-for](lead-with-what-it-is-for.md) — say what the thing is and what it costs before the first identifier, and cut the details that change nothing
- [an-either-is-a-question-for-the-user](an-either-is-a-question-for-the-user.md) — an issue offering alternatives is asked about before anything is written, never decided

## Tests

- [tdd-workflow](tdd-workflow.md) — the test is written before the code,
  in the same commit
- [read-test-tenets-first](read-test-tenets-first.md) — read
  `docs/tenets/tests/` before implementing, and cover every tier the
  change touches
- [tenets-are-generic](tenets-are-generic.md) — the tenets name no tool,
  language or directory; the repository follows them, not the reverse
- [the-test-tree-splits-on-deployment-phase](the-test-tree-splits-on-deployment-phase.md) — `pre_deployment/{unit,integration}` and `post_deployment/{integration,e2e}` in every subsystem; a stub journey is integration, not end to end

## CI workflows

- [seed-races-routing-deploy](seed-races-routing-deploy.md) — a new
  tenant resource can 403 in `seed` before `api_common_routing` publishes
  its route
- [seed-skip-cascade-needs-guards](seed-skip-cascade-needs-guards.md) —
  a skipped gate silently skips every descendant without a status-check
  `if`
- [only-raw-map-commits-skip-the-tests](only-raw-map-commits-skip-the-tests.md) — a push touching only `data/raw/` skips every test tier; a config-only push no longer does
- [where-a-test-runs-follows-what-starts-it](where-a-test-runs-follows-what-starts-it.md) — a test runs in the workflow the change it guards arrives on; API shape in the endpoint's workflow, rebuilt WANs in `seed`, and a shared module in every workflow that imports it
- [shared-modules-are-tested-first](shared-modules-are-tested-first.md) — `test-repo-libraries` runs every module's tests under `test/lib/python/` ahead of every job whose tests import them
