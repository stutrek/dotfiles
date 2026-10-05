#!/usr/bin/env python3
"""Group my open PRs into stacks and decide which one needs a review request.

Prints JSON to stdout. GitHub is the source of truth; this script only reads.

Usage: stacks.py [--repo OWNER/NAME] [--author LOGIN]
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

DEFAULT_REPO = "ParabolaLabs/parabola"
CLEAR_LABEL = "pr-clear"
TRUNKS = {"master", "main"}

# "[HELP-1853] fix(step auth): 3 of 4 — ..." / "dev(prowork eval) 12 of 12: ..."
TITLE_RE = re.compile(
    r"^(?:\[[^\]]*\]\s*)*(?P<type>\w+)\((?P<scope>[^)]+)\)!?:?\s*(?P<n>\d+)\s+of\s+(?P<m>\d+)",
    re.IGNORECASE,
)
TICKET_RE = re.compile(r"\b([A-Z]{2,6}-\d+)\b")
FAILING = {"FAILURE", "ERROR", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"}
PENDING = {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", "WAITING", "REQUESTED"}
# Checks that report on review, not on the code: they never block asking for a review.
REVIEW_CHECKS = {"Review policy"}
GREPTILE_CHECK = "Greptile Review"


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return json.loads(out.stdout) if out.stdout.strip() else None


def parse_title(title):
    m = TITLE_RE.match(title)
    if not m:
        return None
    return {"scope": m["scope"].strip().lower(), "n": int(m["n"]), "m": int(m["m"])}


def tickets(*texts):
    found = set()
    for t in texts:
        # "PR-03h"-style stack labels look like tickets but aren't.
        found.update(x for x in TICKET_RE.findall(t or "") if not x.startswith(("NOTICKET", "PR-")))
    return sorted(found)


def ci_state(rollup):
    """(ci, failing check names, greptile flagged). Review-ish checks are left out of ci."""
    checks = [(c.get("name") or c.get("context") or "?", (c.get("conclusion") or c.get("state") or "").upper()) for c in rollup or []]
    greptile = any(n == GREPTILE_CHECK and st in FAILING for n, st in checks)
    checks = [(n, st) for n, st in checks if n not in REVIEW_CHECKS and n != GREPTILE_CHECK]
    failing = sorted({n for n, st in checks if st in FAILING})
    if failing:
        return "failing", failing, greptile
    if any(st in PENDING for _, st in checks):
        return "pending", [], greptile
    return "passing", [], greptile


def review_activity(repo, number, author):
    """Requested reviewers plus humans (not the author, not bots) who have reviewed."""
    req = gh("api", f"repos/{repo}/pulls/{number}/requested_reviewers")
    reviews = gh("api", f"repos/{repo}/pulls/{number}/reviews") or []
    reviewers = sorted(
        {
            r["user"]["login"]
            for r in reviews
            if r.get("user") and r["user"]["login"] != author and not r["user"]["login"].endswith("[bot]")
        }
    )
    requested = [u["login"] for u in req.get("users", [])] + [f"team:{t['slug']}" for t in req.get("teams", [])]
    return requested, reviewers


def pr_state(pr):
    if pr["isDraft"]:
        return "draft"
    if pr["clear"]:
        return "pr-clear"
    if pr["reviewDecision"] == "APPROVED":
        return "approved"
    if pr["reviewDecision"] == "CHANGES_REQUESTED":
        return "changes-requested"
    return "open"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--author", default=None)
    args = ap.parse_args()
    author = args.author or gh("api", "user")["login"]

    prs = gh(
        "pr", "list", "--repo", args.repo, "--author", author, "--state", "open", "--limit", "300",
        "--json", "number,title,url,isDraft,baseRefName,headRefName,labels,reviewDecision,updatedAt",
    )

    # CI rollups for every PR in one query overflows the API, so fetch per PR.
    def rollup(pr):
        if pr["isDraft"]:
            return pr["number"], []
        v = gh("pr", "view", str(pr["number"]), "--repo", args.repo, "--json", "statusCheckRollup")
        return pr["number"], v["statusCheckRollup"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        rollups = dict(pool.map(rollup, prs))
    by_head = {}
    for pr in prs:
        pr["clear"] = any(l["name"] == CLEAR_LABEL for l in pr["labels"])
        pr["ci"], pr["failing_checks"], pr["greptile_flagged"] = ci_state(rollups[pr["number"]]) if not pr["isDraft"] else ("n/a", [], False)
        pr["parsed"] = parse_title(pr["title"])
        by_head[pr["headRefName"]] = pr

    children = {}
    roots = []
    for pr in prs:
        if pr["baseRefName"] in by_head:
            children.setdefault(pr["baseRefName"], []).append(pr)
        else:
            roots.append(pr)

    def walk(pr):
        # Depth-first, bottom first; siblings ordered by their "N of M".
        out = [pr]
        for c in sorted(children.get(pr["headRefName"], []), key=lambda p: (p["parsed"] or {}).get("n", 0)):
            out.extend(walk(c))
        return out

    # A stack can have more than one root (e.g. a "0 of 12" prerequisite on its own
    # base), so trees sharing a series merge into one stack, ordered by "N of M".
    groups, by_series = [], {}
    for r in roots:
        g = walk(r)
        p = next((x["parsed"] for x in g if x["parsed"]), None)
        k = (p["scope"], p["m"]) if p else None
        if k and k in by_series:
            by_series[k].extend(g)
            by_series[k].sort(key=lambda x: (x["parsed"] or {}).get("n", 0))
        else:
            groups.append(g)
            if k:
                by_series[k] = g

    # Merged history per stack series, so "3 of 9 merged" counts PRs that already landed.
    series = {}
    for g in groups:
        p = next((x["parsed"] for x in g if x["parsed"]), None)
        if p:
            series[(p["scope"], p["m"])] = None

    def merged_for(key):
        scope, m = key
        found = gh(
            "pr", "list", "--repo", args.repo, "--author", author, "--state", "merged", "--limit", "100",
            "--search", f'"{scope}" in:title', "--json", "number,title,url,mergedAt",
        ) or []
        keep = []
        for pr in found:
            p = parse_title(pr["title"])
            if p and p["scope"] == scope and p["m"] == m:
                keep.append({"number": pr["number"], "n": p["n"], "title": pr["title"], "url": pr["url"], "mergedAt": pr["mergedAt"]})
        return key, sorted(keep, key=lambda x: x["n"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        series = dict(pool.map(merged_for, list(series)))

    # Bottom-up review rule: the candidate is the lowest open PR that still needs a
    # human (not pr-clear, not approved). Everything beneath it is on its way in.
    candidates = []
    for g in groups:
        cand = next((p for p in g if not p["clear"] and p["reviewDecision"] != "APPROVED"), None)
        if cand and not cand["isDraft"]:
            candidates.append(cand)

    def fill(pr):
        pr["requested"], pr["reviewers"] = review_activity(args.repo, pr["number"], author)
        return pr

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fill, candidates))
    cand_by_num = {c["number"]: c for c in candidates}

    stacks = []
    for g in groups:
        p = next((x["parsed"] for x in g if x["parsed"]), None)
        key = f"{p['scope']}/{p['m']}" if p else f"pr/{g[0]['number']}"
        merged = series.get((p["scope"], p["m"]), []) if p else []
        cand = next((cand_by_num[x["number"]] for x in g if x["number"] in cand_by_num), None)

        request = None
        if cand and cand["reviewDecision"] != "CHANGES_REQUESTED" and cand["ci"] != "failing" and not cand["requested"] and not cand["reviewers"]:
            request = cand["number"]

        open_prs = [
            {
                "number": x["number"],
                "n": (x["parsed"] or {}).get("n"),
                "title": x["title"],
                "url": x["url"],
                "state": pr_state(x),
                "ci": x["ci"],
                "failing_checks": x["failing_checks"],
                "greptile_flagged": x["greptile_flagged"],
                "updatedAt": x["updatedAt"],
                **({"requested": x["requested"], "reviewers": x["reviewers"]} if "requested" in x else {}),
            }
            for x in g
        ]
        stacks.append(
            {
                "key": key,
                "scope": p["scope"] if p else None,
                "total": p["m"] if p else len(g),
                "stacked": bool(p) or len(g) > 1,
                "status": "Todo" if all(x["isDraft"] for x in g) else "In Review",
                "tickets": tickets(*[x["title"] for x in g], *[x["headRefName"] for x in g], *[m["title"] for m in merged]),
                "merged": merged,
                "open": open_prs,
                "needs_review_request": request,
                "needs_my_changes": [x["number"] for x in g if x["reviewDecision"] == "CHANGES_REQUESTED"],
                "ci_failing": [x["number"] for x in g if x["ci"] == "failing"],
                "lastUpdated": max(x["updatedAt"] for x in g),
            }
        )

    stacks.sort(key=lambda s: s["lastUpdated"], reverse=True)
    json.dump({"author": author, "repo": args.repo, "stacks": stacks}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
