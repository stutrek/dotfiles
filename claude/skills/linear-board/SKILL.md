---
name: linear-board
description: Sync Stu's personal Linear board ("Stu's board" project) from his open GitHub PRs — one issue per PR stack, grouped by workstream milestone, flagged when the next PR in a stack needs a review request. Use when asked to "sync my board", "update Linear", "what do I need to request review on", "how are my stacks doing", or after opening, merging or re-stacking PRs. Also use when another agent opens a standalone PR (e.g. a Sentry fix) that should appear on the board.
---

# Linear board

GitHub is the source of truth. Linear is a view of it that this skill rewrites; never ask Stu to update Linear by hand, and never make a Linear issue per PR.

## Layout

- **Project:** `Stu's board` in the Engineering team, lead Stu. Everything lives here.
- **Milestone = workstream** (the thing Stu is actually working on). Examples: Prowork eval, Flow edit lock, Canvas perf, PubNub removal, Step-auth guardrail, Sentry fixes, Tooling / misc. A workstream can hold several stacks (flow editing has a "of 5" and an "of 6" stack).
- **Issue = one stack**, or one standalone PR. Title is the workstream-level description in plain words, not the PR title.
- **Status** (Engineering's shared workflow — don't add statuses):
  - `Todo` — every open PR in it is a draft
  - `In Review` — at least one open PR is out of draft
  - `Done` — nothing open remains (all merged or closed)
- **Label `needs-review-request`** — the next PR in the stack (bottom-up) is ready and nobody has been asked to review it. The "Ask for review" view filters on this label.
- **Existing tickets** (ENG-…, HELP-…) found in PR titles or branches are *linked* with `relatedTo`, never moved into this project.

## Sync procedure

1. Run the script from inside the repo checkout:
   ```bash
   python3 ~/.claude/skills/linear-board/stacks.py > /tmp/stacks.json
   ```
   It prints `{stacks: [...]}`. Each stack has `key` (e.g. `canvas/6`, or `pr/16538` for a standalone PR), `status`, `open` PRs bottom-first with a `state` each, `merged` PRs, `tickets`, `needs_review_request` (a PR number or null), `needs_my_changes`, `ci_failing`, and per-PR `greptile_flagged`. The review rule is already applied — don't recompute it.
2. Load the board: `list_issues` with project `Stu's board` (include `description`, `status`, `labels`, `projectMilestone`). Each issue's description starts with a marker line `<!-- board-key: <key> -->`; match stacks to issues by that key only.
3. For each stack:
   - **Existing issue:** replace the description body (keep the marker), set status, add or remove `needs-review-request`, append new ticket relations.
   - **New stack:** pick its milestone. If an existing milestone clearly fits (same scope, same ticket, same subject), use it. Otherwise **ask Stu** — list the new stacks together in one question with a suggested milestone for each, rather than one question per stack. Then create the issue with the marker, assignee `me`, the milestone, status and label.
   - Attach each PR as a link (`links: [{url, title: "#123 …"}]`) — append-only, so only add ones not already attached.
4. Issues whose key no longer appears in the output: if the stack's PRs are merged, set `Done`; if they were closed unmerged, set `Canceled`. Check with `gh pr view` before changing status.
5. Report back in a few lines: what needs a review request (PR number + one-line title + stack), what needs Stu's changes, what has failing CI, and any new stacks placed. Link the board.

## Description format

```markdown
<!-- board-key: canvas/6 -->
**3 of 6 merged** · next up: #16520 needs a review request

| # | PR | State | CI |
|---|----|-------|----|
| 1 | [#16516](url) stop redrawing every step… | merged | |
| 2 | [#16517](url) keep drag positions local… | pr-clear | passing |
| 5 | [#16520](url) build card, note and chart… | **needs review request** | passing |

Related: HELP-1853
_Synced from GitHub <date>. Edits here are overwritten._
```

Keep the PR titles short (drop the conventional-commit prefix and "N of M"). Mark Greptile findings as "Greptile flagged" in the State column.

## Review rule (already implemented in stacks.py)

Bottom-up: the candidate is the lowest open PR in the stack that is neither `pr-clear` nor approved — everything beneath it lands without a human. It needs a review request when it is not a draft, has no changes requested, has no failing CI (Greptile and "Review policy" don't count as CI), and nobody has been requested or has reviewed yet.

## For other agents

If you open a standalone PR (a Sentry fix, a one-off), you don't have to touch Linear yourself — the next sync picks it up. If Stu asks you to put it on the board now, run the sync procedure; Sentry fixes go under the `Sentry fixes` milestone without asking.

## Gotchas

- The Codespace `GITHUB_TOKEN` can't read requested reviewers through GraphQL (`gh pr list --json reviewRequests` fails); the script uses the REST endpoints instead. Don't "simplify" that back.
- Asking GraphQL for CI rollups on every PR at once overflows; the script fetches them per PR.
- Linear's GitHub integration may move linked tickets (e.g. ENG-3463) on its own when a PR merges. That's the linked ticket, not this board — leave it alone.
