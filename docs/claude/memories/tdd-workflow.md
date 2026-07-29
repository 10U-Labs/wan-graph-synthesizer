# Test-driven development

We do TDD in this repository. Write the test first, then the production
code that makes it pass. The user stated it plainly — "we do TDD."

Test-first here means authoring order, not a local red-green loop. The
failing observation and the passing one both belong to CI, because nothing
is run locally; see [verification-in-ci-only](verification-in-ci-only.md).
Put the tests and the implementation in the same commit, since a commit
goes straight to `main` with no pull-request buffer to hold a red state.

Coverage is not one test file. Add the test at each tier the change
touches, which means reading the tenets before writing anything; see
[read-test-tenets-first](read-test-tenets-first.md).
