#!/usr/bin/env python3
"""Find the feature flags my PRs add, and where each one stands on master.

A flag gets its own board issue from the PR that adds it until the PR that deletes
it lands, so a flag that's live but not yet ramped or cleaned up stays on the board.

Prints the board entries as JSON (same shape as render.py: key, title, state,
description, links, plus the flag details). GitHub is the source of truth; this
script only reads.

Usage: flags.py [--repo OWNER/NAME] [--author LOGIN] [--since-days N] [--known NAME:PR ...]

--known carries flags already on the board (name and the PR that added it, from the
issue's marker), so a flag whose PR has aged out of the --since-days window is
still tracked until it's removed from master.
"""

import argparse
import base64
import datetime
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

DEFAULT_REPO = "ParabolaLabs/parabola"
FLAGS_PATH = "python_server/parabola/helpers/feature_flags.py"
TRUNK = "master"

# FEATURE_FLAG_PROWORK_APPEND_DELTAS = "prowork-append-deltas"
CONST_RE = re.compile(r'^\s*(FEATURE_FLAG_\w+)\s*=\s*["\']([^"\']+)["\']')
# FeatureFlag("codeSandboxCodeTab", RolloutEntity.ORGANIZATION, ...)
LITERAL_RE = re.compile(r'FeatureFlag\(\s*["\']([^"\']+)["\']')
PR_IN_MESSAGE_RE = re.compile(r"\(#(\d+)\)\s*$")


def gh(*args, ok_missing=False):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        if ok_missing:
            return None
        sys.exit(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return json.loads(out.stdout) if out.stdout.strip() else None


def definitions(lines):
    """{flag name: constant or None} for every flag defined in these source lines."""
    found = {}
    for line in lines:
        if m := CONST_RE.match(line):
            found[m[2]] = m[1]
        for name in LITERAL_RE.findall(line):
            found.setdefault(name, None)
    return found


def patch_changes(patch):
    """(added, removed) flag definitions in a unified diff of the flags file.

    A flag defined on both sides (a reworded line, a moved block) is neither.
    """
    plus = [l[1:] for l in (patch or "").splitlines() if l.startswith("+") and not l.startswith("+++")]
    minus = [l[1:] for l in (patch or "").splitlines() if l.startswith("-") and not l.startswith("---")]
    added, removed = definitions(plus), definitions(minus)
    both = added.keys() & removed.keys()
    return {k: v for k, v in added.items() if k not in both}, {k: v for k, v in removed.items() if k not in both}


def calls(source):
    """Every FeatureFlag(...) call in the file, comments stripped and whitespace collapsed."""
    out, i = [], 0
    while (i := source.find("FeatureFlag(", i)) != -1:
        if source[max(0, i - 6):i].endswith("class "):
            i += 1
            continue
        depth, j = 0, i + len("FeatureFlag")
        while j < len(source):
            c = source[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = source[i + len("FeatureFlag(") : j]
        body = "\n".join(re.sub(r"\s+#.*$|^\s*#.*$", "", l) for l in body.splitlines())
        out.append(" ".join(body.split()).rstrip(", "))
        i = j
    return out


def rollout(source, name, const):
    """How master configures the flag, e.g. 'ORGANIZATION, 0 if config.SERVER_ENV else 1'."""
    firsts = {f'"{name}"', f"'{name}'"} | ({const} if const else set())
    for body in calls(source):
        first, _, rest = body.partition(",")
        if first.strip() in firsts:
            return rest.strip().replace("RolloutEntity.", "") or None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--author", default=None)
    ap.add_argument("--since-days", type=int, default=45, help="how far back to look for merged PRs that added flags")
    ap.add_argument("--known", nargs="*", default=[], help="NAME:PR for flags already on the board")
    args = ap.parse_args()
    repo = args.repo
    author = args.author or gh("api", "user")["login"]

    # Each flag: name -> {"const", "added_in" (PR number), "removed_in" [PR numbers]}
    flags = {}

    def note(pr, added, removed):
        for name, const in added.items():
            f = flags.setdefault(name, {"const": const, "added_in": None, "removed_in": []})
            f["const"] = f["const"] or const
            # Stacked PRs: keep the lowest number, the one that actually introduced it.
            f["added_in"] = min(pr, f["added_in"]) if f["added_in"] else pr
        for name, const in removed.items():
            f = flags.setdefault(name, {"const": const, "added_in": None, "removed_in": []})
            f["const"] = f["const"] or const
            if pr not in f["removed_in"]:
                f["removed_in"].append(pr)

    # Open PRs: each PR's own diff against its base, so a flag lands on the PR in a
    # stack that adds it, not on everything above it.
    open_prs = gh(
        "pr", "list", "--repo", repo, "--author", author, "--state", "open", "--limit", "300",
        "--json", "number",
    ) or []

    def pr_patch(number):
        files = gh("api", "--paginate", f"repos/{repo}/pulls/{number}/files?per_page=100") or []
        return number, next((f.get("patch") for f in files if f["filename"] == FLAGS_PATH), None)

    # Merged: commits on master that touched the flags file, by me, in the window.
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits = gh(
        "api", "--paginate",
        f"repos/{repo}/commits?sha={TRUNK}&path={FLAGS_PATH}&author={author}&since={since}&per_page=100",
    ) or []

    def commit_patch(c):
        m = PR_IN_MESSAGE_RE.search(c["commit"]["message"].splitlines()[0])
        if not m:
            return None, None
        full = gh("api", f"repos/{repo}/commits/{c['sha']}")
        return int(m[1]), next((f.get("patch") for f in full.get("files", []) if f["filename"] == FLAGS_PATH), None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(pr_patch, [p["number"] for p in open_prs])) + list(pool.map(commit_patch, commits))
    for number, patch in results:
        if number and patch:
            note(number, *patch_changes(patch))

    for k in args.known:
        name, _, pr = k.partition(":")
        f = flags.setdefault(name, {"const": None, "added_in": None, "removed_in": []})
        if pr and not f["added_in"]:
            f["added_in"] = int(pr)

    # Only flags I added (or am already tracking). Removing someone else's flag isn't mine to chase.
    known_names = {k.partition(":")[0] for k in args.known}
    flags = {n: f for n, f in flags.items() if f["added_in"] or n in known_names}

    content = gh("api", f"repos/{repo}/contents/{FLAGS_PATH}?ref={TRUNK}")
    master = base64.b64decode(content["content"]).decode()
    master_defs = definitions(master.splitlines())

    prs = {}

    def pr_info(number):
        return number, gh("pr", "view", str(number), "--repo", repo, "--json", "number,title,url,state,mergedAt", ok_missing=True)

    wanted = {n for f in flags.values() for n in [f["added_in"], *f["removed_in"]] if n}
    with ThreadPoolExecutor(max_workers=8) as pool:
        prs = dict(pool.map(pr_info, wanted))

    today = datetime.date.today().isoformat()
    out = []
    for name, f in sorted(flags.items()):
        const = f["const"] or master_defs.get(name)
        on_master = name in master_defs
        added = prs.get(f["added_in"]) if f["added_in"] else None
        removals = [prs[n] for n in sorted(f["removed_in"]) if prs.get(n)]
        live_removal = next((r for r in removals if r["state"] == "OPEN"), None)

        if added and added["state"] == "OPEN":
            state, head = "Todo", "**Not merged yet**"
        elif on_master:
            state, head = "In Progress", "**Live on master** · ramp it, then remove it"
            if live_removal:
                state, head = "In Review", f"**Removal in review** · [#{live_removal['number']}]({live_removal['url']})"
        elif added and added["state"] == "CLOSED":
            state, head = "Canceled", "**Never merged**"
        else:
            state, head = "Done", "**Removed from master**"

        rows = []
        if added:
            when = f" ({added['mergedAt'][:10]})" if added.get("mergedAt") else ""
            rows.append(f"| added | [#{added['number']}]({added['url']}) {added['title']} | {added['state'].lower()}{when} |")
        for r in removals:
            rows.append(f"| removed | [#{r['number']}]({r['url']}) {r['title']} | {r['state'].lower()} |")

        cfg = rollout(master, name, const) if on_master else None
        lines = [
            f"<!-- board-key: flag/{name} -->",
            head,
            "",
            f"Flag `{name}`" + (f" (`{const}`)" if const else ""),
            "",
        ]
        if cfg:
            lines += [f"Rollout on master: `{cfg}`", ""]
        if rows:
            lines += ["| | PR | State |", "|---|----|-------|", *rows, ""]
        if on_master:
            lines += ["Prod overrides live in Redis and aren't shown here — check with the `prod-redis-reader` skill.", ""]
        lines.append(f"_Synced from GitHub {today}. Edits here are overwritten._")

        links = [{"url": p["url"], "title": f"#{p['number']} {p['title']}"} for p in [added, *removals] if p]
        out.append(
            {
                "key": f"flag/{name}",
                "name": name,
                "constant": const,
                "title": f"{name} feature flag",
                "state": state,
                "on_master": on_master,
                "rollout": cfg,
                "added_in": f["added_in"],
                "removed_in": sorted(f["removed_in"]),
                "links": links,
                "description": "\n".join(lines),
            }
        )

    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
