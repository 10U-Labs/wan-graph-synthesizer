# Post-Deployment Integration Test Tenets

These are the non-negotiable rules for post-deployment integration
tests: the tier that inspects what the deployment just created.

## Table of Contents

- [Only What This Deployment Created](#only-what-this-deployment-created)
- [The Three-Layer Model](#the-three-layer-model)
- [One File Per Layer](#one-file-per-layer)
- [Layer 1, Existence](#layer-1-existence)
- [Layer 2, Configuration](#layer-2-configuration)
- [Layer 3, Wiring](#layer-3-wiring)
- [Assert Against the Declaration](#assert-against-the-declaration)
- [Inspect, Never Invoke](#inspect-never-invoke)
- [No Cleanup Required](#no-cleanup-required)
- [Fail Fast with Granular Diagnostics](#fail-fast-with-granular-diagnostics)
- [Fetch Once, Assert Many Times](#fetch-once-assert-many-times)
- [Quick Reference](#quick-reference)

## Only What This Deployment Created

A post-deployment test inspects what this deployment just created, and
nothing else.

- Do test: the resources this unit declares.
- Do test: their configuration, against the declaration.
- Do test: the connections between them.
- Do NOT test: resources another unit owns. Its own tests cover them,
  and asserting on them here couples two units that are otherwise
  independent, so one unit's outage turns the other's pipeline red.
- Do NOT test: application logic. That is a unit test, and it has
  already run.
- Do NOT test: anything that requires invoking something.

## The Three-Layer Model

Every deployed resource is checked through three layers, in order.

| Layer | The question it answers |
| --- | --- |
| 1. Existence | Was it created |
| 2. Configuration | Does it match the declaration |
| 3. Wiring | Is it connected to its neighbours |

Each layer isolates a different failure.

- Layer 1 fails: the deployment did not create the resource.
- Layer 2 fails: it exists but carries the wrong settings.
- Layer 3 fails: it exists and is configured, but nothing can reach it,
  or it cannot reach what it needs.

Each layer presumes its predecessors passed. Folding a setting into an
existence test means a configuration drift reports as a missing
resource, and the report is the reason the layers exist.

## One File Per Layer

The layers are separated into one file each, ordered so that the layer
is visible in the name and the files run in layer order.

Do not organise by resource. A file per service hides which layer broke,
and the layer is the diagnostic.

## Layer 1, Existence

Existence only. No settings, no connections.

Ask the platform for each declared resource under the name the
declaration gives it, and assert that it is there. Nothing else belongs
in this layer, however convenient the response makes it.

## Layer 2, Configuration

Settings only, presuming existence has passed.

Do not re-fetch a resource to prove it is there before reading a
setting. Existence was layer 1's assertion, and repeating it is a second
assertion wearing a disguise.

## Layer 3, Wiring

Connections only, presuming existence and configuration have passed.

Wiring catches what the other two layers cannot: a permission that was
never attached, an identity the resource does not actually assume, a
trigger nothing registered. A resource can exist, carry every declared
setting, and still be unreachable.

## Assert Against the Declaration

Where a value is derived rather than chosen, read it from the same place
the deployment reads it instead of copying the literal into the test.

A test that hardcodes a derived name keeps passing while the declaration
renames the resource underneath it, which is exactly the drift this tier
exists to catch.

Values the declaration itself states outright are the opposite case, and
are written as literals on purpose. Here the test is a second opinion:
derive both sides from one source and the assertion says nothing.

## Inspect, Never Invoke

If a test invokes a function, sends a request or enqueues a message, it
has left this tier.

Behaviour is covered by the tiers that own it: logic by unit tests over
the code, and whole-entrypoint journeys by
[E2E_TESTS.md](E2E_TESTS.md). Reaching for an invocation here usually
means one of those tiers has a gap, and the gap is what to fix.

The permitted calls are the read-only ones that describe a resource, its
settings and its permissions.

## No Cleanup Required

Post-deployment tests create nothing, so they clean up nothing.

- Do: read configuration.
- Do: read permissions and identity documents.
- Do NOT: write an object, a record or a message anywhere.

A test that needs cleanup is in the wrong tier. Move it.

## Fail Fast with Granular Diagnostics

- One assertion per test, enforced by a gate.
- Layers run in order, so the first failure names the stage.
- Assert the specific value, so both sides appear in the failure.
- Name the resource in the assertion, not only the attribute.

## Fetch Once, Assert Many Times

A description fetched once is shared by every layer that reads it, so
the tier costs one call per resource rather than one per test.

This is not only about cost. Tests that each fetch their own copy can
disagree about what they saw, and a tier meant to report a single
deployment's outcome then reports several.

## Quick Reference

| To test | Layer |
| --- | --- |
| A resource exists | 1 |
| An identity exists | 1 |
| A log destination exists | 1 |
| Runtime and size settings | 2 |
| Timeouts and limits | 2 |
| Injected configuration values | 2 |
| A resource assumes its identity | 3 |
| A caller may invoke it | 3 |
| An identity grants the access it needs | 3 |
| Application logic | Unit |
| An entrypoint end to end | End to end |
