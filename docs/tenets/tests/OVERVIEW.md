# Test Tenets Overview

These are the tenets the tests are held to. They say which tiers a
change must cover, where a test is placed relative to the code it
covers, and how the rules are enforced.

No tenet here names a language, a tool, a directory or a resource. The
repository is the source of truth for all of those, and a tenet that
restated them would be a copy that drifts. A tenet holds after the
stack is rewritten; if a sentence would not, it does not belong here.

## Table of Contents

- [Test Tiers](#test-tiers)
- [Cover Every Tier the Change Touches](#cover-every-tier-the-change-touches)
- [Tests Mirror the Code They Cover](#tests-mirror-the-code-they-cover)
- [Shared Code Sits as High as It Applies](#shared-code-sits-as-high-as-it-applies)
- [Check Before You Create](#check-before-you-create)
- [Enforcement Is Mechanical](#enforcement-is-mechanical)
- [The Order of the Gates](#the-order-of-the-gates)

## Test Tiers

There are four tiers, separated by what a test may touch, which is also
what decides when it becomes possible to run. Each links to its tenets.

| Tier | The question it answers | What it may touch |
| --- | --- | --- |
| [Unit][unit] | Is this unit correct alone | Nothing external |
| [Pre-deployment][pre] | Can this be deployed | Live state, read only |
| [Post-deployment][post] | Did the deployment succeed | What it created |
| [End to end][e2e] | Does the entrypoint behave | A local double |

[unit]: UNIT_TESTS.md
[pre]: PRE_DEPLOYMENT_INTEGRATION_TESTS.md
[post]: POST_DEPLOYMENT_INTEGRATION_TESTS.md
[e2e]: E2E_TESTS.md

## Cover Every Tier the Change Touches

Unit tests alone are never sufficient.

The tiers are cumulative, not alternatives. A change that adds a
coupling between two files owes a contract test. A change that adds a
deployed resource owes existence, configuration and wiring. A change to
an entrypoint's own plumbing owes a journey. Passing one tier says
nothing about the question another tier asks.

The converse is equally binding: do not answer a cheap question in an
expensive tier. If a test would pass with every collaborator replaced by
a literal, it is a unit test wherever it currently sits.

## Tests Mirror the Code They Cover

A test's location is derived, never invented. It follows the structure
of the code under test, and the tier is the last thing its path names.

Two things depend on this. A reader who knows where the code lives
knows where its tests live, without searching. And any pipeline that
selects work by path can tell which tests a change implicates, which is
what makes it possible to gate a change on exactly the checks it
affects.

Do not group tests by behaviour. A file collecting the happy paths and
another collecting the error cases hide which unit broke, and the unit
is the diagnostic.

## Shared Code Sits as High as It Applies

Put shared setup at the highest scope where it applies, and no higher.

What every test needs is declared once for the whole suite. What one
subsystem needs is declared with that subsystem. What one tier needs is
declared with that tier. Setup local to a single file stays in that
file.

Both errors cost. Lifting a fixture above its real audience gives it
consumers nobody can enumerate, so it can no longer be changed safely.
Leaving it below its real audience guarantees a copy.

The same rule decides ownership. A helper any consumer of the codebase
could use belongs with the shared code. A helper that only one
subsystem's tests could use never does, however tempting the shelf.

## Check Before You Create

Before writing a fixture, helper or double, look for the one that
already exists: first in the enclosing scopes, then among the shared
helpers.

Duplication is not merely discouraged, it fails the build. A
copy-paste gate runs at a zero-tolerance threshold over source and
tests alike, so a copied fixture is a red run rather than a review
comment.

## Enforcement Is Mechanical

Every tenet that a machine can check is checked by one, and the check
runs before the tests do. A rule enforced by review is a rule that
holds until the reviewer is busy.

Suppression is not available. A per-line directive that silences a
finding fails a gate of its own, and so does a configuration file that
would relax a rule across the tree. There is no tolerance band on the
static analysis and no partial credit on coverage. When a gate objects,
the answer is to change the code.

## The Order of the Gates

Stages run cheapest and most local first, and each presumes the one
before it passed.

```text
static analysis
  └── unit tests
        └── pre-deployment integration tests
              └── deployment
                    └── post-deployment integration tests
```

- Static analysis depends on nothing, so it gives the fastest feedback.
- Unit tests run behind it, because there is no point testing code that
  does not lint. They carry the coverage gate.
- Pre-deployment integration runs immediately before the deployment and
  changes nothing itself.
- The deployment runs only once everything knowable without it is
  known.
- Post-deployment integration runs last, because there is nothing live
  to inspect until then.

A tier that needs credentials or a deployed environment cannot run on
every push. The tiers that need neither must, so the checks a
contributor gets for free arrive first.

One change may fire several pipelines. It is done when every pipeline
that fired is green, not when the first one is.
