# Pre-Deployment Integration Test Tenets

These are the non-negotiable rules for pre-deployment integration tests:
the tier that runs before anything is deployed.

Pre-deployment tests answer one question. Can this change be deployed.
Post-deployment tests answer the other. Did the deployment succeed.

## Table of Contents

- [Two Kinds of Test](#two-kinds-of-test)
- [The Four-Layer Model](#the-four-layer-model)
- [One File Per Layer](#one-file-per-layer)
- [Layer 1, Contracts](#layer-1-contracts)
- [Layer 2, Authentication](#layer-2-authentication)
- [Layer 3, Authorization](#layer-3-authorization)
- [Layer 4, State](#layer-4-state)
- [Behavioural Integration Tests](#behavioural-integration-tests)
- [Read Only, Never Write](#read-only-never-write)
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

Verify that the credentials and the state this deployment depends on are
sound.

- Do test: credentials exist and resolve to an identity.
- Do test: those credentials may inspect what the deployment must read.
- Do test: nothing the deployment would create already exists untracked.
- Do NOT test: what this deployment is about to create. It does not
  exist yet, and asserting on it belongs to the post-deployment tier.

## The Four-Layer Model

Every deployable unit passes through four layers, in order.

| Layer | The question it answers |
| --- | --- |
| 1. Contracts | Do the local files agree |
| 2. Authentication | Are the credentials valid |
| 3. Authorization | May they inspect what is needed |
| 4. State | Does declared state match the world |

Each layer isolates a different failure.

- Layer 1 fails: two files disagree, and no deployment would fix it.
- Layer 2 fails: credentials are missing or expired.
- Layer 3 fails: credentials are valid but may not look.
- Layer 4 fails: something exists outside tracked state, so the
  deployment would collide with it.

The order is the diagnostic. Each layer presumes its predecessors
passed, so the first failure names the stage, and a layer never
re-establishes what an earlier one settled.

Existence, configuration and wiring are deliberately absent here.
Whatever this deployment creates cannot be inspected before it runs, so
those questions belong to
[POST_DEPLOYMENT_INTEGRATION_TESTS.md](POST_DEPLOYMENT_INTEGRATION_TESTS.md).
A dependency another unit owns is asserted against that unit's
declaration in layer 1, not by asking the platform at run time.

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

## Behavioural Integration Tests

Where the code is pure logic, the tier has a second kind of test:
several units exercised against each other, with nothing remote and no
declaration involved.

Name these for the behaviour they exercise, not for a layer number, and
keep them out of the numbered chain — they are not a stage every unit
passes through. Keep the boundary with the unit tier sharp: if the test
would still pass with every collaborating unit replaced by a literal, it
is a unit test.

## Read Only, Never Write

Pre-deployment tests inspect. They never create, mutate or delete
anything remote, and they leave no artifact behind.

A write here would defeat layer 4, which exists precisely to prove that
nothing untracked is sitting where the deployment is about to land. The
tier therefore has no cleanup rules, because it has nothing to clean up.

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
| A live resource's settings | Post-deployment |
| Several units against each other | Behavioural |
