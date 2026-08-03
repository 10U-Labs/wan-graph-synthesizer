# An either in a proposed solution is a question, not a choice to make

When an issue's `Proposed Solution` offers alternatives — "either X or Y" — stop and ask which one before writing anything. Do not pick, however clearly the issue leans, and do not treat the issue's own preference as the answer. The alternatives are in the issue because the trade-off was not settled when it was written, and settling it is the user's call.

This is not a style preference. The two branches of an either usually differ in which workflow runs a test, which resource a change touches, or what a failure will mean, and those are the questions the issue exists to answer. Choosing one silently spends the user's decision and then buries it in a commit message, where it is found after the work is done and has to be undone.

Issue #47 is the incident. Its `Proposed Solution` opened by saying the delivered-design tests should move into `.github/workflows/seed.yml`, in a job needing `seeding`, and closed with "Either the deploy moves into `seed.yml` ahead of `seeding`, or `seeding` moves into `api_endpoint_tenants_wan_post.yml` after `reconciliation`. The second is the smaller change and keeps deploy and seed in one order." Those two are incompatible, and the second was taken on the strength of the issue calling it smaller.

It was the wrong one, and the reason is the whole point of the issue. A push touching `etc/` alone starts `seed.yml` and nothing else — that is the shape of every `backbone` setting change, including #46. With the tests in `api_endpoint_tenants_wan_post.yml`, that push seeded, rebuilt all five WANs, and nothing measured any of them. The fix closed the guessing hole and left the tier unreachable for exactly the pushes it exists for, and a third commit was needed to run the file now at `test/scripts/seed/post_deployment/e2e/test_delivered_designs.py` in `seed.yml` after `seeding`, where it belonged.

The division the user stated afterwards is worth keeping: tests in an endpoint's own workflow are about how that API behaves and how its deployment is shaped; whether a WAN was actually rebuilt from a change to `etc/` belongs to `seed.yml`, because `seed.yml` is the workflow that change starts. See [where-a-test-runs-follows-what-starts-it](where-a-test-runs-follows-what-starts-it.md).

Asking costs one turn. Ask before any file is edited, not after a draft exists, because a draft makes the question sound like a request for approval of what was already done.
