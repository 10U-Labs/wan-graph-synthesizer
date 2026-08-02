# Pre-Deployment Integration Test Tenets

These are the non-negotiable rules for pre-deployment integration tests:
the tier that runs before anything is deployed.

Pre-deployment tests answer one question. Can this change be deployed.
Post-deployment tests answer the other. Did the deployment succeed.

## Table of Contents

- [Two Kinds of Test](#two-kinds-of-test)
- [The Seven-Layer Model](#the-seven-layer-model)
- [One File Per Layer](#one-file-per-layer)
- [Layer 1, Contracts](#layer-1-contracts)
- [Layer 2, Authentication](#layer-2-authentication)
- [Layer 3, Authorization](#layer-3-authorization)
- [Layer 4, State](#layer-4-state)
- [Layer 5, Existence](#layer-5-existence)
- [Layer 6, Configuration](#layer-6-configuration)
- [Layer 7, Capability](#layer-7-capability)
- [The Tests That Carry No Layer](#the-tests-that-carry-no-layer)
- [Read Only Everywhere But Layer 7](#read-only-everywhere-but-layer-7)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Shared Setup Is Declared, Not Rebuilt](#shared-setup-is-declared-not-rebuilt)
- [Why a Dry Run Is Not a Gate](#why-a-dry-run-is-not-a-gate)
- [Quick Reference](#quick-reference)

## Two Kinds of Test

### Contract tests

Verify that files which must agree with each other do agree. Nothing
remote is touched.

- Do test: every reference to a value another unit declares resolves to
  something that unit actually declares.
- Do test: what this unit publishes is wired to the thing it claims.
- Do test: a reference to state another unit owns points at that unit.
- Do NOT test: the structure of a single file on its own. Parsing one
  file is a unit test.

### Prerequisite tests

Verify that the credentials, the state and the prerequisites this
deployment depends on are sound.

- Do test: credentials exist and resolve to an identity.
- Do test: those credentials may inspect what the deployment must read.
- Do test: nothing the deployment would create already exists untracked.
- Do test: what another deployment created and this one depends on is
  there, is as this deployment needs it, and can be used the way this
  deployment will use it.
- Do NOT test: what this deployment is about to create. It does not
  exist yet, and asserting on it belongs to the post-deployment tier.

## The Seven-Layer Model

Every deployable unit passes through seven layers, in order.

| Layer | The question it answers |
| --- | --- |
| 1. Contracts | Do the local files agree |
| 2. Authentication | Are the credentials valid |
| 3. Authorization | May they inspect what is needed |
| 4. State | Does declared state match the world |
| 5. Existence | Is the prerequisite there |
| 6. Configuration | Is it as this deployment needs it |
| 7. Capability | Can this deployment use it |

Each layer isolates a different failure.

- Layer 1 fails: two files disagree, and no deployment would fix it.
- Layer 2 fails: credentials are missing or expired.
- Layer 3 fails: credentials are valid but may not look.
- Layer 4 fails: something exists outside tracked state, so the
  deployment would collide with it.
- Layer 5 fails: the look was permitted and the prerequisite is not
  there, so the deployment that owns it has not run or did not finish.
- Layer 6 fails: the prerequisite is there and carries settings this
  deployment cannot work against.
- Layer 7 fails: the prerequisite is there and right, and this
  deployment cannot perform the operation it will have to perform.

The order is the diagnostic. Each layer presumes its predecessors
passed, so the first failure names the stage, and a layer never
re-establishes what an earlier one settled.

Layers 5 to 7 are about what another deployment created, never about what this deployment is about to create. Whatever this unit creates cannot be inspected before it runs, and asking after it belongs to [POST_DEPLOYMENT_INTEGRATION_TESTS.md](POST_DEPLOYMENT_INTEGRATION_TESTS.md). What separates the two is ownership and not the question: existence, configuration and capability are asked here of the ground the deployment lands on, and there of the ground it laid.

A prerequisite is not a hypothetical. Units that deploy independently depend on each other's resources, and the deployment that owns a thing can be behind the deployment that needs it. That failure looks like a defect in the code of whichever unit ran second, and it is not; these three layers are what tell the two apart before either has run.

## One File Per Layer

The layers are separated into one file each, ordered so that the layer
is visible in the name and the files run in layer order.

Do not organise by resource. A file per service makes it impossible to
see which layer broke, which is the entire point of the ordering.

## Layer 1, Contracts

Cross-file consistency, asserted against the declaration rather than a
copied literal.

This is the only layer most units write by hand, and the only one that
grows when a unit gains a coupling. Read the value from the same place
the code reads it: a test that copies the literal passes while the two
files drift apart, which is the failure this layer exists to catch.

An assertion that reads one file is not a contract test, whatever it
asserts. It belongs in the unit tier.

## Layer 2, Authentication

Credentials only. Nothing about permissions and nothing about
resources.

Every unit's authentication layer asks the same question, so no unit
writes its own. It takes the shared one, which is both what forbids the
copy and what keeps the answer identical everywhere.

Asking whether a call is permitted is an authorization test, not an
authentication one, and belongs one layer down.

## Layer 3, Authorization

Permission to inspect, not the existence of what is inspected.

The distinction is worth stating precisely, because the two outcomes
look alike from a distance. A permission denial fails the layer, because
the credentials may not look. A not-found passes it, because the call
was allowed and the thing simply is not there yet. Absence is the
post-deployment tier's business.

## Layer 4, State

Confirm that nothing the deployment would create already exists outside
the state it tracks.

Derive the answer from the deployment tool's own dry run rather than
from a hand-written list of resources, so the check cannot fall behind
the declaration. Then ask the platform about each thing the dry run
would create, and fail naming the ones that are already there.

A skip for cold state is required, not optional. A unit that has never
been deployed has no tracked state to compare against, and without the
skip its first run fails on a condition that cannot yet be true.

This layer inspects and computes. It never deploys.

## Layer 5, Existence

The prerequisite is there, presuming permission to look was settled one layer up.

Ask the platform for each thing another deployment owns and this one depends on, under the name the declaration gives it, and assert that it is there. Nothing about its settings belongs in this layer, however much of them the answer happens to carry.

Layer 3 passed on a not-found because the call was allowed. This is the layer where a not-found is a failure, and the difference between the two is what makes the report worth reading: permission and absence are different problems, owned by different people.

## Layer 6, Configuration

The prerequisite is as this deployment needs it, presuming existence has passed.

Do not fetch a thing again to prove it is there before reading a setting off it. Existence was the previous layer's assertion, and repeating it here is a second assertion in disguise.

Assert only the settings this deployment depends on. Everything else about a prerequisite is the business of the unit that owns it, and asserting on it here fails this unit's tests for a change it has no stake in.

## Layer 7, Capability

This deployment can perform the operations it will need, presuming configuration has passed.

Permission to inspect is not permission to act, and the two are granted separately. A deployment that can read every prerequisite it depends on and cannot write where it must write fails halfway through, having already changed some of what it was going to change. This layer is what moves that failure to before the deployment, where nothing has been changed yet.

Exercise the operation itself rather than reading back the permission that ought to allow it. A granted permission is a statement about intent; performing the operation is the only thing that settles whether the intent holds.

## The Tests That Carry No Layer

Several real units exercised against each other, before anything is deployed, is what this tier is. Two kinds of test are exactly that and carry no layer number. The reason is not that they count for less: the numbered chain is what a deployable unit passes through on its way to being deployed, and these two answer a question about the code rather than about the deployment.

The first is behavioural. Where the code is pure logic, exercise the units against each other with nothing remote and no declaration involved, and name the test for the behaviour it exercises rather than for a layer. Keep the boundary with the unit tier sharp: if the test would still pass with every collaborating unit replaced by a literal, it is a unit test.

The second is a journey with the far end replaced. Enter where a caller would enter, keep everything on this side of that boundary real — the real argument handling, the real committed inputs, the real code — and replace only what the entrypoint speaks to at the far end. Name it for the entrypoint. A double placed further in than the boundary stops the test covering the wiring it exists for, and a correct run behind a double is immediate, so a test of this shape never waits.

A journey of that kind covers wiring no unit test sees, and it is still several real units against each other with nothing deployed, which is why it sits here. It may never stand in for the question [E2E_TESTS.md](E2E_TESTS.md) asks, which is what a caller receives from the deployed program.

## Read Only Everywhere But Layer 7

Layers 1 to 6 inspect. They never create, mutate or delete anything remote, and they leave no artifact behind.

A write in those layers would defeat layer 4, which exists precisely to prove that nothing untracked is sitting where the deployment is about to land. A test that puts something there and a test that reports what it found there cannot both be trusted in the same tier.

Layer 7 is the exception the tier is built to contain, because an operation is only proved by being performed. It writes the smallest thing that proves the operation, in a place the deployment itself would write, and it removes that thing on the way out — on the failing path as well as the passing one, with the failure of the removal failing the test. What is left behind is exactly what layer 4 is looking for on the next run, so a swallowed cleanup failure here reappears as a collision the deployment did not cause.

## Fail Fast with Granular Diagnostics

A failure reading `access denied` and nothing else is not acceptable
diagnostics.

- One assertion per test.
- Layers run in order, so the first failure names the stage.
- A failure message carries the name of the thing and the expected
  value.
- A check that fails deliberately inside a helper reports the name it
  was checking, rather than letting a bare exception surface.

## Shared Setup Is Declared, Not Rebuilt

A tier's shared setup exposes what the tier needs and constructs
nothing that a wider scope already constructs.

Names derived from the declaration are derived once, at the scope every
tier of that unit can see, and each tier takes them from there. Deriving
them a second time inside a tier is the copy this tier is meant to
prevent.

## Why a Dry Run Is Not a Gate

A bare dry run is not a substitute for layer 4.

A dry run prints a difference. A difference decides nothing: it is read
if someone is watching and ignored otherwise, so it cannot stop a
deployment. Layer 4 consumes the same dry run and asserts on it, which
turns the same information into a result that can fail. Nothing else in
the tier can answer the question layer 4 answers: that the deployment
will not collide with something untracked.

## Quick Reference

| To test | Layer |
| --- | --- |
| Cross-file agreement | 1 |
| A published value wired to its source | 1 |
| A reference to another unit's state | 1 |
| Credentials resolve | 2 |
| Permission to inspect | 3 |
| Nothing untracked in the way | 4 |
| A prerequisite another deployment owns is there | 5 |
| Its settings are what this deployment needs | 6 |
| An operation this deployment will perform | 7 |
| Several units against each other | No layer |
| An entrypoint driven against a local double | No layer |
| A resource this deployment creates | Post-deployment |
| What a caller receives from the deployed program | End to end |
