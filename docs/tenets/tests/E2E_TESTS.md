# E2E Test Tenets

These are the non-negotiable rules for end-to-end tests: the tier that
drives a real entrypoint the way its caller does.

An entrypoint is something a person or another system invokes directly.
Anything reached only through deployed infrastructure is covered by
[POST_DEPLOYMENT_INTEGRATION_TESTS.md](POST_DEPLOYMENT_INTEGRATION_TESTS.md)
instead.

## Table of Contents

- [Top of the Pyramid](#top-of-the-pyramid)
- [Hermetic by Construction](#hermetic-by-construction)
- [Run the Real Entrypoint](#run-the-real-entrypoint)
- [Assert on Observable Outcomes](#assert-on-observable-outcomes)
- [Last Line of Defense, Not First](#last-line-of-defense-not-first)
- [Cover the Failure Path](#cover-the-failure-path)
- [Never Wait](#never-wait)
- [Document the Journey](#document-the-journey)
- [One File Per Entrypoint](#one-file-per-entrypoint)
- [A Fresh Double Per Test](#a-fresh-double-per-test)
- [Where the Tier Runs](#where-the-tier-runs)
- [Boundary with the Deployed Tiers](#boundary-with-the-deployed-tiers)
- [Quick Reference](#quick-reference)

## Top of the Pyramid

End-to-end tests are few, and each one stands for a journey that makes
the entrypoint unusable when it breaks: it runs, it does what it is for,
it reports when the far end fails.

An edge case in a parser is not a journey. It is cheaper, clearer and
faster to diagnose as a unit test, and putting it here buys nothing but
runtime.

## Hermetic by Construction

An end-to-end test touches no live resource, sends nothing off the
machine, and costs nothing to run.

Replace the far end at the boundary the entrypoint itself speaks to, and
keep everything on this side of that boundary real: the real code, the
real argument handling, the real committed inputs. A double placed
anywhere further in stops the test from covering the wiring this tier
exists for.

There is no test against a staging environment and none against
production. If a journey can only be exercised against live
infrastructure, it is not an end-to-end test: either it becomes an
inspection in the post-deployment tier, or it does not exist.

That rule is what makes the tier free to run on every change, including
changes that never touch credentials.

## Run the Real Entrypoint

Invoke the entrypoint the way its caller does, through the same boundary,
in its own process where the caller would use one.

Calling a function inside the entrypoint instead skips the argument
handling, the entrypoint resolution and the exit status — three of the
things this tier exists to cover. Let a failure surface as an assertion
on the result rather than as an exception from the harness, so the report
names the journey.

## Assert on Observable Outcomes

Assert what the outside world sees: the status the entrypoint reports,
and what reached the far end.

Do not reach inside the process for internal state. If an internal value
needs asserting, that is a unit test over the code that owns it.

## Last Line of Defense, Not First

If an end-to-end test catches something a unit test could have caught,
the unit tests have a gap, and the gap is the bug to fix.

| Issue | Should be caught by |
| --- | --- |
| A parsing error in one unit | Unit |
| A malformed request body | Unit |
| Two units disagreeing | Integration |
| A wrong entrypoint name | End to end |
| An unhandled failure status | End to end |
| A missing runtime path or dependency | End to end |

The tier's value is the wiring nothing else sees: resolution, argument
handling, exit status, and the fact that the real inputs in the
repository are still readable by the real code.

## Cover the Failure Path

A tier that covers only success proves the entrypoint runs, not that it
reports.

Drive the far end to fail and assert that the entrypoint says so. An
entrypoint that reports success after every write failed is worse than
one that crashes, because a pipeline gating on it goes green.

## Never Wait

The far end is a local double, so a correct run is immediate.

No retry loops, no polling, no sleeps. There is no eventual consistency
behind a double, so a test that waits is waiting for something this tier
does not have. If a wait seems necessary, the double is wrong, not the
timeout.

## Document the Journey

Each test's description states the journey and the failure it stands
for, in one sentence. The tier is small enough that every test earns
one.

## One File Per Entrypoint

One test file per entrypoint, named for the entrypoint.

Do not split by journey type. The entrypoint is the subject, and a tier
with a handful of tests per entrypoint has nothing to gain from further
division.

## A Fresh Double Per Test

The double is created per test, not shared across the file.

Each test gets a double with an empty record of what reached it, so one
test's traffic cannot satisfy another's assertion. A test that needs
different far-end behaviour builds its own rather than adding a
parameter to the shared one.

Whatever creates the double tears it down on the way out, on the failing
path as well as the passing one.

## Where the Tier Runs

The tier runs after the cheaper tiers and before anything that writes to
a live environment.

That order is the whole reason it is worth its cost: whatever is about
to write to production has just been run start to finish against a
double. Because the tier is hermetic it needs no credentials, so unlike
the deployment tiers it can gate every change rather than only the ones
that reach a real environment.

## Boundary with the Deployed Tiers

| Post-deployment integration | End to end |
| --- | --- |
| The resource exists | The entrypoint runs |
| Its settings are right | Its status is right |
| Its permissions are attached | Its requests arrive |
| The platform reports it correct | The process behaves |

## Quick Reference

| To test | Tier |
| --- | --- |
| A function's return value | Unit |
| A request body's shape | Unit |
| Two units agreeing | Integration |
| The status an entrypoint reports | End to end |
| What an entrypoint sends | End to end |
| A live resource's settings | Post-deployment |
