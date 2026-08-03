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
  - [Nothing Is Trusted Before What It Presumes](#nothing-is-trusted-before-what-it-presumes)

## Test Tiers

There are three kinds of test, separated by how much of the program each one exercises: one unit, several units against each other, and the journey a caller makes. Integration comes in two halves because the program is deployed, and a unit in the repository and the deployed instance of that unit are different things to exercise. Each name links to that tier's own tenets.

| Tier | The question it answers |
| --- | --- |
| [Unit](UNIT_TESTS.md) | Is this unit correct on its own |
| [Integration, pre-deployment](PRE_DEPLOYMENT_INTEGRATION_TESTS.md) | Can this be deployed |
| [Integration, post-deployment](POST_DEPLOYMENT_INTEGRATION_TESTS.md) | Did the deployment succeed |
| [End to end](E2E_TESTS.md) | Does the journey work for the caller |

How much of the program a test exercises is the only thing that separates them. What a test may touch and what it needs before it can run follow from that and decide nothing: a tier is not defined by its cost, and naming the cost as the boundary is how a tier ends up exercising less of the program than the one below it.

## General Tenets

These hold in every tier. Where a tier's own document says more, it says
it about the tier, never instead of what is here.

### Cover Every Tier the Change Touches

Unit tests alone are never sufficient.

The tiers are cumulative, not alternatives. A change that adds a
coupling between two files owes a contract test. A change that adds a
deployed resource owes existence, configuration and wiring. A change to
what a caller receives owes a journey against the deployment. Passing
one tier says nothing about the question another tier asks.

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

### Nothing Is Trusted Before What It Presumes

An answer is worth no more than what it presumes. A pass resting on a presumption that turns out false is not a pass; it is an answer to a question nobody asked, and reading it as one is how a suite reports sound while the thing under it is broken.

The rule governs what a result may be taken to mean. It does not, on its own, govern what may be attempted at the same time. Two kinds of presumption sit behind that, and they differ in what they cost to ignore.

A tier may presume something exists. Post-deployment integration presumes a deployment, and end to end presumes one as well and asks what the caller receives from it. Without that deployment there is nothing to call, so neither can be attempted sooner, and here the presumption does fix when the tier runs. End to end runs last of all, after every tier that could have named the failure more precisely.

A tier may instead presume something is correct. Unit tests presume the code survived being read; pre-deployment integration presumes the units are correct. Everything these need is in hand from the start, so nothing stops them being attempted at once, and attempting them at once is usually cheaper and tells the author more in one go. What their presumption fixes is the reading, not the running: a green unit tier over code that failed the checks which read it has established nothing, and must be reported and treated as unestablished rather than as a pass. Run them together; do not believe the one whose presumption failed.

The rest of the rule is diagnostic. Of the results in hand, the one presuming least is the one that names the defect, and those presuming more are its consequences. When several fail together, read the failure that presumed least; the others say only that they stood on it. This is why a thing shared by many tiers is checked as its own subject rather than as a step inside its consumers — when it breaks, the result that names it must exist, or every tier that used it reports a defect of its own that it does not have.

Cost follows from the same rule and does not compete with it. A tier that presumes a deployment cannot be required of a change that deploys nothing; a tier that presumes only the code must be required of every change, because no change may wait on an expensive answer that a cheap one already gave. That is a consequence of what each tier presumes and not a second rule set beside it. Where cost is allowed to decide what a tier may exercise, the tier stops answering its question, and the cheap answer it gives instead is mistaken for the expensive one nobody asked for.
