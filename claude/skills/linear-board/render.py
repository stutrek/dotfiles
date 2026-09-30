#!/usr/bin/env python3
"""Render each stack from stacks.py into the Linear issue description the board uses.

Usage: stacks.py | render.py > issues.json
Each entry: key, progress (title suffix like " (3 of 7)", empty for single PRs),
state, needs_review_request, relatedTo, links (every PR, for attachments), description.
"""
import json, re, sys, datetime
d = json.load(sys.stdin)
def short(t):
    t = re.sub(r"^(?:\[[^\]]*\]\s*)*\w+\([^)]*\)!?:?\s*", "", t)
    t = re.sub(r"^\d+\s+of\s+\d+\s*[—:-]*\s*", "", t)
    t = re.sub(r"\s*[\(\[](?:[A-Z]{2,6}-\d+)[\)\]]\s*$", "", t)
    return t if len(t) <= 70 else t[:67].rstrip() + "…"
LABEL = {"draft":"draft","pr-clear":"pr-clear","approved":"approved","changes-requested":"**changes requested**","open":"in review"}
today = datetime.date.today().isoformat()
out = []
for s in d["stacks"]:
    rows = []
    for m in s["merged"]:
        rows.append((m["n"], f"| {m['n']} | [#{m['number']}]({m['url']}) {short(m['title'])} | merged | |"))
    for p in s["open"]:
        st = LABEL[p["state"]]
        if p["number"] == s["needs_review_request"]: st = "**needs review request**"
        elif p["state"] == "open" and p.get("requested"): st = "review requested: " + ", ".join(p["requested"])
        if p["greptile_flagged"]: st += " · Greptile flagged"
        ci = p["ci"] if p["ci"] != "n/a" else ""
        if p["failing_checks"]: ci = "**failing**: " + ", ".join(sorted(set(p["failing_checks"])))
        rows.append((p["n"] if p["n"] is not None else 0, f"| {p['n'] if p['n'] is not None else ''} | [#{p['number']}]({p['url']}) {short(p['title'])} | {st} | {ci} |"))
    rows.sort(key=lambda r: r[0])
    head = f"**{len(s['merged'])} of {s['total']} merged**" if s["stacked"] else "**Single PR**"
    nxt = f" · next up: #{s['needs_review_request']} needs a review request" if s["needs_review_request"] else ""
    if s["needs_my_changes"]: nxt += " · changes requested on " + ", ".join(f"#{n}" for n in s["needs_my_changes"])
    desc = "\n".join([f"<!-- board-key: {s['key']} -->", head + nxt, "", "| # | PR | State | CI |", "|---|----|-------|----|", *[r[1] for r in rows], ""]
        + ([f"Related: {', '.join(s['tickets'])}", ""] if s["tickets"] else [])
        + [f"_Synced from GitHub {today}. Edits here are overwritten._"])
    progress = f" ({len(s['merged'])} of {s['total']})" if s["stacked"] else ""
    prs = sorted(s["merged"] + s["open"], key=lambda x: x.get("n") or 0)
    links = [{"url": x["url"], "title": f"#{x['number']} {short(x['title'])}"} for x in prs]
    out.append({"key": s["key"], "progress": progress, "state": s["status"], "needs_review_request": bool(s["needs_review_request"]), "relatedTo": s["tickets"], "links": links, "description": desc})
json.dump(out, sys.stdout, indent=1)
print()
