---
name: autopilot
description: Start or stop the standing reminders that keep an autonomous issue-solving session on the rails. Use when the user says "start autopilot", "go autonomous on the open issues", "stop autopilot", or asks to clear the reminders. Takes "start" or "stop".
---

# Autopilot

Eight recurring reminders, one per standing rule, that fire back into this session while it works through open issues on its own. Each rule gets its own reminder so that no rule can be quietly dropped from a merged block of text, and the fire times are staggered across the ten-minute period so they arrive one at a time rather than as a wall.

The argument is the sub-command: `start` or `stop`.

`CronCreate`, `CronList` and `CronDelete` are deferred tools: the session is told their names but not their schemas, so a call made before the schema is fetched fails with `InputValidationError` and creates nothing. Fetch them first with `ToolSearch`, query `select:CronCreate,CronList,CronDelete`: `start` calls `CronCreate`, `stop` calls `CronList` and `CronDelete`.

## Start

Every open issue in the repository the session is running in is in scope, and `start` takes no argument. An issue reached by following a dependency out of that set is in scope as well, whatever repository it lives in, because numbering in one repository says nothing about another — this one is at #113 and `10U-Labs/10ulabs.com` is already at #488. The floor this used to take was a number below which open issues were left alone, which is a thing the sequence already says: an issue nobody should work yet is one something else blocks, written down as a `blocked_by` edge that every reader can see, rather than as a number one session was told once.

Create eight jobs with `CronCreate`, exactly as listed below. Use `recurring: true` (the default), and take all eight prompts verbatim. Each `cron` field is a distinct offset within the same ten-minute period, so the seven reminders never land together:

| Offset | Cron | Prompt |
| --- | --- | --- |
| :01 | `1,11,21,31,41,51 * * * *` | `REMINDER: Continue to solve the open issues autonomously, unless you need human feedback about ANYTHING — not just about the next open issue.` |
| :03 | `3,13,23,33,43,53 * * * *` | `REMINDER: Issues must be solved through a single commit & push.` |
| :04 | `4,14,24,34,44,54 * * * *` | `REMINDER: Issues must be solved through a set of indivisible Claude tasks.` |
| :05 | `5,15,25,35,45,55 * * * *` | `REMINDER: Lead with what the thing is for. Every paragraph — in chat as much as in issues, commits and comments — opens with a plain sentence saying what the thing is and what it does, before any file, function or line is named. Say what a defect costs in ordinary words near the top, not in the seventh paragraph. Then cut the details that change nothing the reader would do.` |
| :06 | `6,16,26,36,46,56 * * * *` | `REMINDER: Ensure Claude tasks are indivisible.` |
| :07 | `7,17,27,37,47,57 * * * *` | `REMINDER: Do not do anything but wait while a workflow is running.` |
| :08 | `8,18,28,38,48,58 * * * *` | `REMINDER: An issue you file goes into the sequence before you go back to work. Add a blocked_by edge: the issue in hand is blocked by the new one if it cannot be finished without it, otherwise whichever issue in the set cannot be finished without it, otherwise the new issue is blocked by the tail of the sequence. Never leave a filed issue with no edge.` |
| :09 | `9,19,29,39,49,59 * * * *` | `REMINDER: When you come up against a new problem, file a GitHub issue. A problem in the program — src/, lib/python/, scripts/, lib/opentofu/ — gets the sub-headers "Problem", "Why Unit Tests Did Not Catch It", "Why Integration Tests Did Not Catch It", "Why E2E Tests Did Not Catch It", "Which Unit, Integration, or E2E regression tests would prevent this from happening again?", and "Proposed Solution". A problem in a config, a map, a workflow file or the docs gets "Problem" and "Proposed Solution" only, and owes no tests.` |

Then tell the user that eight reminders are running, and the two limits that come with them: the jobs live in this session only and are gone when it ends, and recurring jobs auto-expire after seven days.

Then start working, in the same turn that created the jobs. Read the open issues with `gh issue list`, then read `gh api repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by` for each of them; every entry names the repository its blocker lives in. Follow those entries, and the entries of the issues they reach, until nothing new comes back, and add every open issue found this way to the set. Then take the lowest-numbered issue in the set that no open issue blocks, preferring the repository the session is running in when two are equally unblocked, and begin solving it under the standing rules the reminders carry — committing in whichever repository its `Proposed Solution` names, and reading that repository's CI to confirm it. Running this skill is starting the work; the eight jobs only keep it on the rails once it is going.

An issue filed during a run goes into the sequence before the session goes back to work. A `blocked_by` edge points from the issue that waits to the issue it waits on, and which issue gets the edge follows from three cases that between them cover everything. If the issue in hand cannot be finished until the new one is, the issue in hand gets the new one as a `blocked_by`, which puts the new issue immediately in front of it — and in front of the whole sequence when the issue in hand is its head, which is how #100 came to sit before #96. If some other issue in the set cannot be finished until the new one is, that issue gets the new one as a `blocked_by`. If neither is true, the new issue gets an edge to the tail of the sequence, the one open issue in the set that no other open issue is blocked by, which is #82 today. There is no fourth case and nothing to choose between: an issue is either needed before something already in the sequence or it is not.

A filed issue is never left without an edge. An issue with no edge in this repository is worked last whatever it is about, because it always carries the highest number and the tie-break above takes the lowest; an issue with no edge in another repository is not reached at all, because the traversal gets there only by following an edge into it.

Add the edge with `gh api repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by -F issue_id=<id>`, where `{number}` is the issue that waits and `<id>` is the numeric id of the blocker, read from `gh api repos/{owner}/{repo}/issues/{n} --jq .id`. It has to be that numeric id: `gh issue view <n> --json id` returns the GraphQL node id, `I_kwDOSz3xVM8AAAABNduOUg` for #96, and this endpoint rejects it. And it has to be sent with `-F` rather than `-f`, because `-f` sends the number as a string and the API answers `HTTP 422: Invalid property /issue_id: "5199031511" is not of type integer`.

## Stop

Call `CronList`, then call `CronDelete` once per job it returns — all of them, not only the eight this skill created. "Delete all your reminders" means the session ends with an empty schedule. Call `CronList` again afterwards to confirm it is empty, and report how many jobs were deleted.

`CronList` returning nothing is not a failure; say the schedule was already empty and stop.

## Notes

Starting autopilot begins the work in the same turn, changed on 2026-08-18. It used to create the eight jobs and stop, on the reasoning that arming the reminders and doing the work were separate things. What that produced was a session sitting idle after `/autopilot start 6`: a cron job fires only when the session is idle and the first one is up to ten minutes out, so the skill looked like it had not worked at all. A start at eight minutes past gets going in a minute and looks fine; a start at ten minutes past sits silent for the whole period, and that is the same skill on the same rules.

The three cron tools are deferred, which is why `Start` and `Stop` both open by fetching their schemas. A deferred tool is listed to the session by name only, so the first `CronCreate` call is rejected as invalid input and no job is created — a failure that reads like the tool is missing rather than like a step was skipped.

Cron jobs fire only while the session is idle, never mid-turn, because a turn cannot be preempted. That limit is the reason this skill does not try to correct drift in the middle of a task: what it can do is restart a loop that has stalled, which is the failure it is there to catch.

The issue sub-headers in the reminder at :09 match `CLAUDE.md` and `docs/claude/memories/how-issues-are-written.md` word for word, closing section included. They disagreed on that section until 2026-08-02: the reminder asked for `Proposed Solution` and the other two said `Solution`, so issues #35 and #37 through #55 were all filed with `## Solution`. `Proposed Solution` is the name, and the two files were changed to it rather than the reminder being changed away from it. The seven issues still open that day were rewritten to match; the fourteen closed ones keep `## Solution`, since nobody acts on the heading of a finished issue. Those files stay the authority when an issue is actually being written, and there is nothing left for them to disagree with.

The reminder at :05 was added on 2026-08-02 for the same reason the two-section form was added to the one at :09. The :09 reminder names the sections and nothing else, so an issue written to it comes out correctly structured and ordered for whoever wrote it: issue #47 opens by naming `_settled` and the line it sits on, and reaches the race between `seed` and `api_endpoint_tenants_wan_post` that makes the function matter three paragraphs later. Structure is not the whole of how an issue is written, and a reminder that names only structure is read as though it were. `docs/claude/memories/lead-with-what-it-is-for.md` is the long form, and it applies to chat replies and commit messages too, which is why the reminder does not say "issue".

That reminder carries the two-section form as well as the six, because it used to carry only the six and firing them alone every ten minutes was enough to produce the tests they asked for. A defect in a workflow file or a config was arriving beside a standing instruction to name the regression tests that would prevent it, and the instruction won: issue #37 had to argue at length that none were owed, and a contract over the seed workflow's yamllint list reached `test/` before the rule was written down. A reminder that names only one case is read as though the case were the whole rule.

The skill body is read when the skill is invoked, so editing this file does not reach a session already running under it. Whoever lands a change here has to `/autopilot stop` and `/autopilot start` again before it takes effect: a session that solved the issue which changed this file and then carried on is still working from the scope it was started with, and it will report that it has run out of issues rather than that it is reading the wrong set of them.

`CLAUDE.md` in this repository is the rulebook wherever the session is working, including in another repository the dependency traversal reaches. Verification in CI only, one issue per commit straight to `main`, and the writing and issue-structure rules all hold there. `10U-Labs/10ulabs.com` states none of its own, and a session working there under no rules at all is the worse outcome.

The three placement cases in `## Start` are settled by fact rather than by taste, added on 2026-08-19, so a session filing an issue has nothing to weigh and nothing to ask about. An earlier way of putting it asked the session to append, prepend or interpose the new issue as it judged best, which hands the decision to whoever is least able to make it: the session filing the issue knows what the issue is, which is exactly what the three cases read, and does not know what the sequence is for. The rule needs a reminder of its own because it is not read at invocation and then held — the `:09` reminder fired every ten minutes through the sessions that filed 10ulabs.com#487, 10ulabs.com#488 and #100, and not one of the three issues got an edge without being asked for one.

A reminder in this file is named by the minute it fires — the `:01` reminder, the `:09` reminder — and a line in it is written out in full, as "line 22". The rest of the repository writes `path/to/file.py:56` for a line and then a bare `:56` for another line in the same file, and that shorthand collides here: line 22 is the `:01` reminder, so "the reminder at `:22`" sends a reader looking for a reminder that fires at minute 22, and there is none.
