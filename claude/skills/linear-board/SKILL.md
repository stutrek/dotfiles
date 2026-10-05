---
name: linear-board
description: Sync Stu's personal Linear board ("Stu's board" project) from his open GitHub PRs — one issue per PR stack, grouped by workstream milestone, flagged when the next PR in a stack needs a review request, plus one issue per feature flag his PRs add, kept open until the flag is removed from master. Use when asked to "sync my board", "update Linear", "what do I need to request review on", "how are my stacks doing", "which flags do I still need to ramp or remove", or after opening, merging or re-stacking PRs. Also use when another agent opens a standalone PR (e.g. a Sentry fix) that should appear on the board.
---

# Linear board

GitHub is the source of truth. Linear is a view of it that this skill rewrites; never ask Stu to update Linear by hand, and never make a Linear issue per PR. The one exception to "issue = stack" is feature flags (below).

## Layout

- **Project:** `Stu's board` (P-ENG-252, https://linear.app/parabola/project/stus-board-63d069e8c2a4) in the Engineering team, lead Stu. Everything lives here.
- **Milestone = workstream** (the thing Stu is actually working on). Current ones: Prowork eval, Flow edit lock, Flow run conflicts, Canvas perf, PubNub removal, Step-auth guardrail, Flow copy, Worker hardening, Help desk fixes, Tooling / misc, Sentry fixes, React 19, Feature flags, Parked. A workstream can hold several stacks.
- **Issue = one stack**, or one standalone PR. Title is `<stack title> (<merged> of <total>)`, e.g. `Canvas perf: stop rebuilding styles on every render (1 of 6)`. The stack title is a plain-words description chosen when the issue is created; the progress suffix is rewritten on every sync (render.py's `progress`). Single PRs have no suffix.
- **Attachments:** every PR in the stack, merged and open, is attached to the issue so Linear shows its PR panel.
- **Status** (Engineering's shared workflow — don't add statuses):
  - `Todo` — every open PR in it is a draft
  - `In Review` — at least one open PR is out of draft
  - `Done` — nothing open remains (all merged or closed)
- **Label `needs-review-request`** — the next PR in the stack (bottom-up) is ready and nobody has been asked to review it. The "Ask for review" view filters on this label.
- **Feature flags:** every flag a PR of Stu's adds to `python_server/parabola/helpers/feature_flags.py` gets its own issue under the `Feature flags` milestone, titled `<flag-name> feature flag`, keyed `flag/<flag-name>`. It outlives the stack: it stays open after the adding PR merges, as the reminder to ramp the flag and then delete it, and closes only when the flag is gone from master. Status:
  - `Todo` — the PR that adds it hasn't merged
  - `In Progress` — live on master: ramp it, then remove it
  - `In Review` — still on master, and a PR removing it is open
  - `Done` — removed from master. `Canceled` — the adding PR closed unmerged
  The flag issue is `relatedTo` the stack issue whose table lists the adding PR.
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
5. Flags:
   ```bash
   python3 ~/.claude/skills/linear-board/flags.py --known <name>:<pr> ... > /tmp/flags.json
   ```
   Pass `--known` for every `flag/` issue already on the board that isn't `Done` or `Canceled`: the name from its marker and the PR number on its "added" row. That keeps a flag tracked after its PR ages out of the script's 45-day merged-PR window. Each entry has `key`, `title`, `state`, `description`, `links`, `added_in`, `removed_in`, `on_master` and `rollout`.
   - **Existing issue:** same as a stack — replace the description if it changed, set the title and status, attach any missing `links`.
   - **New flag:** create it only if `state` is `Todo` or `In Progress` (a flag added and removed within the window needs no reminder). Milestone `Feature flags`, assignee `me`, `relatedTo` the stack issue whose description links PR `added_in` — no need to ask.
   - **Hand-made flag issues** (no marker) come in two kinds:
     - An empty or near-empty one titled with the flag name is adopted: rewrite it with the marker and the rendered description.
     - One Stu wrote out (e.g. ENG-3760 "Flow lock feature flags", a checklist of three flags with rollout notes) **covers every flag it names in backticks**. Don't create issues for those flags, and never overwrite it. Mention in the report when one of its flags reaches Done, so Stu can tick it off.
6. Report back in a few lines: what needs a review request (PR number + one-line title + stack), what needs Stu's changes, what has failing CI, and any new stacks placed. For flags: which are live on master and still need ramping or removing, and which closed this sync. Link the board.

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

Flag issues render from `flags.py` instead:

```markdown
<!-- board-key: flag/prowork-append-deltas -->
**Removal in review** · [#16632](url)

Flag `prowork-append-deltas` (`FEATURE_FLAG_PROWORK_APPEND_DELTAS`)

Rollout on master: `ORGANIZATION, 0 if config.SERVER_ENV else 1`

| | PR | State |
|---|----|-------|
| added | [#16272](url) perf(prowork): stream reply text as append deltas | merged (2026-09-23) |
| removed | [#16632](url) chore(prowork): remove the prowork-append-deltas flag | open |
```

"Rollout on master" is the code default. Prod overrides live in Redis and aren't read by the sync; use the `prod-redis-reader` skill if Stu asks what a flag is really set to.

## Review rule (already implemented in stacks.py)

Bottom-up: the candidate is the lowest open PR in the stack that is neither `pr-clear` nor approved — everything beneath it lands without a human. It needs a review request when it is not a draft, has no changes requested, has no failing CI (Greptile and "Review policy" don't count as CI), and nobody has been requested or has reviewed yet.

## For other agents

If you open a standalone PR (a Sentry fix, a one-off), you don't have to touch Linear yourself — the next sync picks it up. If Stu asks you to put it on the board now, run the sync procedure; Sentry fixes go under the `Sentry fixes` milestone without asking.

## Gotchas

- The Codespace `GITHUB_TOKEN` can't read requested reviewers through GraphQL (`gh pr list --json reviewRequests` fails); the script uses the REST endpoints instead. Don't "simplify" that back.
- Asking GraphQL for CI rollups on every PR at once overflows; the script fetches them per PR.
- `flags.py` finds a flag by its definition line — `FEATURE_FLAG_X = "name"` or `FeatureFlag("name", …)` — added or deleted in the PR's diff of the flags file. A ramp (changing the percentage) doesn't add or delete one, so it doesn't show as a PR on the issue; the "Rollout on master" line picks it up once it lands. Merged PRs are found from master's commits on that file, so a flag that reached master inside someone else's squash isn't attributed to Stu.
- `save_issue`'s response can be stale: it sometimes echoes the old description and timestamp, or an empty `attachments`, even though the write landed. `get_issue` before retrying, or you'll attach a PR twice.
- Linear's GitHub integration may move linked tickets (e.g. ENG-3463) on its own when a PR merges. That's the linked ticket, not this board — leave it alone.
