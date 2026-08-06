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

The gate names all twelve jobs one by one, because the nine static-analysis checks and the three test jobs are independent of each other and any one of them can be the only red job in the run — see [every-check-is-its-own-job](every-check-is-its-own-job.md). The nine checks are gated on nothing and run on every push, so they are `and`-ed in flat. The other three — `test-repo-libraries`, `unit-tests` and `integration-tests` — skip on a `data/raw/`-only push, so they sit in an arm against `needs.concluding-testing-unnecessary.result == 'success'`, which is the only result that push leaves behind.

No YAML linting stands between a push and the live API, and both of the ways it used to have gone. The `yamllint` job once sat behind `concluding-yamllint-necessary`, which `determining-testing` needed under `if: ${{ !failure() && !cancelled() }}`, so a yamllint failure skipped `determining-testing` and cascaded into a skipped `seeding`; those three jobs are gone and `determining-testing` needs nothing. `lint-yaml` was named in `seeding`'s `needs:` and `if:` directly, and it has been deleted — it ran `yamllint --strict` over `.github/workflows/seed.yml` with the same `--config-data` string the `yamllint` job uses on that file and the five tenant configs in `etc/`, so it found nothing the other job did not. What remains is one `yamllint` job that nothing waits on. It is the only job that reads `etc/afgsc.yml`, `etc/daf.yml`, `etc/dow.yml`, `etc/f_35.yml` and `etc/minuteman.yml`, which are the inputs `scripts/seed.py` publishes, so a red one is likely to be about a file `seeding` is about to PUT. Adding `- yamllint` to `seeding`'s `needs:` and `&& needs.yamllint.result == 'success'` to its `if` is what would restore the block.
