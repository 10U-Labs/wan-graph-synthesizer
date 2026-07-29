# Working in wan-graph-synthesizer

These are the standing conventions for working in this repository. Each
section links the longer write-up behind it, one note per topic under
`docs/claude/memories/`;
[docs/claude/memories/README.md](docs/claude/memories/README.md) indexes
them all.

## Verification

CI is the source of truth. Do not run tests, linters or builds locally to
verify a change — write the code and the tests, commit, push to `main`,
and read the run with `gh run list` / `gh run watch` /
`gh run view --log-failed`. Local runs cost tokens; CI is free and checks
every gate at once.

A push can trigger several path-filtered workflows. The change is done
when each workflow that fired is green, not when the first one is.

Longer:
[verification-in-ci-only](docs/claude/memories/verification-in-ci-only.md).

## Commits

Work goes straight to `main` as direct commits. Do not create a feature
branch, do not open a pull request, and do not structure advice around a
review cycle. There is no pull-request buffer, so CI is the only review
there is and the tests land in the same commit as the code they cover.

Longer:
[commit-straight-to-main](docs/claude/memories/commit-straight-to-main.md).

## Tests

We do TDD: the test is written first, then the code that makes it pass.
Test-first means authoring order — the red and green observations belong
to CI, since nothing runs locally.

Read `docs/tenets/tests/` before implementing. The repository enforces a
strict hierarchy — `pre_deployment/{unit,integration}` and
`post_deployment/integration` — and unit tests alone are not sufficient.
Add coverage at every tier the change touches, one assert per pytest.

Those docs are tenets, not a description of the suite. They name no
language, tool, directory or resource, because the repository already
states all of that and a second copy drifts. When a tenet and the
repository disagree, the repository is what changes. Editing a tenet to
match the code is backwards.

Longer: [tdd-workflow](docs/claude/memories/tdd-workflow.md),
[read-test-tenets-first](docs/claude/memories/read-test-tenets-first.md),
[tenets-are-generic](docs/claude/memories/tenets-are-generic.md).

## CI workflows

Adding a new per-tenant store resource can fail the first `seed` run with
`HTTP 403` on the new PUT: `seed` and `api_common_routing` are independent
workflows on the same push, so seeding can beat the route into existence.
Wait for `api_common_routing`, then `gh run rerun <run-id> --failed`. A
later commit that misses `etc/`, `openapi.json` and `seed.py` will not
re-trigger `seed` at all.

In `seed.yml`, a skipped `concluding-*` gate skip-cascades transitively to
every descendant. An ordinary expression `if` does not break the cascade;
each downstream job needs its own status-check function, normally
`if: ${{ !cancelled() && needs.<parent>.result == 'success' }}`.

A `seed` run whose push touched only `data/` or `etc/` reports success
without testing anything: `determining-testing` sets
`testing-necessary=false` and the static-analysis, unit, integration and
e2e jobs all skip. Read the job list, not the conclusion. A series that
moves configs in commits separate from the reader they feed therefore
tests nothing, and `gh run rerun` recomputes the same decision — end it
with `gh workflow run seed.yml --ref main`, which has no
`github.event.before` and so runs every tier.

Longer:
[seed-races-routing-deploy](docs/claude/memories/seed-races-routing-deploy.md),
[seed-skip-cascade-needs-guards](docs/claude/memories/seed-skip-cascade-needs-guards.md),
[config-only-commits-skip-the-tests](docs/claude/memories/config-only-commits-skip-the-tests.md).

## Notes

A convention learned in a session belongs in this repository: a paragraph
in this file and a topic file under `docs/claude/memories/`, linked from
both indexes. The session tool's local memory directory is one machine's
unversioned files, and a rule kept in both places drifts with nothing to
signal it, which is why the local copies were deleted on 2026-07-29. Keep
there only what is true of that machine alone.
