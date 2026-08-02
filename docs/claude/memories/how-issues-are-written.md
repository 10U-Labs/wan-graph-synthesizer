# How issues are written

An issue about the program has six sections, in this order, and every issue about the program has all six even when a section is short.

- **Problem** — what is wrong, stated as a fact about the code with the evidence for it.
- **Why Unit Tests Did Not Catch It** — the specific assertions that passed, and why they could not have failed.
- **Why Integration Tests Did Not Catch It** — the same, for the tier that checks two units agreeing.
- **Why E2E Tests Did Not Catch It** — the same, for the tier that drives a real entrypoint.
- **Which Unit, Integration, or E2E regression tests would prevent this from happening again?** — the tests to write, each named by the tier it belongs to and the assertion it makes.
- **Solution** — what to change.

An issue about anything else has two sections, **Problem** and **Solution**, and owes no tests at all.

The program is the code a test tier can run: `src/`, `lib/python/`, `scripts/`, and the OpenTofu under `lib/` that the post-deployment tier checks once it is applied. The four test sections are about the program and are written only for it. A defect there got past tiers that exist and could have failed, and naming which assertion let it through is what turns one bug report into a gap in the suite that can be closed.

The tenant configs under `etc/`, the maps under `data/`, the workflow files under `.github/workflows/` and the documentation are not the program. No tier runs them. A test written against one of them opens the file, reads a value back and asserts the value it just read, so it cannot fail for a reason worth knowing and it fails for reasons that are not: it goes red every time somebody adds a tenant or renames a step. Do not write the four sections for such an issue, and do not write the test the fourth section would have asked for. Issue #37, a defect in three workflow files, spent its closing paragraph arguing why no coverage came with it, and an earlier draft of it had asked for two contract tests before they were dropped; under this rule neither the tests nor the argument would have been written.

The line is what the defect is in, not what the fix touches. A change to the program that also edits a config file is a program issue and gets all six. A change confined to config, maps or workflows is not, however much program behaviour it moves.

Within a program issue, answer each of the three backward-looking sections honestly, including when the honest answer is that the tier does not exist for that part of the program, or that the tier is the wrong home for the question and something else should have caught it. That answer is the finding, not a reason to leave the section out.

The regression section is those three read forwards, and it is where the coverage owed is named. Each entry says which tier the test sits in, what it sets up, and what it asserts, so that the test can be written from the issue without rediscovering the defect. It is a separate section from the solution because a fix and the test that would have caught it are separate pieces of work, and an issue that folds the second into the last paragraph of the first tends to ship without it.

Write prose in simple, plain, ordinary English. Short sentences, no hedging, no jargon from computer science where a plain word will do. Assume a network engineer is reading, not a graph theorist.

Use telecommunications vocabulary for the subject matter. Path diversity, not mesh degree. Site or point of presence, not node. Circuit, link, span, haul, chokepoint, protection. The source used graph-theory words for telecom concepts until issue #38 renamed the backbone setting to `number_of_diverse_paths`; where an identifier still reads as graph theory, take the vocabulary from this note rather than from the identifier you are describing.

Tables are allowed where a table genuinely reads better than a paragraph: a name-to-name rename mapping, or two measured columns being compared. Bullets are allowed only when enumerating a list of things. Do not use bullets to break up an argument — an argument is prose.

Back a claim with a number computed from the repository's own data wherever a number is available, and say how it was computed so a reader can redo it. Prefer bounds that survive new data being added over exact figures that go stale the moment somebody transcribes another map.

Issue bodies are not hard-wrapped, like all markdown here — see [markdown-is-not-hard-wrapped](markdown-is-not-hard-wrapped.md). The tier vocabulary and what each tier is for come from `docs/tenets/tests/` — see [read-test-tenets-first](read-test-tenets-first.md).

Issues #38, #39 and #40, written on 2026-07-31, are the worked examples of the prose. They predate the regression section, which was added on 2026-08-01, and each names its coverage inside the solution instead. The two-section form for everything outside the program was settled later the same day.
