# Find a run by the full commit hash, never the short one

`gh run list --commit <sha>` matches only the full forty-character hash. Given the abbreviated seven-character form that `git log --oneline` prints and that everybody copies around, it returns an empty list. It does not warn, it does not error, and it does not say that nothing matched.

That would be a small annoyance if the empty list meant something distinct, but it does not. An empty list is exactly what the command returns when a commit genuinely has no runs yet, so the two situations are indistinguishable from the output alone. A watcher polling until the command reports something waits forever on a short hash, and the waiting looks identical to a run that has not started.

It cost two watchers in one session on 2026-07-30. Both were armed on the short hash `git log` had just printed. Both sat there until they timed out. Both times the workflows had in fact started, run and finished green within a couple of minutes. The runs were found immediately by listing recent runs and comparing the head SHA by hand, which is how the mistake surfaced at all.

Two ways to avoid it, and the second is better where something polls:

```sh
gh run list --commit "$(git rev-parse HEAD)"
gh run list --limit 10 --json workflowName,status,conclusion,headSha
```

The first passes the full hash, which `git rev-parse` gives and `git log --oneline` does not. The second does not use the filter at all: list the recent runs and match the head SHA by prefix locally. That works with either form of the hash and cannot silently match nothing, which is why it is the right shape for any loop that waits for a conclusion.

The same caution applies to reading a run rather than finding one. `gh run view <run-id>` takes the numeric run id from the listing, not a commit hash of any length, so take the id from the listing rather than constructing a query from the commit.

See also [verification-in-ci-only](verification-in-ci-only.md), which is why finding the run matters: the run is the only evidence a change works, so a watcher that silently never finds it is a change with no verification at all.
