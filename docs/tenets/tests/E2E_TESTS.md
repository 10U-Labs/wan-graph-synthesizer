# E2E Test Tenets

These are the non-negotiable rules for end-to-end tests: the tier that makes a caller's journey against what was actually deployed, and judges it on what the caller receives.

Every tier below it reports what the program says about itself. A unit returns a value, and the platform describes the thing it was told to create. This tier reports what the outside world gets, which is the only account of the program a caller ever sees, and the two accounts are not the same account.

## Table of Contents

- [Top of the Pyramid](#top-of-the-pyramid)
- [Safe Where It Runs](#safe-where-it-runs)
- [Test the Full Path](#test-the-full-path)
- [Judge on What the Caller Receives](#judge-on-what-the-caller-receives)
- [Last Line of Defense, Not First](#last-line-of-defense-not-first)
- [Cover the Failure Path](#cover-the-failure-path)
- [Wait Only Against a Deadline](#wait-only-against-a-deadline)
- [Document the Journey](#document-the-journey)
- [One File Per Entrypoint](#one-file-per-entrypoint)
- [One Test's Traffic Never Satisfies Another's Assertion](#one-tests-traffic-never-satisfies-anothers-assertion)
- [Where the Tier Runs](#where-the-tier-runs)
- [A Journey With the Far End Replaced](#a-journey-with-the-far-end-replaced)
- [Boundary with the Deployed Tiers](#boundary-with-the-deployed-tiers)
- [Quick Reference](#quick-reference)

## Top of the Pyramid

End-to-end tests are few, and each one stands for a journey that leaves the program unusable to its callers when it breaks: the request arrives, the work it asks for is done, and what comes back is what the caller was promised.

These are the most expensive tests there are. They are slow, they run against a live environment with everything that implies, and they can fail for reasons that are outside the program entirely. The cost is what keeps the tier small. It gains the one thing no cheaper tier can give: that the deployed program serves the caller it was deployed for.

An edge case in a parser is not a journey. It is cheaper, clearer and
faster to diagnose as a unit test, and putting it here gains nothing but
runtime.

## Safe Where It Runs

There is no environment held aside for this tier to break. It runs against the deployment its callers use, so every test in it takes one of three forms.

It inspects and creates nothing. Or it carries a flag the program honours by doing the whole journey and stopping short of the lasting effect at the end of it. Or it creates the smallest thing that will serve and takes that thing away again.

Whatever a test creates, it removes on the way out, on the failing path as well as the passing one, and a cleanup that fails fails the test. A swallowed cleanup failure leaves the thing behind, where it costs money for as long as it exists and where the next run finds it sitting in the way and reports something that has nothing to do with the change under test.

A journey that fits none of the three forms is not one this tier declines to cover. It is a journey no caller can make either, and the program is what changes.

## Test the Full Path

Enter where the caller enters and let the request travel the whole way, across every hop between the entrance and the part that finally does the work.

Reaching in partway along — invoking the far part directly, handing it the message the hop before it would have sent — skips the hops it stands in for, and those hops are the whole of what this tier covers. A test that starts halfway along the path is an integration test wearing this tier's name, and it goes on passing on the day the first hop stops delivering.

Let a failure surface as an assertion on what came back rather than as an exception from the harness, so the report names the journey rather than the line that raised.

## Judge on What the Caller Receives

The tier below asks the platform whether it did what it was told. This tier asks the caller what it got.

The two answers come apart more often than they look as though they could. The platform reports a name recorded, an address configured, a permission granted, and every one of those reports is true, while the caller cannot resolve the name, reach the address or use the permission. A configuration is a statement of intent, and confirming that the intent was recorded is all the tier below can ever do.

One question decides where an assertion belongs. If the platform reports the thing correct, could a caller still fail on it? If it could, this tier answers by being the caller. If it could not, the platform's own account settles it and the assertion belongs one tier down.

Do not reach inside the program for internal state. If an internal value needs asserting, that is a unit test over the code that owns it.

## Last Line of Defense, Not First

If an end-to-end test catches something a unit test could have caught,
the unit tests have a gap, and the gap is the bug to fix.

| Issue | Should be caught by |
| --- | --- |
| A parsing error in one unit | Unit |
| A malformed request body | Unit |
| Two units disagreeing | Integration, pre-deployment |
| A resource missing or carrying the wrong settings | Integration, post-deployment |
| A request that never arrives | End to end |
| Work lost between two deployed parts | End to end |
| A name the platform holds and the world cannot resolve | End to end |
| A published result no caller can use | End to end |

The tier's value is what only a caller sees: that the hops between the deployed parts carry traffic in the direction they were declared to carry it, that what the platform has recorded has reached the world outside it, and that the answer at the end of the journey is the one the caller was promised.

## Cover the Failure Path

A tier that covers only success proves the program runs, not that it reports.

Ask for something the program must refuse, or for a journey it cannot complete, and assert that what comes back says so in terms the caller can act on. A program that reports success when the work behind the report did not happen is worse than one that fails outright, because everything relying on the report proceeds.

## Wait Only Against a Deadline

A journey the caller waits through is asserted at once. No retry loop, no polling, no sleep: the answer is either there when the call returns or the journey failed.

Not every journey is that shape. Where what the caller receives is produced by a run this test does not control, the test may wait for it, and what makes the wait a test rather than a hope is a deadline. Set it to when the run is expected to have finished, say in the test what is being waited for and why the deadline is the length it is, and fail when it passes.

A deadline lengthened because a run was flaky has stopped measuring anything. The wait is then covering for the defect the tier exists to report, and what it produces — green, eventually — is worse than a failure, because everything downstream of the report proceeds on it.

## Document the Journey

Each test's description states the journey and the failure it stands
for, in one sentence. The tier is small enough that every test earns
one.

## One File Per Entrypoint

One test file per entrypoint, named for the entrypoint.

Do not split by journey type. The entrypoint is the subject, and a tier
with a handful of tests per entrypoint has nothing to gain from further
division.

## One Test's Traffic Never Satisfies Another's Assertion

Each test asserts on what its own journey produced, and on nothing else.

A live environment gives this for free to nobody. Everything is shared, other runs are in flight, and yesterday's traffic is still there. So mark what a test sends with something that identifies the test, and assert against that mark rather than against a count, a most recent entry, or any value another run could have put there. A test that passes because something else happened to be running at the same time is not reporting on the program.

## Where the Tier Runs

The tier runs after the deployment, and after the tier that inspects it.

Nothing is asked of a caller's journey until the platform has said the deployment succeeded, because a failure the tier below can name as a missing resource or a wrong setting is worth more than the same failure arriving as a journey that did not work. And the tier is required of every change that deploys: a change that reaches a live environment is not verified until something has used it the way a caller does.

## A Journey With the Far End Replaced

A test that drives an entrypoint with the far end replaced by a double belongs to [PRE_DEPLOYMENT_INTEGRATION_TESTS.md](PRE_DEPLOYMENT_INTEGRATION_TESTS.md).

It is worth having and it covers real wiring, but nothing it exercises was deployed, so it cannot answer the question this tier asks and it must not stand in for an answer. Several real units driven against each other before a deployment is the tier below, whichever entrypoint they are entered through.

## Boundary with the Deployed Tiers

| Integration, post-deployment | End to end |
| --- | --- |
| The resource exists | A request reaches it |
| Its settings are right | The journey it serves completes |
| Its permissions are attached | The permission works in use |
| The platform reports it correct | The caller gets what was promised |

## Quick Reference

| To test | Tier |
| --- | --- |
| A function's return value | Unit |
| A request body's shape | Unit |
| Two units agreeing | Integration, pre-deployment |
| An entrypoint driven against a local double | Integration, pre-deployment |
| A live resource's settings | Integration, post-deployment |
| What a caller receives from the deployed program | End to end |
| A journey crossing more than one deployed part | End to end |
