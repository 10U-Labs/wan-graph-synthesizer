# Config-only commits skip the seed test tiers

`determining-testing` in `.github/workflows/seed.yml` reads the push diff
and sets `testing-necessary=false` when every changed path is under
`data/` or `etc/`. That is deliberate — new demand rows and a retuned knob
cannot break code — and it means a green `seed` run is not by itself
evidence that anything was tested. Read the job list, not the
conclusion: `static-analysis`, `unit-tests`, `integration-tests` and
`e2e-tests` all report `skipped`, `seeding` deploys, and the run is
`success`.

The trap is a series that splits the code from the configs it reads.
Issues #15 and #16 moved the tenant knobs under `backbone` and `access`
root keys across five configs, committed one file per commit after a
single commit had repointed every read in `scripts/seed.py`. Nothing
tested the combined state: the code commit's run was cancelled by the
next push, and each of the five config commits skipped every tier. The
suite was red for four commits and no run said so.

`gh run rerun` cannot recover it. The decision is recomputed from the
same `github.event.before`..`github.sha` diff, so a rerun of a
config-only push skips the tests again. Dispatch instead:

```sh
gh workflow run seed.yml --ref main
```

`workflow_dispatch` has no `github.event.before`, and the gate reads an
empty base as `necessary=true`, so every tier runs against the current
tip. Do this at the end of any series whose last commit touched only
`data/` or `etc/` — which is to say, whenever the configs are migrated
separately from their reader.

Interleaving instead of splitting avoids it: a commit that touches both
the config and the code has a diff outside `etc/`, so it tests. That is
the shape to prefer when each key can move on its own. Splitting is
still right when the reader has to change once for keys that then move
per file; it just owes a dispatch at the end.

See also [verification-in-ci-only](verification-in-ci-only.md) for why
the run is the only evidence there is, and
[seed-skip-cascade-needs-guards](seed-skip-cascade-needs-guards.md) for
the other way this workflow reports success without testing.
