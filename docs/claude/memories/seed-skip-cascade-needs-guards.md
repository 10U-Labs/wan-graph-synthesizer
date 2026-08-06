# Guarding the seed skip-cascade

In the determining-concluding chains of `.github/workflows/seed.yml`,
exactly one `concluding-*-necessary`/`unnecessary` gate runs and its
sibling is always skipped. GitHub Actions propagates that skip
**transitively** to every descendant, and an ordinary expression `if` does
not break it. Only a status-check function — `!cancelled()`, `always()`,
`success()`, `failure()` — does, and each descendant needs its own:
breaking the cascade on the parent does not clear it for the child. A job
whose sole `needs` job succeeded is still skipped when any transitive
ancestor was skipped.

The failure is silent. `concluding-testing-necessary` and every job behind
it — the static-analysis checks and the unit, integration and end-to-end
tiers — were skipped while `determining-testing` output
`testing-necessary=true`; the run finished in about 40 seconds and
`seeding` deployed anyway.

When adding or moving a job downstream of a determining group, guard it
with `if: ${{ !cancelled() && needs.<parent>.result == 'success' }}`. The
`== 'success'` preserves fail-fast, where a bare `!cancelled()` would run
the job even when the gate or branch was skipped correctly. Piping the
decide value through `tee` — `echo "x=$v" | tee -a "$GITHUB_OUTPUT"` —
makes the determination visible in the log.

Failure must block where a skip must pass, and the two need different
guards. `!cancelled()` discards both signals, so a failed upstream still
runs the job, and an upstream failure launders into skips by the time it
reaches a convergence node, so `!failure()` cannot see it there. `seeding`
therefore uses a positive gate reading `== 'success'` off every gate in
the workflow, and deploys only when a branch tail actually succeeded. A
cascade of skips makes it false and `seeding` skips.

The gate names all thirteen jobs one by one, because the ten
static-analysis checks and the three test jobs are independent of each
other and any one of them can be the only red job in the run — see
[every-check-is-its-own-job](every-check-is-its-own-job.md). Nine of the
checks are gated on nothing and run on every push, so they are `and`-ed in
flat. The other four — `lint-yaml`, `test-repo-libraries`, `unit-tests`
and `integration-tests` — skip on a `data/raw/`-only push, so they sit in
an arm against `needs.concluding-testing-unnecessary.result == 'success'`,
which is the only result that push leaves behind.

The `yamllint` job is outside all of this and blocks nothing. It once sat
behind `concluding-yamllint-necessary`, which `determining-testing` needed
under `if: ${{ !failure() && !cancelled() }}`, so a yamllint failure
skipped `determining-testing` and cascaded into a skipped `seeding`. Those
three jobs are gone and `determining-testing` needs nothing, so `yamllint`
now runs beside the rest and a red one leaves `seeding` free to deploy.
The five tenant configs in `etc/` are what only `yamllint` reads, so that
is what a red one is likely to be about.
