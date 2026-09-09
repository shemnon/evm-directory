#!/usr/bin/env python3
"""Re-probe every row's live endpoint and report drift since the pinned block.

`verify.py` closes the loop on `src:` — it re-reads the pinned clone and diffs it
against `chain.yaml`. `src_live:` had no such loop, and it is the one kind of
evidence that rots without anyone touching the repo, because the network keeps
running after the probe. A row goes stale in three ways and no existing gate sees
any of them:

  HALTED   the chain stops producing blocks. Polygon zkEVM did exactly that on
           2026-07-03; it was noticed by hand, weeks late, and only because
           someone happened to re-probe.
  MOVED    the endpoint stops answering, or answers for a different chain id.
           Every `src_live:` on the row is then unciteable — nobody can replay
           the call — while the row still reads as live-verified.
  FORKED   the chain hardforks past the height the row was probed at, so its
           live facts describe a protocol the network no longer runs.

This is NOT a CI gate. It needs the public internet and other people's rate
limits, and a build that goes red when a third party has an outage is a build
nobody reads — the same argument SITE.md already makes for `verify.py
--no-clones`. Run it by hand, or on a schedule, and act on what it prints.

Exit 1 on any finding, so a scheduled run can still be wired to an alert.

What "still on the pinned fork" can and cannot mean here
-------------------------------------------------------
No JSON-RPC method returns a fork name, so this check is a DIFFERENTIAL, not an
assertion. It reads the EIP-marker header fields at the pinned block and at the
head and reports a CHANGE between the two. The baseline is always the chain's own
pinned block, never a hardcoded Ethereum fork ladder — which is what makes it
usable across this dataset. Arc carries `parentBeaconBlockRoot` with no beacon
chain behind it; Polygon zkEVM is a Berlin-era chain in 2026; Hedera and Tron are
not Ethereum-shaped at all. A hardcoded expectation would fire on all of them and
be wrong every time. A differential against the row's own pin fires only when
something actually moved.

The blind spot is stated rather than papered over: the header markers see
Shanghai (`withdrawalsRoot`), Cancun (`blobGasUsed`, `parentBeaconBlockRoot`) and
Prague (`requestsHash`). **Osaka adds no header field, so an Osaka activation is
invisible to this tool** — 15 rows in the dataset declare `baseline_fork: osaka`
and this check cannot confirm any of them. Seeing it needs a state-reading probe
(P256VERIFY at 0x0100) against an archive node at the pinned height, which most
public endpoints will not serve. `--deep` reads the fork-gated system contracts'
code at both heights, which catches a predeploy being upgraded — a thing the
header cannot see at all — and reports `state unavailable` on a pruning endpoint
rather than guessing.
"""
import argparse, json, pathlib, sys, urllib.error, urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from model import ROOT, load, order, name
from verify import provenance

# Header fields introduced by a fork, newest last. Presence is the signal; a field
# that is absent AND a field that is explicitly null both read as "not there",
# because clients disagree about which they emit for a pre-fork block.
HEADER_MARKS = [("withdrawalsRoot",       "4895", "shanghai"),
                ("blobGasUsed",           "4844", "cancun"),
                ("parentBeaconBlockRoot", "4788", "cancun"),
                ("requestsHash",          "7685", "prague")]

# --deep only. Fork-gated system contracts, which are ordinary accounts with code
# and can therefore be diffed by code hash across two heights. Their value is not
# fork detection — `requestsHash` already covers Prague — but catching a predeploy
# whose CODE CHANGED under a row that cites its behaviour.
DEEP_MARKS = [("2935", "0x0000F90827F1C53a10cb7A02335B175320002935"),
              ("4788", "0x000F3df6D732807Ef1319fB7B8bB8522d0Beac02"),
              ("7002", "0x00000961Ef480Eb55e80D19ad83579A64c007002"),
              ("7251", "0x0000BBdDc7CE488642fb579F8B00f3a590007251")]


class RpcError(Exception):
    """The endpoint did not answer, or answered with an error object. Raised
    rather than returned so a dead endpoint cannot be mistaken for a null result:
    `eth_getBlockByNumber` returning null is a FINDING (the pinned block is no
    longer served) and a connection refusal is a different finding entirely."""


def rpc(endpoint, method, params, timeout):
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "EVM-Directory/livecheck"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RpcError(f"HTTP {e.code}")
    except urllib.error.URLError as e:           # DNS, TLS, refused, timeout
        raise RpcError(str(e.reason)[:90])
    except Exception as e:                       # bad JSON, socket timeout
        raise RpcError(f"{type(e).__name__}: {e}"[:90])
    if d.get("error"):
        err = d["error"]
        raise RpcError(str(err.get("message", err) if isinstance(err, dict) else err)[:90])
    return d.get("result")


def num(x):
    """Hex quantity -> int, tolerating decimal strings and ints."""
    if isinstance(x, int): return x
    if isinstance(x, str): return int(x, 16 if x.startswith("0x") else 10)
    raise ValueError(x)


def fingerprint(hdr):
    """The fork-marker header fields this block carries, as a stable string."""
    return "+".join(e for f, e, _ in HEADER_MARKS if hdr.get(f) is not None) or "none"


def age_str(secs):
    if secs < 90:              return f"{secs:.0f}s"
    if secs < 5400:            return f"{secs / 60:.0f}m"
    if secs < 172800:          return f"{secs / 3600:.1f}h"
    return f"{secs / 86400:.1f}d"


def unreachable(chains):
    """Rows this tool structurally cannot check: no endpoint answers, so there is
    nothing to probe. They are listed rather than omitted — a row that silently
    drops out of a liveness report is exactly the failure this tool exists to
    prevent. Such a row may still be marked `dead: abandoned`, on a dark window
    rather than a last block; that is a conclusion drawn from what outlived the
    chain, and no amount of probing will confirm or disturb it."""
    return [s for s, c in chains.items()
            if c["chain"].get("live_state") == "unreachable"]


def check(slug, c, args):
    """Probe one row. Returns (lines to print, findings)."""
    lp, ch = c.get("live_probe") or {}, c["chain"]
    ep, pinned = lp.get("endpoint"), lp.get("observed_at_block")
    state, mb = ch.get("live_state"), ch.get("dead")
    lines, findings = [], []

    def bad(msg):
        findings.append(msg); lines.append(f"  ! {msg}")

    if not isinstance(ep, str) or not ep.startswith("http"):
        # taraxa records "NONE REACHABLE" as the endpoint on purpose. That is a
        # declared footing like `evidence: documented`, not a failure to report.
        lines.append(f"  SKIP    no HTTP endpoint declared ({str(ep)[:48]!r})")
        return lines, findings
    if not isinstance(pinned, int):
        lines.append(f"  SKIP    observed_at_block is not a height ({pinned!r})")
        return lines, findings

    # --- identity: is this still the same network at the same address? ---------
    try:
        cid = num(rpc(ep, "eth_chainId", [], args.timeout))
    except RpcError as e:
        bad(f"UNREACHABLE  {ep} — {e}")
        # a consequence of the finding above, not a second finding
        lines.append("    every src_live: on this row is currently unreplayable")
        return lines, findings
    want = lp.get("chain_id")
    if want is not None and cid != want:
        bad(f"CHAIN ID  endpoint answers {cid}, live_probe declares {want} "
            f"— the endpoint has been repointed")
    else:
        lines.append(f"  identity ok   chain id {cid} @ {ep}")

    # --- the head, and whether it is where this row's live_state says ----------
    try:
        head = rpc(ep, "eth_getBlockByNumber", ["latest", False], args.timeout)
        hn, hts = num(head["number"]), num(head["timestamp"])
    except (RpcError, KeyError, TypeError, ValueError) as e:
        bad(f"NO HEAD   eth_getBlockByNumber(latest) — {e}")
        return lines, findings
    age = (datetime.now(timezone.utc)
           - datetime.fromtimestamp(hts, timezone.utc)).total_seconds()
    delta = hn - pinned
    where = (f"head {hn} ({age_str(age)} old), pinned {pinned}, "
             f"{delta:+d}")

    # The expectation is read off the row, not assumed. `halted` inverts it: for
    # Polygon zkEVM a moving head is the finding, and reporting "stale" there
    # every run would train the reader to ignore this tool.
    if state == "halted":
        # Test the head's AGE, not its distance from the pin. A halted row does not
        # necessarily pin its own last block: Moonbeam pinned the FINALIZED head,
        # and production ran 5,791 blocks past it before stopping, so `head ==
        # pinned` would have reported that row as resumed forever.
        if age <= args.max_age:
            bad(f"RESUMED   {where} — the row says `live_state: halted` but the head "
                f"is {age_str(age)} old; the chain is producing blocks again, and "
                f"its live facts need re-probing at a new height"
                + ("" if not mb else
                   ". This row is marked DEAD: it has started moving again, so its "
                   "`dead:` block is now false and must come off before anything "
                   "else is edited"))
        elif hn < pinned:
            bad(f"BEHIND    {where} — endpoint is below the block this row cites")
        else:
            gap = "" if delta == 0 else (f"; the pin sits {delta} block(s) below "
                                         f"that last block")
            lines.append(f"  frozen ok     {where}, still halted — no block for "
                         f"{age_str(age)}{gap}")
    else:
        if delta < 0:
            bad(f"BEHIND    {where} — the endpoint has not reached the height "
                f"this row's facts were read at")
        elif age > args.max_age:
            bad(f"STALE     {where} — no block for {age_str(age)}; the chain may "
                f"have halted" + ("" if state != "prelaunch" else
                                  " (this is the stand-in testnet, not mainnet)"))
        else:
            tn = " (testnet stand-in)" if state == "prelaunch" else ""
            lines.append(f"  advancing ok  {where}{tn}")

    # --- can the row's live citations still be replayed here? -----------------
    # A src_live: fact pins a block precisely so someone can re-run the call. If
    # the endpoint no longer serves that block, the pin is a promise the dataset
    # can no longer keep, and that is worth knowing before someone tries.
    try:
        old = rpc(ep, "eth_getBlockByNumber", [hex(pinned), False], args.timeout)
        if old is None:
            bad(f"PIN LOST  eth_getBlockByNumber({pinned}) returns null — this "
                f"endpoint no longer serves the block the row's src_live: facts "
                f"were read at")
    except RpcError as e:
        old = None
        bad(f"PIN LOST  the pinned block {pinned} errors here — {e}")

    # --- fork differential: the pinned block's header shape vs the head's ------
    if old:
        was, now = fingerprint(old), fingerprint(head)
        base = c.get("baseline_fork", "?")
        if was != now:
            bad(f"FORKED    header markers changed since the pin: [{was}] -> "
                f"[{now}]; the row declares baseline_fork: {base} and its "
                f"src_live: facts describe the older protocol")
        else:
            lines.append(f"  fork ok       header markers [{was}] unchanged since "
                         f"the pin (baseline_fork: {base})")

    # --- --deep: did a fork-gated predeploy's code change under the row? -------
    if args.deep and old:
        moved, unavailable = [], 0
        for eip, addr in DEEP_MARKS:
            try:
                a = rpc(ep, "eth_getCode", [addr, hex(pinned)], args.timeout)
                b = rpc(ep, "eth_getCode", [addr, "latest"], args.timeout)
            except RpcError:
                unavailable += 1; continue
            if a != b:
                verb = ("gained" if a in (None, "0x") else
                        "lost" if b in (None, "0x") else "changed")
                moved.append(f"EIP-{eip} {verb} code")
        if unavailable == len(DEEP_MARKS):
            lines.append("  deep skip     state at the pinned block is unavailable "
                         "— not an archive endpoint")
        elif moved:
            bad("PREDEPLOY  " + "; ".join(moved) + " between the pinned block and "
                "the head")
        else:
            lines.append(f"  deep ok       {len(DEEP_MARKS) - unavailable} system "
                         f"contract(s) unchanged since the pin")

    # --- dead rows: the clock that is still running is the user's -------------
    # The chain is finished, but a claims window is not. Surfacing it here is the
    # only place a maintenance run would ever see it.
    if mb:
        e, r = mb.get("how"), mb.get("recourse")
        tag = f"{e}, recourse {r}"
        if e == "abandoned":
            tag += (f" (went dark between {mb.get('dark_after')} and "
                    f"{mb.get('dark_before')})")
        dl, today = mb.get("user_deadline"), date.today()
        if dl:
            left = (dl - today).days if isinstance(dl, date) else None
            if left is None:
                lines.append(f"  dead          {tag}; user deadline {dl}")
            elif left < 0:
                lines.append(f"  dead          {tag}; user deadline {dl} PASSED "
                             f"{-left}d ago")
            else:
                lines.append(f"  dead          {tag}; {left}d left for holders to "
                             f"act (until {dl})")
        else:
            lines.append(f"  dead          {tag}")

    # --- prelaunch rows: has the network this row is WAITING for come up? -----
    # A `prelaunch` row probes a stand-in testnet, so nothing above can tell you
    # the thing you actually want to know. This can.
    aw = lp.get("awaiting_endpoint")
    if aw:
        awc = lp.get("awaiting_chain_id")
        try:
            got = num(rpc(aw, "eth_chainId", [], args.timeout))
            bad(f"LAUNCHED  {aw} now answers for chain id {got}"
                + (f" (awaiting {awc})" if awc is not None else "") +
                " — mainnet exists; every src_live: on this row is a TESTNET "
                "observation and must be re-probed against it before "
                "`live_state` moves off prelaunch")
        except RpcError as e:
            lines.append(f"  awaiting ok   {aw} still does not answer "
                         f"({str(e)[:60]}) — it has not launched")
    return lines, findings


def main():
    ap = argparse.ArgumentParser(
        description="Re-probe the live endpoints behind every row's src_live: "
                    "facts and report chains that have halted, moved or forked "
                    "since the block they were pinned at.",
        epilog="Needs the network; deliberately not a CI gate. See SITE.md.")
    ap.add_argument("slugs", nargs="*",
                    help="chains to probe (default: every row with src_live: facts)")
    ap.add_argument("--timeout", type=float, default=20.0,
                    help="per-request timeout in seconds (default 20)")
    ap.add_argument("--max-age", type=float, default=3600.0, metavar="SECS",
                    help="head older than this counts as stale (default 3600). "
                         "`live_state: halted` rows invert it: there a FRESH head "
                         "is the finding, because the row says the chain stopped")
    ap.add_argument("--deep", action="store_true",
                    help="also diff the fork-gated system contracts' code at the "
                         "pinned block against the head; needs an ARCHIVE "
                         "endpoint and degrades to a skip without one")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable findings on stdout, nothing else")
    a = ap.parse_args()

    chains = load()
    if a.slugs:
        unknown = [s for s in a.slugs if s not in chains]
        if unknown:
            print(f"no such chain: {', '.join(unknown)}", file=sys.stderr)
            return 2
        want = [s for s in order(chains) if s in a.slugs]
    else:
        # The selection is "rows that make live claims", not "rows that are live":
        # a halted or prelaunch row still carries src_live: facts and is exactly
        # where this tool earns its keep.
        want = [s for s in order(chains)
                if provenance(chains[s])["src_live"] and (chains[s].get("live_probe"))]

    if not a.json:
        print(f"probing {len(want)} row(s) with src_live: facts — network required, "
              f"not a CI gate")
        print(f"  advancing/frozen per `live_state`, endpoint identity, pinned-block "
              f"replay,\n  and a header fork-marker differential against the row's "
              f"own pin (Osaka is\n  invisible to that — see the module docstring)")

    report, total, closed = {}, 0, []
    for slug in want:
        c = chains[slug]
        lines, findings = check(slug, c, a)
        report[slug] = findings
        total += len(findings)
        if c["chain"].get("dead") and lines and not lines[0].startswith("  SKIP"):
            closed.append(slug)
        if not a.json:
            st = c["chain"].get("live_state") or ("live" if c["chain"].get("live") else "?")
            tag = "  [dead]" if c["chain"].get("dead") else ""
            print(f"\n{slug}  ({name(c)}, live_state: {st}){tag}")
            for l in lines: print(l)

    if a.json:
        json.dump({"findings": {k: v for k, v in report.items() if v},
                   "clean": [k for k, v in report.items() if not v],
                   "dead": closed,
                   "unreachable": unreachable(chains)},
                  sys.stdout, indent=2)
        print()
    else:
        print(f"\n{'=' * 60}")
        dirty = [k for k, v in report.items() if v]
        if dirty:
            print(f"LIVE DRIFT: {total} finding(s) across {len(dirty)} row(s): "
                  f"{', '.join(dirty)}")
            print("  a finding here is a fact in chain.yaml that the network no "
                  "longer backs.\n  Re-probe the row and re-state it; do not just "
                  "edit the block number.")
        else:
            live = len(want) - len(closed)
            print(f"clean — {live} live row(s) still advancing at the endpoint and "
                  f"fork they were\n  pinned against"
                  + (f", and {len(closed)} dead row(s) still frozen"
                     if closed else ""))
        if closed:
            print(f"\ndead (checked for a restart only, not maintained): "
                  f"{', '.join(closed)}")
        un = unreachable(chains)
        if un:
            print(f"NOT PROBED, no endpoint answers: {', '.join(un)}")
            closed_mia = [s for s in un if (chains[s]["chain"].get("dead") or {})
                          .get("how") == "abandoned"]
            if closed_mia:
                print(f"  marked `dead: abandoned` on a dark window rather than a "
                      f"last block ({', '.join(closed_mia)}) — there is no endpoint "
                      f"left to probe, so nothing here can change that. SCHEMA.md.")
            if set(un) - set(closed_mia):
                print("  still open: unreachable, and no ending established. SCHEMA.md.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
