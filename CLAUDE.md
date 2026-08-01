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

Find the run by the full forty-character hash, from `git rev-parse HEAD`. `gh run list --commit` silently returns an empty list for the short hash `git log --oneline` prints, which is indistinguishable from a run that has not started, so anything that polls should instead list recent runs and match `headSha` by prefix locally.

Longer:
[verification-in-ci-only](docs/claude/memories/verification-in-ci-only.md),
[find-a-run-by-the-full-hash](docs/claude/memories/find-a-run-by-the-full-hash.md).

## Commits

Work goes straight to `main` as direct commits. Do not create a feature
branch, do not open a pull request, and do not structure advice around a
review cycle. There is no pull-request buffer, so CI is the only review
there is and the tests land in the same commit as the code they cover.

A push rejected by CI is answered with a follow-up commit. Do not amend and force-push: `main` is published by the time the run reports, and rewriting it discards what was tried. This sits awkwardly beside solving an issue in a single push, because CI stops at the first failing gate and so surfaces one static-analysis finding per cycle. When the two collide, verifying only in CI is the rule that holds and the extra commits are its cost — local linting has been proposed and declined. Read the whole failed log rather than its first error, and sweep the change for other instances of the same shape before pushing the fix.

Longer:
[commit-straight-to-main](docs/claude/memories/commit-straight-to-main.md),
[a-rejected-push-is-fixed-forward](docs/claude/memories/a-rejected-push-is-fixed-forward.md).

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

Adding a new per-tenant store resource can fail the first `seed` run on the new PUT: `seed`, `api_common_routing` and `api_endpoint_tenants` are independent workflows on the same push, so seeding can beat both the route and the handler that stores it. The code says which is behind — `HTTP 403` is a route API Gateway does not define yet, `HTTP 404` is the old handler not knowing the collection. Wait for both, then `gh run rerun <run-id> --failed`. A later commit that misses `etc/`, `openapi.json` and `seed.py` will not re-trigger `seed` at all.

In `seed.yml`, a skipped `concluding-*` gate skip-cascades transitively to
every descendant. An ordinary expression `if` does not break the cascade;
each downstream job needs its own status-check function, normally
`if: ${{ !cancelled() && needs.<parent>.result == 'success' }}`.

A `seed` run whose push touched only `data/raw/` reports success without testing anything: `determining-testing` sets `testing-necessary=false` and the static-analysis, unit, integration and e2e jobs all skip. `gh run rerun` recomputes the same decision, so force one with `gh workflow run seed.yml --ref main`, which has no `github.event.before` and so runs every tier. The exclusion covered all of `data/` and `etc/` until the integration tier gained a contract that reads both, so a config-only push tests now; do not assume it skips.

Longer:
[seed-races-routing-deploy](docs/claude/memories/seed-races-routing-deploy.md),
[seed-skip-cascade-needs-guards](docs/claude/memories/seed-skip-cascade-needs-guards.md),
[only-raw-map-commits-skip-the-tests](docs/claude/memories/only-raw-map-commits-skip-the-tests.md).

## Markdown

Markdown is not hard-wrapped. There is no column limit on `.md` files here, and none on the bodies of GitHub issues and pull requests: write each paragraph as one line and let the reader wrap it. `markdownlint` runs with MD013 disabled and the YAML linters with `line-length: disable`, so no width is enforced anywhere. Most of the markdown already on disk was written wrapped before the restriction was lifted, so match this rule rather than the file next to you.

Longer:
[markdown-is-not-hard-wrapped](docs/claude/memories/markdown-is-not-hard-wrapped.md).

## Issues

An issue has six sections in a fixed order: "Problem", "Why Unit Tests Did Not Catch It", "Why Integration Tests Did Not Catch It", "Why E2E Tests Did Not Catch It", "Which Unit, Integration, or E2E regression tests would prevent this from happening again?", "Solution". Every issue has all six; where a tier does not exist for the code in question, saying so is the finding, not a reason to drop the section. The regression section names the tests to write, each with its tier and its assertion, and is separate from the solution so that a fix cannot ship with the coverage folded into its last paragraph. Write plain, ordinary English prose and use telecommunications vocabulary for the subject matter — path diversity rather than mesh degree, site rather than node. Tables where a table genuinely reads better, bullets only when enumerating things, never to break up an argument. Back claims with numbers computed from the repository's own data, and say how they were computed.

Longer:
[how-issues-are-written](docs/claude/memories/how-issues-are-written.md).

## Notes

A convention learned in a session belongs in this repository: a paragraph
in this file and a topic file under `docs/claude/memories/`, linked from
both indexes. The session tool's local memory directory is one machine's
unversioned files, and a rule kept in both places drifts with nothing to
signal it, which is why the local copies were deleted on 2026-07-29. Keep
there only what is true of that machine alone.
