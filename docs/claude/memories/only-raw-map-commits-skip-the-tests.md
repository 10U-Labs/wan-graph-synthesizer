# Only raw-map commits skip the seed test tiers

`determining-testing` in `.github/workflows/seed.yml` reads the push diff and sets `testing-necessary=false` only when every changed path is under `data/raw/`. Those are the carriers' published network maps, the PDFs and images the cleaned `data/vertices/` and `data/edges/` files were transcribed from by hand, and no code opens them. Everything else tests, including a push that touches nothing but `etc/` or nothing but the cleaned data. What that decision skips is four jobs — `lint-yaml`, `test-repo-libraries`, `unit-tests` and `integration-tests`. The other nine static-analysis checks and `yamllint` are gated on nothing and run on every push, so a raw-map commit is still read by `pylint`, `mypy`, `jscpd` and the three `assert-*` tools.

It did not always work that way. The exclusion used to cover all of `data/` and `etc/`, on the reasoning that a new demand row or a retuned knob cannot break code. That reasoning expired when the integration tier gained a contract between a tenant's backbone knobs and the carrier files — the check that no city is excused its diverse path count when its own fiber could have met it anyway. Editing `etc/` is the likeliest way to break that contract, and under the old exclusion it was exactly the push that skipped the check. Narrowing the exclusion to `data/raw/` is what keeps the gate honest while still skipping the one thing nothing reads.

What the old behaviour cost is worth remembering, because the same shape can return the moment an exclusion is widened. Issues #15 and #16 moved the tenant knobs under `backbone` and `access` root keys across five configs, committed one file per commit after a single commit had repointed every read in `scripts/seed.py`. Nothing tested the combined state: the code commit's run was cancelled by the next push, and each of the five config commits skipped every tier. The suite was red for four commits and no run said so.

`gh run rerun` cannot recover a run that skipped. The decision is recomputed from the same `github.event.before`..`github.sha` diff, so a rerun of a skipped push skips again. Dispatch instead:

```sh
gh workflow run seed.yml --ref main
```

`workflow_dispatch` has no `github.event.before`, and the gate reads an empty base as `necessary=true`, so every tier runs against the current tip. With the exclusion narrowed this is rarely needed, but it is still the only way to force a run whose last commit touched only the raw maps.

See also [verification-in-ci-only](verification-in-ci-only.md) for why the run is the only evidence there is, and [seed-skip-cascade-needs-guards](seed-skip-cascade-needs-guards.md) for the other way this workflow reports success without testing.
