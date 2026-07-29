# Verifying in CI, never locally

Do not run tests, linters or builds locally to verify a change. Write the
code and the tests, commit, push to `main`, and read the run. The user
directed it without qualification: "nothing local. all verification in
CI."

This covers every gate, not only pytest. The static-analysis jobs, the
unit, integration and e2e tiers, and the seed deploy all run from
`.github/workflows/`, so a lint sweep is verified by pushing and reading
the failed job's log rather than by running an analyser locally file by
file. Local runs cost tokens; CI is free and checks everything at once.

The consequence for TDD is that the red-to-green transition is observed in
CI rather than on this machine — see [tdd-workflow](tdd-workflow.md). The
consequence for a change is that it is not done until the triggered
workflows are green: this repository has many path-filtered workflows, so
one push can start several, and each one that fired has to be read.

Verify with `gh run list`, `gh run watch` and `gh run view --log-failed`.
