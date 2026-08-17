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

A push rejected by CI is answered with a follow-up commit. Do not amend and force-push: `main` is published by the time the run reports, and rewriting it discards what was tried. This used to sit awkwardly beside solving an issue in a single push, because the eleven static-analysis checks were eleven steps of one job and a job stops at its first failing step, so a push surfaced one finding per cycle; each check is now a job of its own and a run reports every finding it has. Where the two still collide, verifying only in CI is the rule that holds and the extra commits are its cost — local linting has been proposed and declined. Read the whole failed log rather than its first error, and sweep the change for other instances of the same shape before pushing the fix.

Longer:
[commit-straight-to-main](docs/claude/memories/commit-straight-to-main.md),
[a-rejected-push-is-fixed-forward](docs/claude/memories/a-rejected-push-is-fixed-forward.md).

## Tests

We do TDD: the test is written first, then the code that makes it pass.
Test-first means authoring order — the red and green observations belong
to CI, since nothing runs locally.

Read `docs/tenets/tests/` before implementing. Unit tests alone are not sufficient: add coverage at every tier the change touches, one assert per pytest.

Those docs are tenets, not a description of the suite. They name no
language, tool, directory or resource, because the repository already
states all of that and a second copy drifts. When a tenet and the
repository disagree, the repository is what changes. Editing a tenet to
match the code is backwards.

Every subsystem under `test/` is laid out as `pre_deployment/{unit,integration}` and `post_deployment/{integration,e2e}`, and a tier directory appears only when a test exists to put in it. The deployment phase is the top split because neither post-deployment tier can be attempted until there is a deployment to call. A journey against a localhost stub is pre-deployment integration however end-to-end it looks: `test/scripts/seed/pre_deployment/integration/test_cli.py` drives `scripts/seed.py` as a subprocess and touches nothing live, while `test/scripts/seed/post_deployment/e2e/test_delivered_designs.py` reads the deployed API.

Longer: [tdd-workflow](docs/claude/memories/tdd-workflow.md),
[read-test-tenets-first](docs/claude/memories/read-test-tenets-first.md),
[tenets-are-generic](docs/claude/memories/tenets-are-generic.md),
[the-test-tree-splits-on-deployment-phase](docs/claude/memories/the-test-tree-splits-on-deployment-phase.md).

## CI workflows

Every static-analysis check is a job of its own, so one push reports every finding it has instead of the first one. In the ten `api_*.yml` workflows the eleven are `lint-yaml`, `assert-no-inline-directives`, `assert-no-linter-config-files`, `assert-one-assert-per-pytest`, `pylint-source`, `mypy-source`, `copy-paste-source`, `pylint-tests`, `mypy-tests`, `copy-paste-tests` and `validate-stack`; `seed.yml` has nine of them, all gated on nothing — it deploys no OpenTofu of its own, so there is no `validate-stack`, and its separate `yamllint` job lints `.github/workflows/seed.yml` along with the five tenant configs in `etc/`, so there is no `lint-yaml` either. They all start when the workflow does, they install only the tools they run, and they sit in alphabetical order in the file because `yamllint` runs with `key-ordering: enable`. `test-repo-libraries` starts with them rather than behind them, and `reconciliation` — `seeding` in `seed.yml` — needs every gate in the workflow, because it runs `tofu apply` against live AWS and an apply cannot be taken back. A green tier beside a red check is unestablished rather than a pass, and gating the deploy on every check is what makes the run say so.

Adding a new per-tenant store resource can fail the first `seed` run on the new PUT: `seed`, `api_common_routing` and `api_endpoint_tenants` are independent workflows on the same push, so seeding can beat both the route and the handler that stores it. The code says which is behind — `HTTP 403` is a route API Gateway does not define yet, `HTTP 404` is the old handler not knowing the collection. Wait for both, then `gh run rerun <run-id> --failed`. A later commit that misses `etc/`, `openapi.json` and `seed.py` will not re-trigger `seed` at all.

In `seed.yml`, a skipped `concluding-*` gate skip-cascades transitively to
every descendant. An ordinary expression `if` does not break the cascade;
each downstream job needs its own status-check function, normally
`if: ${{ !cancelled() && needs.<parent>.result == 'success' }}`.

A `seed` run whose push touched only `data/raw/` reports success without testing the code that seeds: `determining-testing` sets `testing-necessary=false` and `unit-tests` and `integration-tests` both skip. The nine static-analysis checks, `yamllint` and `test-repo-libraries` are gated on nothing and still run, so the nine shared modules under `lib/python/` are still tested. `seeding` still runs, through `concluding-testing-unnecessary`, and `e2e-tests` after it — so the published networks are still measured, but nothing that would have caught a broken `scripts/seed.py` before it wrote to the live API ran first. `gh run rerun` recomputes the same decision, so force one with `gh workflow run seed.yml --ref main`, which has no `github.event.before` and so runs every tier. The exclusion covered all of `data/` and `etc/` until the integration tier gained a contract that reads both, so a config-only push tests now; do not assume it skips.

Shared machinery is tested in every workflow that imports it, and before the tests that stand on it. A module under `lib/python/` has no workflow of its own and no single consumer, so its subtree under `test/lib/python/` runs in each workflow whose own tests import it — transitively, since `test_handler_contracts` imports `test_module_utils` and `test_s3_store_mock`, and `test_terraform_config` sits under `test_fixtures.aws` and `test_terraform_drift`. Each of the eleven workflows that run Python tests carries a `test-repo-libraries` job for this: it starts when the workflow does, runs all nine modules' tests rather than the subset that workflow imports, and is named in the `needs:` of every job there whose tests import them, written out rather than left to arrive down the chain. It gates each module with a `--cov=lib/python/<module>` of its own, so a module arriving without tests fails rather than being carried by its neighbours' numbers, and each workflow lists `test/lib/python/**` in its `paths`. A workflow of its own for these modules cannot be made to work, because GitHub Actions orders nothing between workflows started by the same push, and an expression `if` reading the job's result is not a substitute for the `needs:` edge.

A test runs in the workflow the change it guards arrives on. Tests about how an API behaves and how its deployment is shaped belong in that endpoint's own workflow: `test_01_existence.py`, `test_02_configuration.py` and `test_03_wiring.py` run in `api_endpoint_tenants_wan_post.yml` after `reconciliation`. Whether a WAN was actually rebuilt from a change to `etc/` belongs in `seed.yml`, because a push touching `etc/` alone starts `seed.yml` and nothing else, and its `seeding` job is what delivers the change and POSTs the builds — so `test/scripts/seed/post_deployment/e2e/test_delivered_designs.py` runs there, in the `e2e-tests` job after `seeding`. Which directory a test sits in is the separate question of what it checks, and the two agreeing is the ordinary case; where they do not, the workflow must list the file and its whole conftest chain in its `paths`, which is what `api_endpoint_tenants_wan_post.yml` does for `test/lib/python/test_published_designs/**`.

Longer:
[every-check-is-its-own-job](docs/claude/memories/every-check-is-its-own-job.md),
[shared-modules-are-tested-first](docs/claude/memories/shared-modules-are-tested-first.md),
[where-a-test-runs-follows-what-starts-it](docs/claude/memories/where-a-test-runs-follows-what-starts-it.md),
[seed-races-routing-deploy](docs/claude/memories/seed-races-routing-deploy.md),
[seed-skip-cascade-needs-guards](docs/claude/memories/seed-skip-cascade-needs-guards.md),
[only-raw-map-commits-skip-the-tests](docs/claude/memories/only-raw-map-commits-skip-the-tests.md).

## Markdown

Markdown is not hard-wrapped. There is no column limit on `.md` files here, and none on the bodies of GitHub issues and pull requests: write each paragraph as one line and let the reader wrap it. `markdownlint` runs with MD013 disabled and the YAML linters with `line-length: disable`, so no width is enforced anywhere. Most of the markdown already on disk was written wrapped before the restriction was lifted, so match this rule rather than the file next to you.

Longer:
[markdown-is-not-hard-wrapped](docs/claude/memories/markdown-is-not-hard-wrapped.md).

## Writing

Name things by their names, everywhere — chat replies as much as issues, pull requests, commit messages, docstrings and comments. A name is something the reader can open: a path, a function with its file and line, an S3 object key, a workflow file, a config key, an endpoint with its method. Coined collective nouns are the failure to avoid: "the layer", "the machinery", "the pipeline", "the store" read as repository vocabulary the reader is meant to recognise, so they go looking and find nothing. Say the directory, the module, the bucket, the object key instead. Simple English and precision are separate requirements and both are owed: short sentences and no computer-science jargon where a plain word will do, and the exact identifier rather than a description of it. Verify a name before writing it — a wrong name costs more than a vague one, because it sends the reader somewhere real and wrong.

Lead with what the thing is for. Every paragraph opens with a plain sentence saying what the thing is and what it does, in words that need no file open, and the identifiers come after it — a name before that sentence is a demand, because the reader cannot yet tell why they are being told about it. Say what a defect costs in ordinary words near the top rather than in the seventh paragraph. Then cut: a detail stays where it changes what somebody would do and moves later or goes where it does not, so a correct table of eight config keys still reads as a wall when it arrives before the reader knows why eight keys matter. Order for the reader, who has not opened the files and will not open them while reading, rather than for yourself, who knew the shape before writing a word. Cutting a correct detail is not vagueness; replacing it with a coined noun is.

Say peers and paths. A peer is another backbone site this one has a circuit to; a path is one route between two sites, crossing whatever cities the fiber makes it cross. Those two words answer almost every question about a backbone, and "cable" answers none of them: cable is a real thing at one scale only, a single span between two adjacent points, so "Ashburn has four cables" leaves a reader unable to tell whether four spans, four paths or four circuits were meant. Peers and diverse paths are two different things and conflating them hides defects — `number_of_diverse_paths` is spent as peer slots by `select_backbone_mesh_pairs`, how many routes one pair is drawn with is `synthesizer.ceiling.routes_per_peer`, and a site's diverse paths are the links out of it no single city's loss takes two of (GitHub issue #59).

Longer:
[write-the-exact-name](docs/claude/memories/write-the-exact-name.md),
[lead-with-what-it-is-for](docs/claude/memories/lead-with-what-it-is-for.md),
[say-peers-and-paths](docs/claude/memories/say-peers-and-paths.md).

## Issues

An issue about the program has six sections in a fixed order: "Problem", "Why Unit Tests Did Not Catch It", "Why Integration Tests Did Not Catch It", "Why E2E Tests Did Not Catch It", "Which Unit, Integration, or E2E regression tests would prevent this from happening again?", "Proposed Solution". Every such issue has all six; where a tier does not exist for the part of the program in question, saying so is the finding, not a reason to drop the section. The regression section names the tests to write, each with its tier and its assertion, and is separate from the solution so that a fix cannot ship with the coverage folded into its last paragraph.

The four test sections belong to the program and to nothing else. The program is what a test tier can run: `src/`, `lib/python/`, `scripts/`, and the OpenTofu under `lib/`. An issue about the configs in `etc/`, the maps in `data/`, the workflow files in `.github/workflows/` or the documentation has two sections, "Problem" and "Proposed Solution", and owes no tests — a test over a file no tier runs only reads a value back and asserts what it just read. `test/` falls on both sides: the machinery a tier runs on is program code and gets six, conftest fixtures included, because it can make a whole layer report the wrong answer and a unit tier can usually reach it; the assertions themselves get two, since asking why the unit tests did not catch a defective unit test answers itself. What the defect is in decides this, not what the fix touches. Write plain, ordinary English prose and use telecommunications vocabulary for the subject matter — path diversity rather than mesh degree, site rather than node. Tables where a table genuinely reads better, bullets only when enumerating things, never to break up an argument. Back claims with numbers computed from the repository's own data, and say how they were computed. Each section opens with a plain sentence saying what the thing is and what it is for before any identifier appears; "Problem" says what the code is there to do before it says what is wrong with it, and says what the defect costs within its first few lines.

An issue that offers alternatives is a question to ask, not a choice to make. Where a `Proposed Solution` says "either X or Y", stop and ask which one before editing a file, however clearly the issue leans toward one of them and even when it calls one the smaller change. The alternatives are there because the trade-off was unsettled when the issue was written, and they usually decide which workflow runs a test or what a failure will mean. #47 was solved down the branch the issue preferred, which left the delivered-design tests in a workflow that a push touching `etc/` alone never starts — so every config change still went unmeasured, which was the defect being fixed. Ask before there is a draft, because a draft turns the question into a request to approve what is already done.

Longer:
[how-issues-are-written](docs/claude/memories/how-issues-are-written.md),
[an-either-is-a-question-for-the-user](docs/claude/memories/an-either-is-a-question-for-the-user.md).

## Notes

A convention learned in a session belongs in this repository: a paragraph
in this file and a topic file under `docs/claude/memories/`, linked from
both indexes. The session tool's local memory directory is one machine's
unversioned files, and a rule kept in both places drifts with nothing to
signal it, which is why the local copies were deleted on 2026-07-29. Keep
there only what is true of that machine alone.
