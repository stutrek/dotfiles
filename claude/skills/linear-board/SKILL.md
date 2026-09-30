---
name: linear-board
description: Sync Stu's personal Linear board ("Stu's board" project) from his open GitHub PRs — one issue per PR stack, grouped by workstream milestone, flagged when the next PR in a stack needs a review request. Use when asked to "sync my board", "update Linear", "what do I need to request review on", "how are my stacks doing", or after opening, merging or re-stacking PRs. Also use when another agent opens a standalone PR (e.g. a Sentry fix) that should appear on the board.
---

# Linear board

GitHub is the source of truth. Linear is a view of it that this skill rewrites; never ask Stu to update Linear by hand, and never make a Linear issue per PR.

## Layout

- **Project:** `Stu's board` (P-ENG-252, https://linear.app/parabola/project/stus-board-63d069e8c2a4) in the Engineering team, lead Stu. Everything lives here.
- **Milestone = workstream** (the thing Stu is actually working on). Current ones: Prowork eval, Flow edit lock, Flow run conflicts, Canvas perf, PubNub removal, Step-auth guardrail, Flow copy, Worker hardening, Help desk fixes, Tooling / misc, Sentry fixes, Parked. A workstream can hold several stacks.
- **Issue = one stack**, or one standalone PR. Title is `<stack title> (<merged> of <total>)`, e.g. `Canvas perf: stop rebuilding styles on every render (1 of 6)`. The stack title is a plain-words description chosen when the issue is created; the progress suffix is rewritten on every sync (render.py's `progress`). Single PRs have no suffix.
- **Attachments:** every PR in the stack, merged and open, is attached to the issue so Linear shows its PR panel.
- **Status** (Engineering's shared workflow — don't add statuses):
  - `Todo` — every open PR in it is a draft
  - `In Review` — at least one open PR is out of draft
  - `Done` — nothing open remains (all merged or closed)
- **Label `needs-review-request`** — the next PR in the stack (bottom-up) is ready and nobody has been asked to review it. The "Ask for review" view filters on this label.
- **Existing tickets** (ENG-…, HELP-…) found in PR titles or branches are *linked* with `relatedTo`, never moved into this project.

## Sync procedure

1. Run the scripts from inside the repo checkout:
   ```bash
   python3 ~/.claude/skills/linear-board/stacks.py > /tmp/stacks.json
   python3 ~/.claude/skills/linear-board/render.py < /tmp/stacks.json > /tmp/issues.json
   ```
   `render.py` produces, per stack, the exact `description` to write (marker line included), plus `progress`, `state`, `needs_review_request`, `relatedTo` and `links` (every PR). Pass descriptions through verbatim — don't hand-write tables.

   `stacks.py` prints `{stacks: [...]}`. Each stack has `key` (e.g. `canvas/6`, or `pr/16538` for a standalone PR), `status`, `open` PRs bottom-first with a `state` each, `merged` PRs, `tickets`, `needs_review_request` (a PR number or null), `needs_my_changes`, `ci_failing`, and per-PR `greptile_flagged`. The review rule is already applied — don't recompute it.
2. Load the board: `list_issues` with project `Stu's board` (include `title`, `description`, `status`, `labels`, `projectMilestone`). Each issue's description starts with a marker line `<!-- board-key: <key> -->`; match stacks to issues by that key only.
3. For each stack:
   - **Existing issue:** strip any trailing ` (N of M)` from the current title to get the stack title, and set the title to stack title + `progress` if it changed. If the rendered description differs from the current one (ignore the "Synced from GitHub" date and Linear's escaping of `#`, `[`, `]`, `_` and `<url>` links), replace it; set status; add or remove `needs-review-request` with `addLabels`/`removeLabels`; append new ticket relations with `relatedTo`.
   - **New stack:** pick its milestone. If an existing milestone clearly fits (same scope, same ticket, same subject), use it. Otherwise **ask Stu** — list the new stacks together in one question with a suggested milestone for each, rather than one question per stack. Then create the issue with the marker, assignee `me`, the milestone, status and label.
   - **Attach PRs:** pass only the `links` whose URL isn't already among the issue's attachments (`get_issue` returns `attachments`; `links` is append-only, so resending creates duplicates). Linear rate-limits link attachments — roughly 40 in a burst. On a "Ratelimit exceeded" warning, wait a couple of minutes and retry just the missing ones; the rest of the save still succeeds.
   - Linear's GitHub integration can auto-move an issue when an attached PR merges. The status this sync sets wins — always set status from `state`, even if it looks unchanged.
4. Issues whose key no longer appears in the output: first check the PRs in their table with `gh pr view`.
   - Still open → the stack was **restacked** (e.g. `flow editing/5` became part of `flow editing/6` on 2026-09-30). Find the new key those PRs now belong to. If that key has no issue yet, re-key this issue (rewrite it with the new description) instead of creating a new one. If it already has one, set this one `Duplicate` of it.
   - All merged → `Done`. All closed unmerged → `Canceled`.
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
