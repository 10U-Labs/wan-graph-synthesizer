# Unit Test Tenets

These are the non-negotiable rules for unit tests: the tier that
exercises one unit of code with nothing external in reach.

## Table of Contents

- [The Primary Line of Defense](#the-primary-line-of-defense)
- [The Dividing Line Is Dependencies](#the-dividing-line-is-dependencies)
- [One Assert Per Test](#one-assert-per-test)
- [One Test File Per Unit of Source](#one-test-file-per-unit-of-source)
- [Complete Isolation](#complete-isolation)
- [Test Every Branch](#test-every-branch)
- [Descriptive Test Names](#descriptive-test-names)
- [Every Test Carries a Description](#every-test-carries-a-description)
- [Assertions That Explain Themselves](#assertions-that-explain-themselves)
- [No Test Interdependence](#no-test-interdependence)
- [No Duplicated Setup](#no-duplicated-setup)
- [Fast Execution](#fast-execution)
- [Held to the Standards of Source](#held-to-the-standards-of-source)
- [What Unit Tests Must Catch](#what-unit-tests-must-catch)
- [Quick Reference](#quick-reference)

## The Primary Line of Defense

Almost everything wrong should be caught by a unit test.

The pyramid puts unit tests at the base, and their count should exceed
every other tier combined. If a bug could have been caught by a unit
test and was not, that is a coverage failure, not bad luck.

```text
        /\
       /  \     End to end (few)
      /----\
     /      \   Integration (some)
    /--------\
   /          \
  /            \ Unit (many)
 /______________\
```

## The Dividing Line Is Dependencies

What makes a test a unit test is what it depends on, not whether
anything leaves the process.

Exercise one unit with every collaborator supplied as a literal or a
double, and it is a unit test. Exercise two or more real units against
each other and it is an integration test, however fast it runs and
however local it stays. Speed is a consequence of the boundary, not the
definition of it.

## One Assert Per Test

Each test verifies exactly one behaviour, with exactly one assertion.

The reason is not tidiness. A test stops at its first failed assertion,
so a second one is a fact the test claims to check and then never
reports. And a test that can fail for two reasons no longer names the
reason it failed, which is the whole of what a failure is worth.

When two facts need asserting, write two tests. Setup they share belongs
in a helper or a fixture, never in a second assertion. A helper that
asserts on the caller's behalf is a second assertion in disguise and is
worse, because the count no longer reads in the test.

Where the same single assertion applies across a set of inputs, use the
harness's parameterisation. That stays one assertion and keeps every
case named in the failure output.

## One Test File Per Unit of Source

One test file per unit of source, named for the unit it covers.

Do not organise by behaviour: there is no happy-path file and no
error-cases file. Do not cover two units from one file. Do not split one
unit's tests across several files unless the file names make the split
obvious, and prefer splitting the unit instead.

A unit with no test file of its own is a gap even when its lines are
covered incidentally by another unit's tests, because nothing then
states what that unit promises.

## Complete Isolation

A unit test has zero external dependencies.

- No network calls, including calls to a live platform.
- No file system writes, and reads only of committed inputs.
- No subprocesses.
- No environment mutation left standing when the test ends.

Reach for the suite's doubles rather than a live client, and change the
environment only through a mechanism scoped to the test, so the change
is undone whether the test passes or fails.

## Test Every Branch

Total branch coverage, with nothing exempted from it.

Every conditional, every error path, every early return and every loop
exit needs a test. A branch without a test is not merely unverified, it
is a failure of this tier, and nothing that presumes this tier may
proceed past it.

Warnings count as failures in this tier too. Code that works while
complaining is not covered, it is tolerated.

## Descriptive Test Names

The name states the subject, the condition and the expected result, so
a failure in a log is legible without opening the file.

A name that says only which unit was under test, or only that something
worked, is not acceptable. The name is the first line of the failure
report and usually the only line anyone reads.

## Every Test Carries a Description

Every test carries a written description, in the present tense, saying
what behaviour it pins.

Write the sentence the name could not fit. Describe the behaviour, not
the mechanics. Do not restate the name in prose, and do not narrate
setup the reader can see two lines below.

## Assertions That Explain Themselves

Assert the specific value, not its truthiness.

An assertion on a bare result tells the reader nothing when it fails.
Compare against the expected value so both sides appear in the failure.
Where the subject is a collection, assert the membership or the count
that matters, not that the collection is non-empty. Where the subject is
a raised error, assert its type together with the text that identifies
it, as one assertion.

## No Test Interdependence

Each test passes on its own, in any order, with no shared mutable state.

Build state inside the test, or in a fixture scoped to a single test.
State that tests write to couples them, and the coupling surfaces as an
unrelated test breaking when a new one is added — the most expensive
failure a suite can produce, because it accuses the wrong code.

Shared immutable inputs are fine, and are the right way to express a
fixture that several tests read but none change.

## No Duplicated Setup

Duplicated setup is a defect in a test exactly as it is in the code the
test covers, and no quantity of it is acceptable.

Place what you extract by scope, as
[OVERVIEW.md](OVERVIEW.md#shared-code-sits-as-high-as-it-applies)
requires: a local helper when the reuse is confined to one file, a
shared fixture when a subsystem needs it, the shared helpers when the
whole codebase does.

## Fast Execution

Unit tests are measured in milliseconds.

When one takes noticeable time the cause is almost always that it is no
longer a unit test: something is reaching the network, walking real data
at full size, or spawning a process. Move it to the tier it now belongs
in rather than accepting the cost.

## Held to the Standards of Source

Tests are subject to the same static analysis as the code they cover.

They are typed where the language has types, and they are lint-clean
under the same rules, with no lower bar for being test code. Test code
is read more often than source and changed more often than either, so a
suite exempted from its own standards decays first.

Suppressing a finding inline is not available, and neither is relaxing
the rule in configuration. Fix the code.

## What Unit Tests Must Catch

| Issue | Caught by |
| --- | --- |
| Import and syntax errors | Unit |
| Type mismatches | Unit and static analysis |
| Missing input validation | Unit |
| Edge cases and empty inputs | Unit |
| Business logic errors | Unit |
| Error paths and messages | Unit |
| Single-file configuration parsing | Unit |
| Cross-file contract drift | Pre-deployment integration |
| Credentials and permissions | Pre-deployment integration |
| State drift | Pre-deployment integration |
| Resource misconfiguration | Post-deployment integration |
| Component wiring | Post-deployment integration |
| What a caller receives from the deployed program | End to end |

## Quick Reference

| To test | Tier |
| --- | --- |
| A function's return value | Unit |
| An error raised for bad input | Unit |
| A parsed configuration value | Unit |
| A handler's response shape | Unit |
| Two units agreeing | Pre-deployment integration |
| Declared state matching the world | Pre-deployment integration |
| A live resource's settings | Post-deployment integration |
| A live resource's connections | Post-deployment integration |
| A caller's journey against the deployment | End to end |
