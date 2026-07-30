# Markdown is not hard-wrapped

There is no column limit on markdown in this repository, and none on the markdown written into GitHub issues and pull requests either. Write a paragraph as one line and let whatever displays it do the wrapping. Do not break a sentence across lines to hit 72, 80 or any other width.

Nothing enforces a width, and that is deliberate rather than an oversight. `documentation.yml` runs `markdownlint '**/*.md' --disable MD013`, MD013 being the line-length rule, and every workflow that lints YAML sets `line-length: disable` before it runs. A hard-wrapped paragraph therefore passes CI exactly as an unwrapped one does; the choice is a convention, and the convention is not to wrap.

Hard wrapping costs something. An edit to the middle of a wrapped paragraph reflows every line after it, so a one-word change shows up as a rewritten block and the real change hides inside the noise. Unwrapped, a paragraph edit touches one line.

The trap is the existing files. Most of the markdown here — `CLAUDE.md`, the notes in this directory, the older issues — was written hard-wrapped before the restriction was lifted, so imitating what is already on disk reproduces the old style. On 2026-07-29 a rewrite of issue 17 was wrapped at 80 for exactly that reason: issues 15 and 16 were wrapped, so the new body was made to match them, even though issue 18 right next to them was not. The user's correction was that line-length restrictions were lifted for markdown everywhere. Take the width from this note, not from the neighbouring file.

Related: [tenets-are-generic](tenets-are-generic.md), on the same failure of copying what is already written instead of following the rule that governs it.
