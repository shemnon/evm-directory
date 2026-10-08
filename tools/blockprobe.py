#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Re-sample every row's block metrics and report drift from what `chain.yaml` records.

`block_metrics:` is the one axis whose values are expected to move while nobody
touches the repo. A precompile either exists or does not; a block gas limit is a
number the network's own producers choose, and on a `mutability: adjustable` row
it can be different by the next block. So the axis stores a pair — what the code
sets (`verdict:`) and what the network ran (`observed:`) — and this tool is the
loop that keeps the second half honest, the way `verify.py` keeps `src:` honest
and `livecheck.py` keeps a row's liveness honest.

The drift it finds is not noise. Three kinds have already turned up:

  STALE     the recorded observation is simply old. Rise was recorded at
            1,500,000,000 and runs 2,250,000,000 — a 50% capacity change that
            no source diff would ever surface, because no source changed.
  SENTINEL  the field does not carry a limit at all. The zkStack rows report
            `gasLimit` 2^50, which is not a budget but "unbounded" spelled in
            the header's units. Averaged into a throughput column it produces
            350 Tgas/s and silently ruins every comparison on the page.
  CLASSED   one chain runs more than one kind of block. Hyperliquid interleaves
            a 1s small block with a 60s large block and the two carry DIFFERENT
            gas limits, so "the" gas limit is a category error — a single probe
            returns whichever class it happened to land on.

Block time is measured by two-point sampling, the method the kaia and sei rows
already used by hand: read the head, read the block `--span` behind it, divide
the timestamp delta by the span. It is deliberately not an average of recent
blocks — a long span smooths over the single slow block that an average would
chase, and it is reproducible by anyone against an archive node, which an
average over "recent" blocks is not.

This is NOT a CI gate, for the reason livecheck.py gives at length: it needs the
public internet and other people's rate limits, and a build that goes red during
someone else's outage is a build nobody reads. Run it by hand or on a schedule.

Exit 1 on any drift, so a scheduled run can be wired to an alert.
"""
import argparse, concurrent.futures as cf, json, pathlib, re, sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from model import ROOT, load, order, short
from livecheck import RpcError, num, rpc

UA_NOTE = "EVM-Directory/blockprobe"

# A `gasLimit` that is really a flag. 2^50 is what the zkStack rows report and it
# is not a capacity — the batch is bounded by prover circuits, recorded on the
# proofs axis, not by anything in this header field. Kept as an explicit set
# rather than a magnitude threshold: megaeth's 10,000,000,000 is a real limit a
# real block fills, and no cutoff separates the two without guessing.
SENTINELS = {1 << 50}

# The chains whose endpoint answers for a network other than the row's subject,
# or not at all. Recorded here so a skip is a declaration rather than a silent
# absence from the report.
NO_PROBE = {
    "taraxa": "no endpoint resolves — every documented host's DNS fails",
}


def is_sentinel(v):
    return isinstance(v, int) and v in SENTINELS


def fetch(endpoint, slug, span, window, timeout):
    """Everything this tool needs from one chain, in as few calls as possible.

    Returns a dict of findings; `error` set means nothing else is trustworthy."""
    out = {"slug": slug, "endpoint": endpoint}
    try:
        head = rpc(endpoint, "eth_getBlockByNumber", ["latest", False], timeout)
    except RpcError as e:
        out["error"] = str(e)
        return out
    if not head:
        out["error"] = "latest returned null"
        return out

    n = num(head["number"])
    out.update(head=n, timestamp=num(head["timestamp"]),
               gas_limit=num(head["gasLimit"]), gas_used=num(head["gasUsed"]))
    for k, f in (("blob_gas_used", "blobGasUsed"), ("excess_blob_gas", "excessBlobGas"),
                 ("base_fee", "baseFeePerGas"), ("block_bytes", "size")):
        if head.get(f) is not None:
            out[k] = num(head[f])

    # --- block time, two-point -------------------------------------------
    # Shrink the span rather than skip the measurement: a chain 900 blocks old
    # still has a cadence, and refusing to measure it would read as "unknown"
    # when the answer is available at lower precision.
    for s in (span, span // 10, span // 100, 10):
        if s >= 10 and n > s:
            try:
                old = rpc(endpoint, "eth_getBlockByNumber", [hex(n - s), False], timeout)
                if old:
                    dt = num(head["timestamp"]) - num(old["timestamp"])
                    out.update(span_blocks=s, span_seconds=dt,
                               block_time_ms=round(dt * 1000 / s, 1),
                               span_from=n - s, span_gas_limit=num(old["gasLimit"]))
                    break
            except RpcError as e:
                out["block_time_error"] = str(e)
                break

    # --- more than one class of block? -----------------------------------
    # A window of CONSECUTIVE blocks, because the question is whether the limit
    # varies between adjacent blocks rather than over time. Two values here is
    # the Hyperliquid signature; a slow drift of near-identical values is the
    # signature of an adjustable limit being nudged, which is a different fact.
    if window:
        seen = {}
        for b in range(n, max(n - window, 0), -1):
            try:
                blk = rpc(endpoint, "eth_getBlockByNumber", [hex(b), False], timeout)
            except RpcError:
                break
            if blk:
                seen.setdefault(num(blk["gasLimit"]), []).append(b)
        if len(seen) > 1:
            out["classes"] = {str(k): {"blocks": len(v), "example": v[0]}
                              for k, v in sorted(seen.items())}
        out["window_blocks"] = window

    # --- the node's own enumeration --------------------------------------
    # EIP-7910. Where it answers it is the strongest evidence on this axis:
    # the blob schedule straight from the node rather than inferred from a
    # header field that only shows what the last block happened to use.
    try:
        cfg = rpc(endpoint, "eth_config", [], timeout)
        cur = cfg.get("current", cfg) if isinstance(cfg, dict) else None
        if isinstance(cur, dict):
            bs = cur.get("blobSchedule")
            if isinstance(bs, dict):
                out["blob_target"] = bs.get("target")
                out["blob_max"] = bs.get("max")
            elif "blobSchedule" in cur:
                out["blob_schedule"] = None      # explicitly null: no blobs here
            out["fork_id"] = cur.get("forkId")
    except RpcError:
        pass                                      # absent on most rows; not a finding
    return out


# --------------------------------------------------------------------------
# comparing against what the row records
# --------------------------------------------------------------------------

def recorded(c):
    """The row's `block_metrics:` observations, flattened to {key: value}."""
    bm = c.get("block_metrics") or {}
    return {k: v for k, v in bm.items() if isinstance(v, dict)}


def drift(c, got):
    """What the network says versus what the row records. Only `observed:` is
    compared — a `verdict:` disagreeing with the network is not drift, it is the
    finding the axis exists to publish (a code default the producers overrode)."""
    out = []
    rec = recorded(c)
    pairs = [("block_gas_limit", got.get("gas_limit"), 0),
             ("block_time", got.get("block_time_ms"), 0.08)]
    for key, live, tol in pairs:
        if live is None:
            continue
        e = rec.get(key)
        if not e or e.get("observed") is None:
            out.append((key, None, live, "not recorded"))
            continue
        was = e["observed"]
        if tol:                                   # cadence is measured, not declared
            if was and abs(live - was) / max(was, 1) > tol:
                out.append((key, was, live, f"moved >{tol:.0%}"))
        elif was != live:
            out.append((key, was, live, "changed"))
    for key, live in (("blob_count", got.get("blob_max")),):
        if live is None:
            continue
        e = rec.get(key)
        if not e or e.get("observed") is None:
            out.append((key, None, live, "not recorded"))
        elif e["observed"] != live:
            out.append((key, e["observed"], live, "changed"))
    return out


# --------------------------------------------------------------------------
# write-back
# --------------------------------------------------------------------------

# Surgical, line-level, and deliberately not a YAML round-trip. chain.yaml is
# hand-formatted — block scalars, aligned inline maps, comments that carry real
# argument — and PyYAML's dumper would reflow every one of them, turning a
# three-field refresh into a whole-file diff nobody can review. So the writer
# edits only the lines it owns, inside the one block it is addressing, and fails
# loudly rather than guessing when the shape is not what it expects.
# `src_live` is in this list and that is load-bearing. The citation ENCODES the
# heights it was taken at, so refreshing `observed_at_block` without rewriting it
# leaves a citation pointing at one block and a fact claiming another — a row that
# still reads as live-verified while nobody can replay the call that verified it.
# verify.py rejects a src_live with no `@ <block>`; nothing but this list stops one
# whose block is merely wrong.
OBSERVED_KEYS = ("observed", "observed_at_block", "observed_at", "src_live")


def patch(text, key, values):
    """Replace the `observed*:` lines of `block_metrics.<key>`. Returns new text,
    or None if the block is absent or has no observed lines to update."""
    m = re.search(rf"^block_metrics:\n(?:.*\n)*?^  {re.escape(key)}:\n", text, re.M)
    if not m:
        return None
    start = m.end()
    # the entry runs until the next key at the same (2-space) indent, or EOF
    nxt = re.search(r"^  \S", text[start:], re.M)
    end = start + (nxt.start() if nxt else len(text) - start)
    body, new = text[start:end], text[start:end]
    for f in OBSERVED_KEYS:
        if f not in values or values[f] is None:
            continue
        v = values[f]
        # A citation is a string containing `:` and `->`, which bare YAML would read
        # as a mapping. Numbers and dates stay unquoted, as the hand-written rows have
        # them, so a refresh does not restyle lines it is not changing.
        if isinstance(v, str) and not re.fullmatch(r"[\d.\-]+", v):
            if '"' in v:
                raise SystemExit(f"refusing to write a citation containing a quote: {v}")
            v = f'"{v}"'
        line = re.search(rf"^(    {re.escape(f)}:)[ \t]*(.*)$", new, re.M)
        if line:
            new = new[:line.start()] + f"{line.group(1)} {v}" + new[line.end():]
    return text[:start] + new + text[end:] if new != body else None


def write_back(slug, updates, quiet):
    f = ROOT / "chains" / slug / "chain.yaml"
    text = original = f.read_text()
    touched = []
    for key, values in updates.items():
        out = patch(text, key, values)
        if out:
            text, _ = out, touched.append(key)
    if text != original:
        f.write_text(text)
        if not quiet:
            print(f"  wrote {slug}: {', '.join(touched)}")
    return bool(touched)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Re-sample block metrics from every row's live endpoint.",
        epilog="Reports drift by default; --write updates the observed values in place.")
    ap.add_argument("rows", nargs="*", help="slugs to probe (default: all with an endpoint)")
    ap.add_argument("--write", action="store_true",
                    help="update observed / observed_at_block / observed_at in chain.yaml")
    ap.add_argument("--span", type=int, default=10000,
                    help="blocks between the two block-time samples (default 10000)")
    ap.add_argument("--window", type=int, default=0,
                    help="also read N consecutive blocks to detect multiple block classes")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--json", metavar="FILE", help="write the raw probe to FILE")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()

    chains = load()
    want = set(a.rows) if a.rows else None
    if want and (bad := want - set(chains)):
        print(f"no such row: {', '.join(sorted(bad))}", file=sys.stderr)
        return 2

    targets = []
    for s in order(chains):
        if want and s not in want:
            continue
        if s in NO_PROBE:
            if not a.quiet:
                print(f"{short(s):18} SKIP  {NO_PROBE[s]}")
            continue
        ep = (chains[s].get("live_probe") or {}).get("endpoint")
        if ep and ep.startswith("http"):
            targets.append((s, ep))

    results = {}
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(fetch, ep, s, a.span, a.window, a.timeout): s
                for s, ep in targets}
        for fu in cf.as_completed(futs):
            r = fu.result()
            results[r["slug"]] = r

    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {"probed_at": date.today().isoformat(), "results": results}, indent=1))

    findings = 0
    today = date.today().isoformat()
    for s, _ in targets:
        r = results.get(s) or {}
        if r.get("error"):
            print(f"{short(s):18} UNREACHABLE  {r['error']}")
            findings += 1
            continue
        gl, bt = r.get("gas_limit"), r.get("block_time_ms")
        tag = "  SENTINEL" if is_sentinel(gl) else ""
        if r.get("classes"):
            tag += f"  CLASSED {len(r['classes'])} limits in {r['window_blocks']} blocks"
        if not a.quiet:
            print(f"{short(s):18} @{r['head']:<12,} gas_limit {gl:>18,}"
                  f"  block_time {bt if bt is not None else '?':>9} ms{tag}")
        for key, was, now, why in drift(chains[s], r):
            findings += 1
            print(f"  {'DRIFT':<6} {key:16} {why:14} "
                  f"recorded {was if was is not None else '—'} -> live {now}")

        if a.write:
            # Each citation is rebuilt from the probe that produced the number beside
            # it, in the same form the hand-written rows use, so a refreshed row is
            # indistinguishable from an original one and stays replayable.
            upd = {}
            if gl is not None:
                upd["block_gas_limit"] = {
                    "observed": gl, "observed_at_block": r["head"],
                    "observed_at": today,
                    "src_live": f"eth_getBlockByNumber @ {r['head']} -> "
                                f"gasLimit {hex(gl)}"}
            if bt is not None and r.get("span_from") is not None:
                upd["block_time"] = {
                    "observed": bt, "observed_at_block": r["head"],
                    "observed_at": today,
                    "src_live": f"eth_getBlockByNumber @ {r['head']} vs "
                                f"{r['span_from']} -> {r['span_seconds']}s / "
                                f"{r['span_blocks']} blocks"}
            if r.get("blob_max") is not None:
                upd["blob_count"] = {
                    "observed": r["blob_max"], "observed_at_block": r["head"],
                    "observed_at": today,
                    "src_live": f"eth_config @ {r['head']} -> blobSchedule.max "
                                f"{r['blob_max']}"}
            write_back(s, upd, a.quiet)

    print(f"\n{len(targets)} rows probed, {findings} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
