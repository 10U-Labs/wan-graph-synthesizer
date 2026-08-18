---
name: autopilot
description: Start or stop the standing reminders that keep an autonomous issue-solving session on the rails. Use when the user says "start autopilot", "go autonomous on issues above N", "stop autopilot", or asks to clear the reminders. Takes "start <issue-number>" or "stop".
---

# Autopilot

Seven recurring reminders, one per standing rule, that fire back into this session while it works through open issues on its own. Each rule gets its own reminder so that no rule can be quietly dropped from a merged block of text, and the fire times are staggered across the ten-minute period so they arrive one at a time rather than as a wall.

The argument is the sub-command: `start <issue-number>` or `stop`.

`CronCreate`, `CronList` and `CronDelete` are deferred tools: the session is told their names but not their schemas, so a call made before the schema is fetched fails with `InputValidationError` and creates nothing. Fetch them first with `ToolSearch`, query `select:CronCreate,CronList,CronDelete`: `start` calls `CronCreate`, `stop` calls `CronList` and `CronDelete`.

## Start

The issue number is required — it is the `{X}` in the first reminder, and every issue above it is in scope. If the user did not give one, ask for it before creating anything.

Create seven jobs with `CronCreate`, exactly as listed below. Use `recurring: true` (the default). Substitute the issue number for `{X}` in the first prompt and leave the other six verbatim. Each `cron` field is a distinct offset within the same ten-minute period, so the seven reminders never land together:

| Offset | Cron | Prompt |
| --- | --- | --- |
| :01 | `1,11,21,31,41,51 * * * *` | `REMINDER: Continue to solve open issues greater than issue {X} autonomously, unless you need human feedback about ANYTHING — not just about the next open issue.` |
| :03 | `3,13,23,33,43,53 * * * *` | `REMINDER: Issues must be solved through a single commit & push.` |
| :04 | `4,14,24,34,44,54 * * * *` | `REMINDER: Issues must be solved through a set of indivisible Claude tasks.` |
| :05 | `5,15,25,35,45,55 * * * *` | `REMINDER: Lead with what the thing is for. Every paragraph — in chat as much as in issues, commits and comments — opens with a plain sentence saying what the thing is and what it does, before any file, function or line is named. Say what a defect costs in ordinary words near the top, not in the seventh paragraph. Then cut the details that change nothing the reader would do.` |
| :06 | `6,16,26,36,46,56 * * * *` | `REMINDER: Ensure Claude tasks are indivisible.` |
| :07 | `7,17,27,37,47,57 * * * *` | `REMINDER: Do not do anything but wait while a workflow is running.` |
| :09 | `9,19,29,39,49,59 * * * *` | `REMINDER: When you come up against a new problem, file a GitHub issue. A problem in the program — src/, lib/python/, scripts/, lib/opentofu/ — gets the sub-headers "Problem", "Why Unit Tests Did Not Catch It", "Why Integration Tests Did Not Catch It", "Why E2E Tests Did Not Catch It", "Which Unit, Integration, or E2E regression tests would prevent this from happening again?", and "Proposed Solution". A problem in a config, a map, a workflow file or the docs gets "Problem" and "Proposed Solution" only, and owes no tests.` |

Then tell the user which issue number is in force, that seven reminders are running, and the two limits that come with them: the jobs live in this session only and are gone when it ends, and recurring jobs auto-expire after seven days.

Then start working, in the same turn that created the jobs. Read the open issues above `{X}` with `gh issue list`, take the lowest-numbered one that nothing else is blocking, and begin solving it under the standing rules the reminders carry. Running this skill is starting the work; the seven jobs only keep it on the rails once it is going.

## Stop

Call `CronList`, then call `CronDelete` once per job it returns — all of them, not only the seven this skill created. "Delete all your reminders" means the session ends with an empty schedule. Call `CronList` again afterwards to confirm it is empty, and report how many jobs were deleted.

`CronList` returning nothing is not a failure; say the schedule was already empty and stop.

## Notes

Starting autopilot begins the work in the same turn, changed on 2026-08-18. It used to create the seven jobs and stop, on the reasoning that arming the reminders and doing the work were separate things. What that produced was a session sitting idle after `/autopilot start 6`: a cron job fires only when the session is idle and the first one is up to ten minutes out, so the skill looked like it had not worked at all. A start at :08 gets going in a minute and looks fine; a start at :10 sits silent for the whole period, and that is the same skill on the same rules.

The three cron tools are deferred, which is why `Start` and `Stop` both open by fetching their schemas. A deferred tool is listed to the session by name only, so the first `CronCreate` call is rejected as invalid input and no job is created — a failure that reads like the tool is missing rather than like a step was skipped.

Cron jobs fire only while the session is idle, never mid-turn, because a turn cannot be preempted. That limit is the reason this skill does not try to correct drift in the middle of a task: what it can do is restart a loop that has stalled, which is the failure it is there to catch.

The issue sub-headers in the reminder at :09 match `CLAUDE.md` and `docs/claude/memories/how-issues-are-written.md` word for word, closing section included. They disagreed on that section until 2026-08-02: the reminder asked for `Proposed Solution` and the other two said `Solution`, so issues #35 and #37 through #55 were all filed with `## Solution`. `Proposed Solution` is the name, and the two files were changed to it rather than the reminder being changed away from it. The seven issues still open that day were rewritten to match; the fourteen closed ones keep `## Solution`, since nobody acts on the heading of a finished issue. Those files stay the authority when an issue is actually being written, and there is nothing left for them to disagree with.

The reminder at :05 was added on 2026-08-02 for the same reason the two-section form was added to the one at :09. The :09 reminder names the sections and nothing else, so an issue written to it comes out correctly structured and ordered for whoever wrote it: issue #47 opens by naming `_settled` and the line it sits on, and reaches the race between `seed` and `api_endpoint_tenants_wan_post` that makes the function matter three paragraphs later. Structure is not the whole of how an issue is written, and a reminder that names only structure is read as though it were. `docs/claude/memories/lead-with-what-it-is-for.md` is the long form, and it applies to chat replies and commit messages too, which is why the reminder does not say "issue".

That reminder carries the two-section form as well as the six, because it used to carry only the six and firing them alone every ten minutes was enough to produce the tests they asked for. A defect in a workflow file or a config was arriving beside a standing instruction to name the regression tests that would prevent it, and the instruction won: issue #37 had to argue at length that none were owed, and a contract over the seed workflow's yamllint list reached `test/` before the rule was written down. A reminder that names only one case is read as though the case were the whole rule.
