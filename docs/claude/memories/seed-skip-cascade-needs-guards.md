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

The failure is silent. `concluding-testing-necessary` and the whole
`static-analysis → unit → integration → e2e` chain were skipped while
`determining-testing` output `testing-necessary=true`; the run finished in
about 40 seconds and `seeding` deployed anyway.

When adding or moving a job downstream of a determining group, guard it
with `if: ${{ !cancelled() && needs.<parent>.result == 'success' }}`. The
`== 'success'` preserves fail-fast, where a bare `!cancelled()` would run
the job even when the gate or branch was skipped correctly. Piping the
decide value through `tee` — `echo "x=$v" | tee -a "$GITHUB_OUTPUT"` —
makes the determination visible in the log.

Failure must block where a skip must pass, and the two need different
guards. `!cancelled()` discards both signals, so a failed upstream still
runs the job. `determining-testing` uses `if: ${{ !failure() &&
!cancelled() }}`, which tolerates the skipped sibling but skips on a
failed need. An upstream failure launders into skips by the time it
reaches a convergence node, though, so `!failure()` cannot see it there.
`seeding` therefore uses a positive gate —
`... && (needs.concluding-testing-unnecessary.result == 'success' ||
needs.e2e-tests.result == 'success')` — and deploys only when a branch
tail actually succeeded. A cascade of skips makes both false and `seeding`
skips. That blocks a yamllint failure and a test failure alike, without
`seeding` ever needing `yamllint` directly.
