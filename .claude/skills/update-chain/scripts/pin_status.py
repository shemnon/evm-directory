#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Where one row's client pins stand against upstream, and what its fork schedule says.

The mechanical half of the update-chain skill. Everything here is a lookup and none of
it is judgment: it does not decide whether a fork happened, only which forks the row
itself says fell between the day it was pinned and now, and which newer releases exist.

  tools/.venv/bin/python .claude/skills/update-chain/scripts/pin_status.py <slug> [--json]

Needs `git` and an authenticated `gh`; network required.
"""
import argparse, json, pathlib, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone

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
    """A tag's SHAPE: the full string with every run of digits masked.
    `v1.7.8` -> `v#.#.#`, `celo-v2.2.4` -> `celo-v#.#.#`,
    `v1.15.5-wasp1` -> `v#.#.#-wasp#`, `v1.20.4-1789748350` -> `v#.#.#-#`.

    Two tags are comparable ONLY if their full strings differ in nothing but the
    numbers. The previous rule kept just the prefix before the first digit, which
    collapsed every `v*` tag into one family and made these three wrong answers
    look right:

      pin `v1.15.5-wasp1`  ->  `v1.16.3`              a PLAIN UPSTREAM geth tag
                               `v1.16.2-wasp`          a different suffix series
      pin `v1.20.3`        ->  `v1.20.4-1789748350`    a tree holding one file,
                                                       SOURCE_CODE_IS_PRIVATE

    A fork that carries both its own suffixed tags and its upstream's — which is
    most of the Go forks in this dataset — cannot be compared on the prefix alone.
    A differing shape is not noise: it is the hint about parentage that
    `other_families` reports, and it stays out of `newer_stable` where a target
    would be taken from it."""
    return re.sub(r"\d+", "#", tag)


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


def gh_file(repo, ref, path):
    """One file's text at a ref, or None. `gh api contents` also answers for a
    gitlink, where it returns type `submodule` and the sha it points at."""
    out = sh("gh", "api", f"repos/{repo}/contents/{path}?ref={ref}",
             "--jq", 'if .type == "submodule" then "SUBMODULE " + .sha else .content end')
    if not out:
        return None
    if out.startswith("SUBMODULE "):
        return out
    import base64
    try:
        return base64.b64decode(out).decode("utf-8", "replace")
    except Exception:
        return None


def manifest_key(line):
    """The left-hand side of a manifest line: `besuCommit` from `besuCommit = "..."`,
    `github.com/0xsoniclabs/tosca` from a go.mod require. Used to find the SAME entry
    at another ref instead of every line that happens to name the repo."""
    l = line.strip().lstrip("-").strip()
    if "=" in l and not l.startswith("github.com/"):
        return l.split("=", 1)[0].strip()
    parts = l.replace("replace ", "").split()
    return parts[0] if parts else None


def manifest_hits(repo, ref, path, sha, name, version=None):
    """What `path` at `ref` says about this companion.

    The question is exact — "does the client still name THIS commit?" — so the needle
    is the PINNED SHA, not the repo name. A repo name is far too loose to decide on:
    `besu` matches `besuPluginLibrary` and `besuShomeiPluginVersion` in Linea's Gradle
    catalog, neither of which is the pin, and a version bump in either would read as
    the companion moving. The sha cannot be confused with anything.

    Go pseudo-versions carry only the first 12 hex, so match that prefix too.

    Returns (sha_lines, name_lines, found) — `found` is whether the pinned sha is
    present at all. When it is not, `name_lines` is what the reader needs to see
    instead, and the caller says plainly that it is a guess rather than the pin.
    This stays a lookup, not a parser: four manifest formats say the same thing in
    four syntaxes, and the line itself is checkable by eye."""
    txt = gh_file(repo, ref, path)
    if txt is None:
        return None
    if txt.startswith("SUBMODULE "):
        got = txt.split(" ", 1)[1]
        return ([got], [got], got.startswith(sha[:12]))
    # A manifest may name the commit OR the tag: go.mod replace directives and
    # Cargo `tag = "..."` deps carry a version and no sha, which is why nine
    # companions reported "sha not located" before the version was a needle too.
    keys = [sha.lower(), sha.lower()[:12]]
    vkeys = []
    if version and not re.search(r"\((?:branch|UNTAGGED)\)|^(rev|submodule) ", version):
        # A version alone is ambiguous: artela pins artela-evm AND aspect-runtime at
        # v0.4.8-rc8, so the version must be paired with the repo name to pick a line.
        vkeys.append(version.lower())
    shal, namel = [], []
    for l in txt.splitlines():
        ls, low = l.strip(), l.lower()
        named = name.lower() in low
        if any(k in low for k in keys) or (named and any(k in low for k in vkeys)):
            shal.append(ls)
        elif named:
            namel.append(ls)
    return (shal, namel, bool(shal))


def candidates(repo, current):
    """Stable tags of the pin's family, newest first, plus the unstable ones newer
    than the pin (a testnet or alpha tag is often the first sign of a fork)."""
    fam = family(current)
    rel = gh_json("release", "list", "-R", repo, "--limit", "50", "--exclude-drafts",
                  "--json", "tagName,publishedAt,isPrerelease") or []
    rows = [{"tag": r["tagName"], "date": epoch(r["publishedAt"]),
             "unstable": r["isPrerelease"] or bool(UNSTABLE.search(r["tagName"]))}
            for r in rel]
    tag_only = not any(r["tag"] == current for r in rows)
    if tag_only:
        # Tag-only repos, or a pin older than the last 50 releases: fall back to
        # every tag, ordered by version number rather than publication date. Keep
        # ALL shapes here, not just the pin's — the other-shape tags are the
        # parentage hint, and on a tag-only repo this is the only place to find it
        # (iotaledger/go-ethereum publishes no releases at all).
        out = sh("git", "ls-remote", "--tags", "--refs", f"https://github.com/{repo}") or ""
        tags = [l.split("refs/tags/", 1)[1] for l in out.splitlines() if "refs/tags/" in l]
        rows = sorted(({"tag": t, "date": None, "unstable": bool(UNSTABLE.search(t))}
                       for t in tags),
                      key=lambda r: vkey(r["tag"]), reverse=True)
    else:
        rows.sort(key=lambda r: r["date"] or 0, reverse=True)
    same = [r for r in rows if family(r["tag"]) == fam]
    idx = next((i for i, r in enumerate(same) if r["tag"] == current), len(same))
    newer = same[:idx]
    # Only a shape published AFTER the pin can be its successor. Rootstock renames
    # every release (REED -> VETIVER -> ...), and listing the older names is noise.
    # With shape-based families this list also carries the upstream-parentage hint:
    # a `-wasp` series next to a `-wasp1` pin, or a plain `v1.16.3` next to both.
    after = next((r["date"] for r in rows if r["tag"] == current), None)
    if tag_only:
        # No dates to order by, and a tag-only repo is full of junk refs
        # (`PoC6`, `buildbot-testing-tag-3`). Keep only shapes in the PIN'S OWN
        # lineage — one shape a prefix of the other — which is exactly "same
        # version scheme, different suffix depth": `v#.#.#` and `v#.#.#-wasp`
        # next to a `v#.#.#-wasp#` pin. Then rank by version.
        def related(sh):
            return sh != fam and (sh.startswith(fam) or fam.startswith(sh))
        other = [r for r in rows
                 if related(family(r["tag"])) and not r["unstable"]][:3]
    else:
        other = [r for r in rows if family(r["tag"]) != fam and not r["unstable"]
                 and after and r["date"] and r["date"] > after][:3]
    return newer, other


# `pinned_by.how` values whose COMPANION REPO IS NOT THE AUTHORITY. For these, a newer
# tag and a moved branch head are both noise: the commit is whatever the client's own
# manifest or gitlink names, so nothing in the companion's repo can advance the pin.
# Reporting them as targets is what produced #50, #51, #53 and the full revert in #52.
GOVERNED = {"manifest", "submodule"}


def pin_report(label, repo_url, version, commit, clone_dir, pinned_by=None):
    repo = gh_repo(repo_url)
    pb = pinned_by or {}
    how = pb.get("how")
    p = {"label": label, "repo": repo, "version": version, "commit": commit,
         "pinned_by": pb or None, "pinned_commit_date": None, "clone": None,
         "kind": None, "target": None, "newer_stable": [], "newer_unstable": [],
         "other_families": []}
    if clone_dir.is_dir():
        p["clone"] = {"path": str(clone_dir.relative_to(ROOT)),
                      "head": sh("git", "-C", str(clone_dir), "rev-parse", "HEAD")}
    p["pinned_commit_date"] = commit_date(repo, commit)
    if how in GOVERNED:
        # Deliberately no lookup at all. Not "look and then suppress": the tag list
        # and the branch head are not evidence about this pin, and printing them
        # under a caveat still invites the edit.
        p["kind"] = "governed"
        return p
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
         "mothballed": ch.get("mothballed"),
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
                                        CHAINS / owner / "repos" / k["name"],
                                        k.get("pinned_by")))
        if cl.get("submodule"):
            sm = cl["submodule"]
            r["pins"].append(pin_report(f"submodule:{sm['name']}", sm["repo"],
                                        sm.get("version"), sm["commit"],
                                        CHAINS / owner / "repos" / sm["name"],
                                        sm.get("pinned_by")))

    # A governed companion's only possible mover is the CLIENT tag. Resolve that here,
    # where the client pin's target is already known, and read the authority file at
    # both refs so the report can say whether the pin would actually change.
    cpin = next((p for p in r["pins"] if p["label"] == "client"), None)
    # `authority` runs the other way: a companion governs the CLIENT pin, so the
    # client's own release list is not a candidate list. Plasma is the live trap —
    # reth has shipped 13 tags past the pin and the chain runs none of them, because
    # the template's EXECUTION_TAG decides. Mark it on the client pin, where the
    # mistaken edit would be made.
    governor = next((p for p in r["pins"]
                     if (p.get("pinned_by") or {}).get("how") == "authority"), None)
    if cpin and governor:
        cpin["governed_by_companion"] = governor["label"]
    ctag = (cpin or {}).get("version")
    ctarget = ((cpin or {}).get("target") or {}).get("tag")
    for p in r["pins"]:
        if p["kind"] != "governed":
            continue
        pb = p["pinned_by"] or {}
        path, nm = pb.get("path"), p["repo"].split("/")[-1]
        p["authority"] = {"repo": (cpin or {}).get("repo"), "path": path,
                          "client_tag": ctag, "client_target": ctarget,
                          "at_pin": None, "at_target": None, "moved": None,
                          "located": None}
        if not (cpin and path and ctag):
            continue
        au = p["authority"]            # NOT `a`: that is the argparse namespace
        h = manifest_hits(cpin["repo"], ctag, path, p["commit"], nm, p.get("version"))
        if h is not None:
            au["at_pin"], au["located"] = (h[0] or h[1]), h[2]
        if ctarget:
            h2 = manifest_hits(cpin["repo"], ctarget, path, p["commit"], nm,
                               p.get("version"))
            if h2 is not None:
                # The pin moved iff the client no longer names this sha. When it is
                # gone, show the line under the SAME KEY rather than every line that
                # merely mentions the repo: Linea's pin is `besuCommit = "<sha>"`, and
                # the repo-name lines there are three unrelated plugin versions.
                au["moved"] = not h2[2]
                if not au["moved"]:
                    au["at_target"] = h2[0]
                else:
                    keys = [manifest_key(l) for l in (au["at_pin"] or [])]
                    keys = [k for k in keys if k]
                    same = [l for l in h2[1] if any(manifest_key(l) == k for k in keys)]
                    au["at_target"] = same or h2[1]
                    au["at_target_exact"] = bool(same)

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
    elif r.get("mothballed"):
        mb = r["mothballed"]
        state = (f"live, but MOTHBALLED ({mb.get('how', 'unrecorded')}) — the pin does not "
                 f"move: source was last published at {mb.get('last_source_tag', '?')} and the "
                 f"newer tags have none (SCHEMA.md). Only src_live: can still advance")
        # Probing is the only lever left on a mothballed row, so say when it may next be
        # pulled. SCHEMA.md sets a FOUR-WEEK FLOOR: a weekly observed_at churns the row
        # and the generated tables without telling a reader anything new.
        seen = (r.get("live_probe") or {}).get("observed_at")
        if seen:
            try:
                probed = (seen if isinstance(seen, datetime)
                          else datetime.fromisoformat(str(seen)))
                nxt = (probed.replace(tzinfo=probed.tzinfo or timezone.utc)
                       + timedelta(weeks=4))
                ready = nxt.timestamp() <= now
                state += (f"\n             last probed {str(seen)[:10]}; next probe allowed "
                          f"{nxt.date()} — {'DUE NOW' if ready else 'not yet, hold off'}")
            except (TypeError, ValueError):
                pass
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
        if p.get("governed_by_companion"):
            print(f"    GOVERNED by {p['governed_by_companion']} — the tags below are "
                  f"upstream's releases, NOT candidates: that companion decides which "
                  f"one this chain runs")
        if p["kind"] == "governed":
            pb = p["pinned_by"] or {}
            a = p.get("authority") or {}
            print(f"    GOVERNED by the client's {pb.get('path')} ({pb.get('how')}) — "
                  f"this companion's own tags and branch head CANNOT advance it")
            at_pin, at_tgt, ct = a.get("at_pin"), a.get("at_target"), a.get("client_target")
            if at_pin is None:
                print(f"      could not read {pb.get('path')} at {a.get('client_tag')} "
                      f"— check it by hand")
            else:
                if not a.get("located"):
                    print(f"      NOTE the pinned sha {p['commit'][:12]} is not in "
                          f"{pb.get('path')} at {a.get('client_tag')} — lines below name "
                          f"the repo but are NOT confirmed to be the pin")
                for ln in at_pin[:3]:
                    print(f"      at client {a.get('client_tag')}:  {ln[:110]}")
            if not ct:
                print("      the client tag is current, so this pin cannot move")
            elif at_tgt is None:
                print(f"      client target {ct} exists; could not read the file there")
            elif a.get("moved"):
                print(f"      CHANGED at client target {ct} — THIS PIN MOVES:")
                for ln in at_tgt[:3]:
                    print(f"        {ln[:110]}")
                if not a.get("at_target_exact"):
                    print("        (same-key line not found; the above merely name the "
                          "repo — read the file to confirm the new pin)")
            else:
                print(f"      unchanged at client target {ct} — bump the client, "
                      f"leave this pin alone")
        elif p["kind"] == "tag":
            if t:
                print(f"    NEWER  → {t['tag']} @ {(t['commit'] or '?')[:12]}  [{d(t['date'])}]")
                for n in p["newer_stable"][1:]:
                    print(f"             also newer: {n['tag']}  [{d(n['date'])}]")
            else:
                print("    current — no newer stable tag of this family")
            for n in p["newer_unstable"]:
                print(f"    unstable newer tag: {n['tag']}  [{d(n['date'])}]  (not a pin candidate; read its notes for forks)")
            if p["other_families"] and not t:
                print("    other stable tag shapes — a rename, the upstream series, or a "
                      "different suffix depth. A HINT ABOUT PARENTAGE, NOT A PIN CANDIDATE: "
                      + ", ".join(o["tag"] for o in p["other_families"]))
        elif p["kind"] == "prose":
            print("    prose pin — no ref to follow; read `version` and advance it by hand")
        elif t:
            print(f"    BRANCH {p['ref']} moved → {t['commit'][:12]}  "
                  f"({t.get('ahead_by') or '?'} commits ahead)  [{d(t['date'])}]")
        else:
            print(f"    branch pin — {p['ref']} is still at the pin")
        pb = p["pinned_by"] or {}
        if pb.get("how") == "authority" and t:
            print("    ^ THIS IS THE AUTHORITY over the client pin: its movement is the "
                  "trigger to re-pin the client, not the other way round (SCHEMA.md)")
        elif pb.get("how") == "reference" and t:
            print("    ^ `reference` — cited to document a fact about this repo, not to "
                  "source facts from it. Movement here is not drift for this row")
        elif pb.get("how") == "unrecorded":
            print("    ^ `pinned_by: unrecorded` — nothing here distinguishes drift from "
                  "noise; establish the authority before editing any pin")

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
