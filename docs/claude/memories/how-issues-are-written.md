# How issues are written

An issue in this repository has five sections, in this order, and every issue has all five even when a section is short.

- **Problem** — what is wrong, stated as a fact about the code with the evidence for it.
- **Why Unit Tests Did Not Catch It** — the specific assertions that passed, and why they could not have failed.
- **Why Integration Tests Did Not Catch It** — the same, for the tier that checks two units agreeing.
- **Why E2E Tests Did Not Catch It** — the same, for the tier that drives a real entrypoint.
- **Solution** — what to change, including the coverage each tier is owed.

The three test sections are the point of the format, not padding. A defect that reached the maps got past every tier that exists, and naming which assertion let it through is what turns one bug report into a gap in the suite that can be closed. Answer each tier honestly, including when the honest answer is that the tier does not exist for this code, or that the tier is the wrong home for the question and something else should have caught it. Do not skip a section because the answer is "there is no such tier" — that answer is the finding.

Write prose in simple, plain, ordinary English. Short sentences, no hedging, no jargon from computer science where a plain word will do. Assume a network engineer is reading, not a graph theorist.

Use telecommunications vocabulary for the subject matter. Path diversity, not mesh degree. Site or point of presence, not node. Circuit, link, span, haul, chokepoint, protection. The source used graph-theory words for telecom concepts until issue #38 renamed the backbone setting to `number_of_diverse_paths`; where an identifier still reads as graph theory, take the vocabulary from this note rather than from the identifier you are describing.

Tables are allowed where a table genuinely reads better than a paragraph: a name-to-name rename mapping, or two measured columns being compared. Bullets are allowed only when enumerating a list of things. Do not use bullets to break up an argument — an argument is prose.

Back a claim with a number computed from the repository's own data wherever a number is available, and say how it was computed so a reader can redo it. Prefer bounds that survive new data being added over exact figures that go stale the moment somebody transcribes another map.

Issue bodies are not hard-wrapped, like all markdown here — see [markdown-is-not-hard-wrapped](markdown-is-not-hard-wrapped.md). The tier vocabulary and what each tier is for come from `docs/tenets/tests/` — see [read-test-tenets-first](read-test-tenets-first.md).

Issues #38, #39 and #40, written on 2026-07-31, are the worked examples of this format.
