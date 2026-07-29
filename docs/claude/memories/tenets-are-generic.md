# The tenets are generic, and the repository follows them

`docs/tenets/tests/` holds tenets, not documentation of the test suite.
A tenet is true whatever the repository holds: it names no language, no
tool, no directory, no resource and no count. The repository is what has
to change to match, never the other way round.

So a tenet says "one test file per unit of source, named for the unit it
covers", not which files cover which module. It says "a copy-paste gate
runs at a zero-tolerance threshold", not which tool runs it. It says
"put shared setup at the highest scope where it applies", not what lives
in the shared helpers today. Layout, tool names, step names, inventories
of existing utilities and counts of existing tests all belong to the
repository, which already states them and states them correctly.

Anything written into a tenet that the repository also states is a copy,
and it drifts with nothing to signal it — the same reasoning that keeps
these notes out of one machine's local memory
([verification-in-ci-only](verification-in-ci-only.md) covers where the
truth about the pipeline lives).

On 2026-07-29 an issue titled "Align docs/tenets/test/ to this repo" was
taken at face value and the five documents were rewritten to describe
this repository: its directory tree, its utility modules, its workflow
step names, its `tofu` and `pytest` invocations. That inverted the
relationship. The user's correction: "the tenets should not reflect the
repo but the other way around ... the tenets must be that, tenets, which
are generic regardless of how the repo looks, what languages it uses, or
what tools does it use". Removing what the repository does not use was
right; replacing it with a description of what the repository does use
was not. Pair with
[read-test-tenets-first](read-test-tenets-first.md), which is about
reading them before implementing.
