# Read the test tenets first

Before implementing a change, read `docs/tenets/tests/` — `OVERVIEW.md`,
`UNIT_TESTS.md`, `PRE_DEPLOYMENT_INTEGRATION_TESTS.md`,
`POST_DEPLOYMENT_INTEGRATION_TESTS.md` and `E2E_TESTS.md`. They define a
strict hierarchy the repository enforces: `pre_deployment/{unit,integration}`
and `post_deployment/integration`, with the synthesizer's in-process
full-synthesis tier at
`test/api/endpoints/tenants/wan/synthesizer/pre_deployment/integration/`.

Unit tests alone are not sufficient. Add coverage at every tier the change
touches. One assert per pytest — an `assert-one-assert-per-pytest` check
enforces it in CI.

On 2026-07-01 a feature shipped with unit tests only, the tenets having
gone unread. It turned CI red and missed a required tier, and the user's
rebuke was "did you read docs/tenets/tests/?". Reading them is the first
step of the work, not a check performed afterwards; pair it with
[tdd-workflow](tdd-workflow.md), which decides when the tests get written.
