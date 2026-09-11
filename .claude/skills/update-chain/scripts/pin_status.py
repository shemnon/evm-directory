#!/usr/bin/env python3
"""Where one row's client pins stand against upstream, and what its fork schedule says.

The mechanical half of the update-chain skill. Everything here is a lookup and none of
it is judgment: it does not decide whether a fork happened, only which forks the row
itself says fell between the day it was pinned and now, and which newer releases exist.

  tools/.venv/bin/python .claude/skills/update-chain/scripts/pin_status.py <slug> [--json]

Needs `git` and an authenticated `gh`; network required.
"""
import argparse, json, pathlib, re, subprocess, sys, time
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[4]
CHAINS = ROOT / "chains"

# A tag that names a build nobody should pin a mainnet row to. GitHub's own
# prerelease flag is not enough: bnb-chain/bsc publishes `v1.8.0-alpha` as a full
# release marked Latest. `(?![a-z])` keeps "presto" and "prague" out of it.
UNSTABLE = re.compile(r"[-._+](alpha|beta|rc|pre|preview|dev|nightly|testnet|test|"
                      r"snapshot|unstable)(?![a-z])", re.I)


def sh(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def gh_json(*args):
    out = sh("gh", *args)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def epoch(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def gh_repo(url):
    return url.replace("https://github.com/", "").rstrip("/")


def family(tag):
    """A tag's naming scheme with the version stripped: `v1.7.8` -> `v`,
    `celo-v2.2.4` -> `celo-v`, `releases/linea-besu-package/v2.1.1` ->
    `releases/linea-besu-package/v`. Two tags of one family are comparable."""
    m = re.match(r"^(.*?)\d", tag)
    return m.group(1) if m else tag


def vkey(tag):
    return [int(n) for n in re.findall(r"\d+", tag)]


def is_tag(version):
    """clone.sh's rule: a single bare token is a tag; anything with prose in it
    ("main (UNTAGGED)", "... (branch)") is pinned by commit alone."""
    return bool(version) and " " not in version.strip()


def tag_commit(repo, tag):
    """The commit a tag names, peeled through an annotated tag object."""
    out = sh("git", "ls-remote", "--tags", f"https://github.com/{repo}",
             f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}") or ""
    refs = dict(reversed(l.split("\t")) for l in out.splitlines() if "\t" in l)
    return refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")


def commit_date(repo, sha):
    return epoch(sh("gh", "api", f"repos/{repo}/commits/{sha}",
                    "--jq", ".commit.committer.date"))


def candidates(repo, current):
    """Stable tags of the pin's family, newest first, plus the unstable ones newer
    than the pin (a testnet or alpha tag is often the first sign of a fork)."""
    fam = family(current)
    rel = gh_json("release", "list", "-R", repo, "--limit", "50", "--exclude-drafts",
                  "--json", "tagName,publishedAt,isPrerelease") or []
    rows = [{"tag": r["tagName"], "date": epoch(r["publishedAt"]),
             "unstable": r["isPrerelease"] or bool(UNSTABLE.search(r["tagName"]))}
            for r in rel]
    if not any(r["tag"] == current for r in rows):
        # Tag-only repos, or a pin older than the last 50 releases: fall back to
        # every tag, ordered by version number rather than publication date.
        out = sh("git", "ls-remote", "--tags", "--refs", f"https://github.com/{repo}") or ""
        tags = [l.split("refs/tags/", 1)[1] for l in out.splitlines() if "refs/tags/" in l]
        rows = sorted(({"tag": t, "date": None, "unstable": bool(UNSTABLE.search(t))}
                       for t in tags if family(t) == fam),
                      key=lambda r: vkey(r["tag"]), reverse=True)
    else:
        rows.sort(key=lambda r: r["date"] or 0, reverse=True)
    same = [r for r in rows if family(r["tag"]) == fam]
    idx = next((i for i, r in enumerate(same) if r["tag"] == current), len(same))
    newer = same[:idx]
    # Only a family published AFTER the pin can be its successor. Rootstock renames
    # every release (REED -> VETIVER -> ...), and listing the older names is noise.
    after = next((r["date"] for r in rows if r["tag"] == current), None)
    other = [r for r in rows if family(r["tag"]) != fam and not r["unstable"]
             and after and r["date"] and r["date"] > after][:3]
    return newer, other


def pin_report(label, repo_url, version, commit, clone_dir):
    repo = gh_repo(repo_url)
    p = {"label": label, "repo": repo, "version": version, "commit": commit,
         "pinned_commit_date": None, "clone": None, "kind": None,
         "target": None, "newer_stable": [], "newer_unstable": [], "other_families": []}
    if clone_dir.is_dir():
        p["clone"] = {"path": str(clone_dir.relative_to(ROOT)),
                      "head": sh("git", "-C", str(clone_dir), "rev-parse", "HEAD")}
    p["pinned_commit_date"] = commit_date(repo, commit)
    if is_tag(version):
        p["kind"] = "tag"
        newer, other = candidates(repo, version)
        p["newer_stable"] = [r for r in newer if not r["unstable"]]
        p["newer_unstable"] = [r for r in newer if r["unstable"]]
        p["other_families"] = other
        if p["newer_stable"]:
            t = p["newer_stable"][0]
            p["target"] = {"tag": t["tag"], "commit": tag_commit(repo, t["tag"]),
                           "date": t["date"]}
    else:
        # A branch or commit pin: the question is how far its branch has moved, not
        # which tag is newest. `name (branch)` and `main (UNTAGGED)` follow that named
        # branch; no version at all follows the default branch. Anything else is prose
        # about a revision ("rev 9d49e36 (...)", "submodule @ v1.14.1 (...)") with no
        # ref behind it, so no lookup can advance it and it is left to a human.
        m = re.match(r"^(\S+) \((?:branch|UNTAGGED)\)", version or "")
        ref = f"refs/heads/{m.group(1)}" if m else None if version else "HEAD"
        p["kind"], p["ref"] = ("branch", ref) if ref else ("prose", None)
        if ref:
            head = (sh("git", "ls-remote", f"https://github.com/{repo}", ref) or "").split("\t")[0]
            if head and head != commit:
                ahead = sh("gh", "api", f"repos/{repo}/compare/{commit}...{head}", "--jq", ".ahead_by")
                p["target"] = {"tag": None, "commit": head, "ahead_by": ahead,
                               "date": commit_date(repo, head)}
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = {f.parent.name: yaml.safe_load(f.read_text())
            for f in sorted(CHAINS.glob("*/chain.yaml"))}
    if a.slug not in rows:
        sys.exit(f"no chains/{a.slug}/chain.yaml")
    y = rows[a.slug]
    ch, cl, lin = y["chain"], y.get("client") or {}, y.get("lineage") or {}
    now = time.time()

    r = {"slug": a.slug, "name": ch.get("name"), "role": ch.get("role"),
         "evidence": ch.get("evidence", "source"), "live": ch.get("live"),
         "live_state": ch.get("live_state"), "dead": ch.get("dead"),
         "baseline_fork": y.get("baseline_fork"), "upstream": lin.get("upstream"),
         "shared_with": cl.get("shared_with"), "live_probe": y.get("live_probe"),
         "forks_src": (y.get("forks") or {}).get("src"),
         "stale_after": y.get("stale_after"), "pins": []}

    # When this row's pin was written, from the repo's own history: the commit that
    # introduced the pinned sha into chain.yaml. That, not the client's commit date,
    # is "the last pinned version" a fork has to postdate.
    f = f"chains/{a.slug}/chain.yaml"
    pinned_on = sh("git", "log", "-1", "--format=%cI", f"-S{cl['commit']}", "--", f) \
        if cl.get("commit") else None
    r["pinned_on"] = epoch(pinned_on) if pinned_on else None
    r["chain_yaml_last_commit"] = epoch(sh("git", "log", "-1", "--format=%cI", "--", f) or None)

    if cl and r["evidence"] != "documented":
        owner = cl.get("shared_with") or a.slug
        if not cl.get("shared_with"):
            name = gh_repo(cl["repo"]).split("/")[-1]
            r["pins"].append(pin_report("client", cl["repo"], cl.get("version"),
                                        cl["commit"], CHAINS / owner / "repos" / name))
        for k in cl.get("companion_repos") or []:
            r["pins"].append(pin_report(f"companion:{k['name']}", k["repo"],
                                        k.get("version"), k["commit"],
                                        CHAINS / owner / "repos" / k["name"]))

    since = r["pinned_on"] or r["chain_yaml_last_commit"] or 0
    r["forks"] = {"activated_since_pin": [], "overdue_pending": [], "upcoming": [],
                  "declared_untimed": []}
    for t in (y.get("forks") or {}).get("timeline") or []:
        st, at = t.get("status", "active"), t.get("activation_time")
        e = {"name": t.get("name"), "status": st, "activation_time": at,
             "mainnet_equivalent": t.get("mainnet_equivalent")}
        if st == "skipped":
            continue
        if not isinstance(at, (int, float)):
            # Block-height and governance activations (gnosis, scroll, polygon-zkevm,
            # kaia, hedera...) cannot be dated here; say what the row does record.
            if st == "pending":
                e["activation_block"] = t.get("activation_block")
                e["activation_condition"] = t.get("activation_condition")
                r["forks"]["declared_untimed"].append(e)
            continue
        if at > now:
            r["forks"]["upcoming"].append(e)
        else:
            if st == "pending":
                r["forks"]["overdue_pending"].append(e)
            if at > since:
                r["forks"]["activated_since_pin"].append(e)

    # Rows a change here reaches: stack/template descendants inherit this row's
    # entries, `shared_with` rows mirror its pin, and a second heritage borrows facts.
    r["descendants"] = sorted(
        s for s, o in rows.items() if s != a.slug and (
            (o.get("lineage") or {}).get("upstream") == a.slug
            or a.slug in ((o.get("lineage") or {}).get("ancestry") or [])
            or (o.get("lineage") or {}).get("second_heritage") == a.slug
            or (o.get("client") or {}).get("shared_with") == a.slug))

    if a.json:
        print(json.dumps(r, indent=2, default=str))
        return
    render(r, now)


def render(r, now):
    d = lambda ts: iso(ts) if ts else "?"
    print(f"{r['slug']}  ({r['name']})  role={r['role']}  evidence={r['evidence']}  "
          f"baseline_fork={r['baseline_fork']}")
    state = "live" if r["live"] else (r["live_state"] or "not live")
    if r["dead"]:
        state = f"DEAD ({r['dead'].get('how', 'unrecorded')}) — the pin does not move (SCHEMA.md)"
    print(f"  state      {state}")
    if r["upstream"]:
        print(f"  upstream   {r['upstream']}")
    if r["shared_with"]:
        print(f"  SHARED     pin belongs to `{r['shared_with']}` — bump that row; this one mirrors it")
    if r["evidence"] == "documented":
        print("  DOCUMENTED no public client, nothing to pin — only docs and live probes can change")
    print(f"  pinned on  {d(r['pinned_on'])}   (chain.yaml last touched {d(r['chain_yaml_last_commit'])})")
    if r["stale_after"]:
        flag = "  PASSED" if r["stale_after"] <= now else ""
        print(f"  stale_after {d(r['stale_after'])}{flag}")

    print("\npins")
    for p in r["pins"]:
        clone = p["clone"]
        cstate = "no clone" if not clone else (
            "clone at pin" if clone["head"] == p["commit"] else f"clone at {clone['head'][:8]} ≠ pin")
        print(f"  {p['label']:<30} {p['repo']}  {p['version'] or '(commit)'} @ {p['commit'][:8]}"
              f"  [{d(p['pinned_commit_date'])}]  {cstate}")
        t = p["target"]
        if p["kind"] == "tag":
            if t:
                print(f"    NEWER  → {t['tag']} @ {(t['commit'] or '?')[:12]}  [{d(t['date'])}]")
                for n in p["newer_stable"][1:]:
                    print(f"             also newer: {n['tag']}  [{d(n['date'])}]")
            else:
                print("    current — no newer stable tag of this family")
            for n in p["newer_unstable"]:
                print(f"    unstable newer tag: {n['tag']}  [{d(n['date'])}]  (not a pin candidate; read its notes for forks)")
            if p["other_families"] and not t:
                print("    other stable tag families (the naming may have changed): "
                      + ", ".join(o["tag"] for o in p["other_families"]))
        elif p["kind"] == "prose":
            print("    prose pin — no ref to follow; read `version` and advance it by hand")
        elif t:
            print(f"    BRANCH {p['ref']} moved → {t['commit'][:12]}  "
                  f"({t.get('ahead_by') or '?'} commits ahead)  [{d(t['date'])}]")
        else:
            print(f"    branch pin — {p['ref']} is still at the pin")

    f = r["forks"]
    print(f"\nforks  (schedule: {r['forks_src'] or 'no forks.src'})")
    if r["live_state"] == "prelaunch":
        print("  PRELAUNCH — there is no mainnet; these times are the stand-in testnet's")
    for e in f["activated_since_pin"]:
        print(f"  ACTIVATED SINCE PIN  {e['name']}  {d(e['activation_time'])}  status={e['status']}"
              f"  mainnet_equivalent={e['mainnet_equivalent']}")
    for e in f["overdue_pending"]:
        print(f"  OVERDUE PENDING      {e['name']}  {d(e['activation_time'])} — still marked pending; confirm it activated")
    for e in f["upcoming"]:
        print(f"  upcoming             {e['name']}  {d(e['activation_time'])}  status={e['status']}")
    for e in f["declared_untimed"]:
        how = (f"at block {e['activation_block']}" if e.get("activation_block")
               else e.get("activation_condition") or "no activation recorded")
        print(f"  pending, untimed     {e['name']}  {how} — check the head / release notes")
    if not any(f.values()):
        print("  nothing in the row's own timeline falls after the pin")
    print("  (only forks the row already declares; a fork first scheduled after the pin shows up\n"
          "   only in a diff of the schedule source between the old and new tags)")

    lp = r["live_probe"]
    if lp:
        print(f"\nlive_probe  {lp.get('endpoint')}  chain_id={lp.get('chain_id')}  "
              f"observed_at_block={lp.get('observed_at_block')}")
    if r["descendants"]:
        print(f"\nreaches     {', '.join(r['descendants'])}")


if __name__ == "__main__":
    main()
