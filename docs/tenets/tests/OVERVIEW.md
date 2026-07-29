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
- [General Tenets](#general-tenets)
  - [Cover Every Tier the Change Touches](#cover-every-tier-the-change-touches)
  - [Tests Mirror the Code They Cover](#tests-mirror-the-code-they-cover)
  - [Shared Code Sits as High as It Applies](#shared-code-sits-as-high-as-it-applies)
  - [Check Before You Create](#check-before-you-create)
  - [Enforcement Is Mechanical](#enforcement-is-mechanical)
  - [Nothing Runs Before What It Presumes](#nothing-runs-before-what-it-presumes)

## Test Tiers

There are four tiers, separated by what a test may touch and by when it
becomes possible to run. Each name links to that tier's own tenets.

| Tier | The question it answers | What it may touch | What it needs before it can run |
| --- | --- | --- | --- |
| [Unit](UNIT_TESTS.md) | Is this unit correct on its own | Nothing external | Nothing |
| [Pre-deployment integration](PRE_DEPLOYMENT_INTEGRATION_TESTS.md) | Can this change be deployed | Live state, read only | Credentials |
| [Post-deployment integration](POST_DEPLOYMENT_INTEGRATION_TESTS.md) | Did the deployment succeed | What it just created | A deployment |
| [End to end](E2E_TESTS.md) | Does the whole entrypoint behave | A local double | Nothing |

## General Tenets

These hold in every tier. Where a tier's own document says more, it says
it about the tier, never instead of what is here.

### Cover Every Tier the Change Touches

Unit tests alone are never sufficient.

The tiers are cumulative, not alternatives. A change that adds a
coupling between two files owes a contract test. A change that adds a
deployed resource owes existence, configuration and wiring. A change to
an entrypoint's own plumbing owes a journey. Passing one tier says
nothing about the question another tier asks.

The converse is equally binding: do not answer a cheap question in an
expensive tier. If a test would pass with every collaborator replaced by
a literal, it is a unit test wherever it currently sits.

### Tests Mirror the Code They Cover

A test's location is derived, never invented. It follows the structure
of the code under test, and the tier is the last thing its path names.

Two things depend on this. A reader who knows where the code lives knows
where its tests live, without searching. And the tests a change
implicates are computable from the paths it touches alone, without
understanding the change, which is what makes it possible to hold a
change to exactly the checks that concern it and no others.

Do not group tests by behaviour. A file collecting the happy paths and
another collecting the error cases hide which unit broke, and the unit
is the diagnostic.

### Shared Code Sits as High as It Applies

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

### Check Before You Create

Before writing a fixture, helper or double, look for the one that
already exists: first in the enclosing scopes, then among the shared
helpers.

Each thing has one definition, and a second copy of it is a defect, in
tests as much as in the code they cover. The copies drift. A test
standing on the stale one passes while what it claims to cover is
broken, which is worse than having no test at all.

There is no amount of this that is harmless. A copy is a copy at one
line as much as at fifty, and one written to be temporary is still the
one that drifts.

### Enforcement Is Mechanical

Any rule here that a machine can decide must be decided by one, and
decided before anything that would rely on it. A rule that holds only
while someone is watching for it does not hold.

A rule that can be set aside where it is inconvenient is not being
applied, it is being negotiated, and it stops predicting anything about
the code it governs. When a rule objects, what changes is the code.

### Nothing Runs Before What It Presumes

Nothing runs before what it presumes has been decided, and of the things
that may run, the one depending on least runs first.

That is a single rule, and it settles every question of order without
anyone choosing one. A check that reads the code presumes nothing, so
nothing may precede it. Unit tests presume the code survived being read.
Pre-deployment integration presumes the units are correct and must
precede the deployment it is asked about, which in turn presumes
everything knowable without it is known. Post-deployment integration
presumes a deployment, so nothing it asserts can be known sooner.

Cost follows from the same rule and does not compete with it. A tier
that needs credentials or a live environment cannot be required of every
change; a tier that needs neither must be, because no change may wait on
an expensive answer that a cheap one already gave.
