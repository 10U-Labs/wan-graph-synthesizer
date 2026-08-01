# How issues are written

An issue in this repository has six sections, in this order, and every issue has all six even when a section is short.

- **Problem** — what is wrong, stated as a fact about the code with the evidence for it.
- **Why Unit Tests Did Not Catch It** — the specific assertions that passed, and why they could not have failed.
- **Why Integration Tests Did Not Catch It** — the same, for the tier that checks two units agreeing.
- **Why E2E Tests Did Not Catch It** — the same, for the tier that drives a real entrypoint.
- **Which Unit, Integration, or E2E regression tests would prevent this from happening again?** — the tests to write, each named by the tier it belongs to and the assertion it makes.
- **Solution** — what to change.

The three backward-looking test sections are the point of the format, not padding. A defect that reached the maps got past every tier that exists, and naming which assertion let it through is what turns one bug report into a gap in the suite that can be closed. Answer each tier honestly, including when the honest answer is that the tier does not exist for this code, or that the tier is the wrong home for the question and something else should have caught it. Do not skip a section because the answer is "there is no such tier" — that answer is the finding.

The regression section is those three read forwards, and it is where the coverage owed is named. Each entry says which tier the test sits in, what it sets up, and what it asserts, so that the test can be written from the issue without rediscovering the defect. It is a separate section from the solution because a fix and the test that would have caught it are separate pieces of work, and an issue that folds the second into the last paragraph of the first tends to ship without it.

Write prose in simple, plain, ordinary English. Short sentences, no hedging, no jargon from computer science where a plain word will do. Assume a network engineer is reading, not a graph theorist.

Use telecommunications vocabulary for the subject matter. Path diversity, not mesh degree. Site or point of presence, not node. Circuit, link, span, haul, chokepoint, protection. The source used graph-theory words for telecom concepts until issue #38 renamed the backbone setting to `number_of_diverse_paths`; where an identifier still reads as graph theory, take the vocabulary from this note rather than from the identifier you are describing.

Tables are allowed where a table genuinely reads better than a paragraph: a name-to-name rename mapping, or two measured columns being compared. Bullets are allowed only when enumerating a list of things. Do not use bullets to break up an argument — an argument is prose.

Back a claim with a number computed from the repository's own data wherever a number is available, and say how it was computed so a reader can redo it. Prefer bounds that survive new data being added over exact figures that go stale the moment somebody transcribes another map.

Issue bodies are not hard-wrapped, like all markdown here — see [markdown-is-not-hard-wrapped](markdown-is-not-hard-wrapped.md). The tier vocabulary and what each tier is for come from `docs/tenets/tests/` — see [read-test-tenets-first](read-test-tenets-first.md).

Issues #38, #39 and #40, written on 2026-07-31, are the worked examples of the prose. They predate the regression section, which was added on 2026-08-01, and each names its coverage inside the solution instead.
