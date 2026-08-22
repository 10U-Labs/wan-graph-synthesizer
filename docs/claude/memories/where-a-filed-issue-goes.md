# Where a filed issue goes

The open issues in this repository are held in an order, so that whoever picks up work next can see which one to take without asking anybody. The order is made of `blocked_by` edges, and one edge says one plain thing: this issue cannot be finished until that one is. Every reader sees the same edges, which is what makes the order a fact rather than somebody's recollection of a conversation. An issue filed with no edge is not in the order at all, and the work it names is either done last or not found.

An issue filed during a piece of work goes into the order before the work resumes. Which issue gets the edge follows from three cases that between them cover everything:

- The issue in hand cannot be finished until the new one is. The issue in hand gets the new one as a `blocked_by`, which puts the new issue immediately in front of it — and in front of everything when the issue in hand is the head of the order.
- Some other open issue cannot be finished until the new one is. That issue gets the new one as a `blocked_by`.
- Neither is true. The new issue gets an edge to the tail of the order, the one open issue that no other open issue is blocked by.

There is no fourth case and nothing to weigh. An issue is either needed before something already in the order or it is not, and whoever files it knows which — that is a question about what the issue says, not about what the order is for. An earlier version of this rule asked for a judgement about where the new issue best belonged, which hands the decision to the person least placed to make it.

Add the edge with `gh api repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by -F issue_id=<id>`, where `{number}` is the issue that waits and `<id>` is the numeric id of the blocker, read with `gh api repos/{owner}/{repo}/issues/{n} --jq .id`. Two things about that call go wrong on the first try. It has to be the numeric id: `gh issue view <n> --json id` returns the GraphQL node id instead, `I_kwDOSz3xVM8AAAABNduOUg` for #96, and the endpoint rejects it. And it has to be sent with `-F` rather than `-f`, because `-f` sends the number as a string and the API answers `HTTP 422: Invalid property /issue_id: "5199031511" is not of type integer`.

A blocker in another repository is allowed, and the edge records which repository it lives in, so following the edges out of one repository reaches issues in another. Numbers say nothing across a repository boundary: the two repositories number their issues independently and neither sequence means anything in the other, so the order is only ever the edges. An issue filed in another repository with no edge back is worse off than one here with no edge, because nothing reaches it at all.

Writing the edge is the step that gets skipped, and skipping it is silent — the issue looks filed, and nothing says it is unreachable. Issue #101, filed and solved on 2026-08-20, is the incident: three issues had gone in without an edge in a row, `10U-Labs/10ulabs.com` #487 and #488 and #100 here, in sessions where the reminder naming an issue's sections fired every ten minutes throughout. None of the three got an edge until somebody asked for one. Reading a rule once at the start of a session is not enough to make it happen an hour later, when the issue is filed as an interruption to something else and the something else is what gets returned to. That is why the rule also fires as the `:08` reminder in `.claude/skills/autopilot/SKILL.md` rather than sitting in the skill body alone.

The first case is more common than it looks, because the work in hand is what turns up the defect. #100 was filed while #96 was in hand, #96 could not be finished until it was, so #100 went in front and was solved first — both on 2026-08-20, with #96 closing fifteen minutes after #100 did.

How an issue is written once its place is settled is in [how-issues-are-written](how-issues-are-written.md), and the rule that its `Proposed Solution` names exactly one change is in [an-issue-states-one-solution](an-issue-states-one-solution.md).
