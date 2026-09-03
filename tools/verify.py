#!/usr/bin/env python3
"""Re-extract facts from the pinned clones and diff them against chain.yaml.

The dataset's whole claim is "from source, not docs" — but facts reach chain.yaml
by a human reading a file once. This closes that loop: it re-reads the source and
reports both directions of drift.

  MISSING  declared in chain.yaml, not found in source  (transcription error)
  UNLISTED found in source, not declared in chain.yaml  (coverage gap — worse)

Rows with `chain.evidence: documented` have no client to clone, so there is nothing
to re-extract; they are reported SKIP and are not drift. Every row also gets a
provenance tally (src / src_live / src_doc / none), because the aggregate tables
merge the three kinds and the mix is invisible there by design.

Exit 1 on any drift. Run after `tools/clone.sh`.
"""
import pathlib, re, sys, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAINNET_STD = set(range(0x01, 0x12)) | {0x100}   # 0x01-0x11 plus P256VERIFY

# Chains whose BASE precompiles come from a dependency rather than this repo:
# coreth/subnet-evm consume ava-labs/libevm, so 0x01-0x11 are not in the tree.
EXTERNAL_BASE = {"avalanche-c", "avalanche-subnet"}

def repo(slug, chain=None):
    """The clone holding this row's evidence. Rows may carry companion repos, and
    rows with client.shared_with borrow their ancestor's clone."""
    if chain:
        shared = chain.get("client", {}).get("shared_with")
        if shared: slug = shared
    d = ROOT / "chains" / slug / "repos"
    if not d.exists(): return None
    dirs = [p for p in d.iterdir() if p.is_dir()]
    if chain:
        want = chain["client"]["repo"].rstrip("/").split("/")[-1]
        for p in dirs:
            if p.name == want: return p
    return next(iter(sorted(dirs)), None)

def text(slug, rel, chain=None):
    p = repo(slug, chain)
    f = p / rel if p else None
    return f.read_text(errors="replace") if f and f.exists() else ""

def block(s, start, end="\n}"):
    i = s.find(start)
    if i < 0: return ""
    j = s.find(end, i)
    return s[i:j if j > 0 else len(s)]

def go_addrs(s):
    """Parse geth-style address literals into ints."""
    out = set()
    for m in re.finditer(r"BytesToAddress\(\[\]byte\{([^}]*)\}\)", s):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        try: out.add(int("".join(f"{int(p, 0):02x}" for p in parts), 16))
        except ValueError: pass
    for m in re.finditer(r'HexToAddress\("(0x[0-9a-fA-F]+)"\)', s):
        out.add(int(m.group(1), 16))
    return out

# ---- per-chain extractors: return the LIVE precompile address set ----------
def ex_ethereum():
    return go_addrs(block(text("ethereum", "core/vm/contracts.go"),
                          "var PrecompiledContractsOsaka = "))
def ex_opstack():
    return go_addrs(block(text("op-stack", "core/vm/contracts.go"),
                          "var PrecompiledContractsJovian = "))
def ex_bnb():
    return go_addrs(block(text("bnb", "core/vm/contracts.go"),
                          "var PrecompiledContractsOsaka = "))
def consts(s):
    """name -> int for `var Foo = common.BytesToAddress(...)` / HexToAddress(...)."""
    out = {}
    for m in re.finditer(r"(\w+)\s*=\s*common\.(?:Bytes|Hex)ToAddress\(([^\n]*?)\)\s*$",
                         s, re.M):
        a = go_addrs(m.group(0))          # feed the whole match, not a reconstruction
        if a: out[m.group(1)] = next(iter(a))
    return out

def resolve(blk, names):
    """Addresses in a map literal, whether written as literals or named constants."""
    a = go_addrs(blk)
    for n, v in names.items():
        if re.search(rf"\b{re.escape(n)}\s*:", blk): a.add(v)
    return a

def ex_avalanche_c():
    s = text("avalanche-c", "params/hooks_libevm.go")
    na = text("avalanche-c", "nativeasset/contract.go")
    names = consts(s) | consts(na)
    a = resolve(block(s, "var PrecompiledContractsGranite = "), names)
    a |= go_addrs(na)
    a |= go_addrs(text("avalanche-c", "precompile/contracts/warp/module.go"))
    return {x for x in a if x > 0xff or x in MAINNET_STD}

def ex_avalanche_subnet():
    s = text("avalanche-subnet", "params/hooks_libevm.go")
    a = resolve(block(s, "var PrecompiledContractsGranite = "), consts(s))
    p = repo("avalanche-subnet")
    if p:
        for m in (p / "precompile" / "contracts").glob("*/module.go"):
            a |= go_addrs(m.read_text())
    return a
def ex_tron():
    s = text("tron", "actuator/src/main/java/org/tron/core/vm/PrecompiledContracts.java")
    return {int(m.group(2), 16) for m in
            re.finditer(r"(\w+Addr)\s*=\s*new DataWord\(\s*\"([0-9a-fA-F]{64})\"\s*\)", s)}
def ex_worldchain():
    return set()   # runs stock OP Stack execution; no precompiles of its own
def ex_optimism():
    return set()   # adds nothing; evidence is op-stack's
def ex_arbitrum():
    return go_addrs(text("arbitrum", "go-ethereum/core/types/arbitrum_signer.go"))
def ex_polygon():
    return go_addrs(block(text("polygon", "core/vm/contracts.go"),
                          "var PrecompiledContractsChicago = "))
def ex_opbnb():
    # this client stops at Fjord — that IS its live set
    return go_addrs(block(text("opbnb", "core/vm/contracts.go"),
                          "var PrecompiledContractsFjord = "))
def ex_base():
    """Rust: `pub const ADDRESS: Address = address!("..")`. The B-20 dynamic range is
    a predicate, not an address, so it is deliberately not enumerated here."""
    p = repo("base", {"client": {"repo": "https://github.com/base/base"}})
    out = set()
    if p:
        for f in (p / "crates" / "common" / "precompiles" / "src").rglob("*.rs"):
            for m in re.finditer(r'pub const ADDRESS: Address = address!\("(0x)?([0-9a-fA-F]{40})"\)',
                                 f.read_text(errors="replace")):
                out.add(int(m.group(2), 16))
    return out

EXTRACT = {"ethereum": ex_ethereum, "op-stack": ex_opstack, "bnb": ex_bnb,
           "avalanche-c": ex_avalanche_c, "avalanche-subnet": ex_avalanche_subnet,
           "tron": ex_tron, "worldchain": ex_worldchain, "optimism": ex_optimism,
           "arbitrum": ex_arbitrum, "polygon": ex_polygon, "opbnb": ex_opbnb,
           "base": ex_base}

# A DIRECTORY, not a file list. The hand-maintained list of files failed open the
# same way the extension allowlist did: op-geth declares PostExecTxType = 0x7D in
# core/types/post_exec_tx.go, which was not on the list, so 0x7D was never reported
# UNLISTED and the coverage gap in op-stack's tx_types went unnoticed. Globbing the
# directory means a new type in a new file is caught by default.
TXTYPE_DIRS = {
    "ethereum": "core/types", "bnb": "core/types", "op-stack": "core/types",
    "polygon": "core/types", "opbnb": "core/types",
    "arbitrum": "go-ethereum/core/types",
    "avalanche-c": None, "avalanche-subnet": None, "tron": None, "worldchain": None,
    "optimism": None, "base": None,
}
def ex_txtypes(slug, chain=None):
    d = TXTYPE_DIRS.get(slug)
    if not d: return set()
    r = repo(slug, chain)
    p = (r / d) if r else None
    if not p or not p.is_dir(): return set()
    out = set()
    for f in sorted(p.glob("*.go")):
        for m in re.finditer(r"TxType\s*=\s*(0x[0-9a-fA-F]+)",
                             f.read_text(errors="replace")):
            out.add(int(m.group(1), 16))
    return out

PROV_SECTIONS = ["precompiles", "tx_types", "system_contracts", "eips",
                 "non_evm_transactions", "system_transactions"]

def provenance(c):
    """Tally how each fact in this row is evidenced. The generated tables merge
    source, docs and live probes without distinction (SCHEMA.md, 'Mixing in the
    aggregate tables'), so this counter is the only place the ratio is visible."""
    t = {"src": 0, "src_live": 0, "src_doc": 0, "none": 0}
    for sec in PROV_SECTIONS:
        d = c.get(sec) or {}
        if not isinstance(d, dict): continue
        for v in d.values():
            if not isinstance(v, dict): continue
            for k in ("src", "src_live", "src_doc"):
                if k in v: t[k] += 1; break
            else: t["none"] += 1
    return t

# An extension ALLOWLIST was the wrong design: every new chain brings a new language,
# and a citation in an unlisted one was silently accepted rather than checked. That hole
# was found twice — first .sol (25 op-stack citations), then .yul/.toml/.cpp/.hpp, which
# left 27 of Monad's 34 citations unverified. Match any dotted extension instead, so a
# new language is checked by default rather than trusted by default. Requiring the
# extension to start with a letter keeps version strings ("v1.2.3", "0.153.14") out.
CITE = re.compile(r"([\w./\-]+\.[a-z][a-z0-9]{0,5})(?::([\w.\-]+))?")
LINEREF = re.compile(r"^\d+(?:-\d+)?$")

def roots(slug, chain):
    """Every clone this row may cite: its own, plus companions. Citations may be
    written with a repo-name prefix (`optimism/packages/...`) to disambiguate which
    companion they mean, so each path is tried both as-is and with that prefix
    stripped against the matching clone."""
    shared = (chain.get("client") or {}).get("shared_with")
    out = []
    for sl in ([shared] if shared else []) + [slug]:
        d = ROOT / "chains" / sl / "repos"
        if d.exists(): out += [q for q in sorted(d.iterdir()) if q.is_dir()]
    return out

def resolve_cite(path, rs):
    """Path against any clone, honouring the repo-name-prefix convention.
    (Distinct from resolve() above, which resolves Go address constants.)"""
    for r in rs:
        if (r / path).exists(): return r / path
    head, _, rest = path.partition("/")
    for r in rs:
        if r.name == head and rest and (r / rest).exists(): return r / rest
    return None

def check_citations(raw, rs):
    """The evidence rule, actually enforced. `src:` must resolve to a real file AND
    its :suffix must check out — a symbol must appear in that file, a line number
    must be within it. File-existence alone let three bad citations through: a stale
    line number, a path relative to the wrong directory, and a sibling that was one
    directory up. Every path in a comma-separated citation is checked, not just the
    first, which is how the second of those survived."""
    bad, nsym, nline, nopath = [], 0, 0, 0
    for m in re.finditer(r"(?<![_\w])src: (.+)", raw):
        found = CITE.findall(m.group(1))
        if not found: nopath += 1      # prose or a bare directory — nothing to resolve
        for path, ref in found:
            f = resolve_cite(path, rs)
            if f is None:
                bad.append(f"BAD SRC   {path} does not exist in any pinned clone"); continue
            if not ref: continue
            body = f.read_text(errors="replace")
            if LINEREF.match(ref):
                n = body.count("\n") + 1
                if int(ref.split("-")[-1]) > n:
                    bad.append(f"BAD LINE  {path}:{ref} is past EOF ({n} lines)")
                else: nline += 1
            elif re.search(rf"\b{re.escape(ref.split('.')[-1])}\b", body):
                nsym += 1
            else:
                bad.append(f"BAD SYM   '{ref}' does not appear in {path}")
    return bad, nsym, nline, nopath

def check_live(raw):
    """A live claim without a block height is unreproducible AND unverifiable."""
    return [f"UNPINNED  src_live has no block height: {m.group(1)[:60]}"
            for m in re.finditer(r"src_live: [\"']?([^\n\"']+)", raw)
            if "@" not in m.group(1)]

AUTHORIZES = {"protocol", "account_code", "never"}
KEY_BINDING = {"derived", "declared", "account_code"}

def check_tx_auth(c):
    """Validate the tx_authorization vocabulary. Exists because `authorizes: no` is a
    TRAP: YAML 1.1 parses a bare `no` as the boolean False, so the value silently loads
    as neither the string it looks like nor an error. The baseline row shipped with
    exactly that bug. The legal value is `never`."""
    out = []
    ta = c.get("tx_authorization")
    if not isinstance(ta, dict): return out
    kb = ta.get("key_binding")
    if kb is not None and kb not in KEY_BINDING:
        out.append(f"BAD AUTH  key_binding {kb!r} not in {sorted(KEY_BINDING)}")
    for name, v in (ta.get("schemes") or {}).items():
        if not isinstance(v, dict): continue
        a = v.get("authorizes")
        if isinstance(a, bool):
            out.append(f"BAD AUTH  {name}: authorizes is the BOOLEAN {a} — YAML 1.1 "
                       f"read a bare yes/no. Write `never` (unquoted is fine).")
        elif a is not None and a not in AUTHORIZES:
            out.append(f"BAD AUTH  {name}: authorizes {a!r} not in {sorted(AUTHORIZES)}")
        if "precompile" not in v:
            out.append(f"BAD AUTH  {name}: no `precompile:` — state the paired "
                       f"verifier's address or `none`; the pairing is the point")
    return out

def declared(c, section):
    return {int(k, 16): v for k, v in (c.get(section) or {}).items()
            if isinstance(k, str) and k.startswith("0x") and isinstance(v, dict)}

def parse_present(spec):
    """`precompiles.base_map.present` -> set of ints. Mirrors model._parse_present."""
    if spec in (None, ""): return set()
    parts = spec if isinstance(spec, list) else str(spec).split(",")
    out = set()
    for p in parts:
        p = str(p).strip()
        if not p: continue
        if "-" in p[2:]:
            lo, hi = p.split("-", 1)
            out |= set(range(int(lo, 16), int(hi, 16) + 1))
        else:
            out.add(int(p, 16))
    return out

def main():
    problems = 0
    totals = {"src": 0, "src_live": 0, "src_doc": 0, "none": 0}
    skipped, unextracted = [], []
    for f in sorted((ROOT / "chains").glob("*/chain.yaml")):
        slug = f.parent.name
        c = yaml.safe_load(f.read_text())
        cl = c.get("client") or {}
        documented = c["chain"].get("evidence") == "documented"

        prov = provenance(c)
        for k in totals: totals[k] += prov[k]
        tally = "  ".join(f"{k}={v}" for k, v in prov.items() if v)

        # opcode deltas must be keyed `op:` — the grid, the chain-page anchors and
        # the silent-divergence index all read that key and nothing else.
        for kind in ("added", "removed", "modified", "pending", "tombstoned"):
            for e in (c.get("opcodes") or {}).get(kind) or []:
                if isinstance(e, dict) and "op" not in e:
                    print(f"\n{slug}")
                    print(f"  BAD KEY  opcodes.{kind} entry "
                          f"'{e.get('name', e.get('opcode', '?'))}' has no `op:` key"
                          + (f" (found `opcode: {e['opcode']}`)" if "opcode" in e else ""))
                    problems += 1

        if documented:
            # No client exists to clone, so nothing can be re-extracted. This is a
            # declared footing, not a failure: a permanently-red build is one nobody
            # reads, which would degrade verification for the rows that CAN be checked.
            lp = c.get("live_probe") or {}
            at = lp.get("observed_at_block")
            for b in check_live(f.read_text()) + check_tx_auth(c):
                print(f"  {b}"); problems += 1
            print(f"\n{slug}  (documented — no public client)")
            print(f"  SKIP    nothing to re-extract"
                  + (f"; live probes pinned at block {at}" if at else ""))
            if not at and prov["src_live"]:
                print("  ! src_live present but live_probe.observed_at_block is unset "
                      "— unpinned live claims are not reproducible"); problems += 1
            print(f"  evidence  {tally or 'no facts recorded'}")
            skipped.append(slug)
            continue

        print(f"\n{slug}  ({cl.get('name', '?')} {cl.get('version', '?')})")

        r = repo(slug, c)
        if r is None:
            print("  ! no clone — run tools/clone.sh"); problems += 1; continue
        import subprocess
        head = subprocess.run(["git", "-C", str(r), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        if head != c["client"]["commit"]:
            print(f"  ! PIN MISMATCH: clone {head[:8]}, chain.yaml {c['client']['commit'][:8]}")
            problems += 1
        else:
            print(f"  pin ok  {head[:8]}")

        # --- every non-baseline row must declare its mainnet base sets, even the
        # ones with no extractor (the source cross-check below needs one; this
        # does not) ---
        if c["chain"].get("role") != "baseline":
            if (c.get("precompiles") or {}).get("base_map") is None:
                print("  ! NO BASE MAP — 0x01-0x11 coverage is not declared "
                      "(add precompiles.base_map)"); problems += 1
            if (c.get("tx_types") or {}).get("envelope") is None:
                print("  ! NO ENVELOPE — 0x00-0x04 coverage is not declared "
                      "(add tx_types.envelope)"); problems += 1

        # --- precompiles, both directions ---
        # A new row has no extractor until someone writes one. That is a real gap —
        # its precompile list is taken on trust — so it is reported loudly and
        # tallied at the end, but it is not drift: failing here would make the build
        # red for every new chain and block the work that closes the gap.
        ex = EXTRACT.get(slug)
        if ex is None:
            print("  ! NO EXTRACTOR — precompile list NOT cross-checked against source")
            unextracted.append(slug)
            bad, nsym, nline, nopath = check_citations(f.read_text(), roots(slug, c))
            bad += check_live(f.read_text())
            for b in bad:
                print(f"  {b}"); problems += 1
            if not bad and (nsym or nline):
                print(f"  citations ok    {nsym} symbol(s) confirmed, "
                      f"{nline} line ref(s) in range"
                      + (f", {nopath} citing no path" if nopath else ""))
            print(f"  evidence  {tally}")
            continue
        found, dec = ex(), declared(c, "precompiles")
        # a dynamic range is a predicate, not an address; nothing to enumerate
        dyn = (c.get("precompiles") or {}).get("dynamic_range")
        # entries a chain declares as removed/pending are expected NOT to be in source
        expect = {a for a, v in dec.items()
                  if v.get("status") in (None, "added", "modified", "tombstoned", "inherited")
                  # inherited from a stack ancestor: verified in the ancestor's repo
                  and not v.get("inherited_from")}
        if slug in EXTERNAL_BASE:
            expect = {a for a in expect if a not in set(range(0x01, 0x12))}
        missing = {a for a in expect if a not in found}
        # Some sources define precompiles and system contracts in one file (Arbitrum's
        # arbitrum_signer.go), so the extractor cannot tell the categories apart.
        # Check membership in either; category discipline is a review concern, not
        # something the extractor can adjudicate.
        elsewhere = set(declared(c, "system_contracts"))
        unlisted = {a for a in found if a not in dec and a not in elsewhere
                    and a not in MAINNET_STD}
        for a in sorted(missing):
            print(f"  MISSING  precompile 0x{a:02x} declared but not found in source"); problems += 1
        for a in sorted(unlisted):
            print(f"  UNLISTED precompile 0x{a:02x} in source but not in chain.yaml"); problems += 1
        if not missing and not unlisted:
            extra = "  +1 dynamic range (not enumerable)" if dyn else ""
            print(f"  precompiles ok  ({len(found)} in source, {len(dec)} declared){extra}")

        # --- base map: cross-check `present` against the extracted map ---
        bm = (c.get("precompiles") or {}).get("base_map")
        BASE = set(range(0x01, 0x12))
        if (bm is not None and ex is not None and (found & BASE)
              and slug not in EXTERNAL_BASE):
            want = parse_present(bm.get("present"))
            for a, v in dec.items():          # explicit base entries count as present
                if a in BASE and v.get("status") in (None, "inherited", "modified"):
                    want.add(a)
            src_base = {a for a in found if a in BASE}
            if bm.get("p256verify") is True or (
                    0x100 in dec and dec[0x100].get("status")
                    in (None, "inherited", "modified")):
                want.add(0x100)
            if 0x100 in found:
                src_base.add(0x100)
            if want != src_base:
                only_yaml = sorted(f"0x{a:02x}" for a in want - src_base)
                only_src = sorted(f"0x{a:02x}" for a in src_base - want)
                print(f"  BASE MAP mismatch: chain.yaml says present={only_yaml or '—'} "
                      f"extra, source has {only_src or '—'} extra"); problems += 1
            else:
                print(f"  base map ok  ({len(src_base & BASE)}/17 base precompiles"
                      f"{', +P256VERIFY' if 0x100 in src_base else ''})")

        # --- tx types ---
        tf, td = ex_txtypes(slug, c), declared(c, "tx_types")
        if TXTYPE_DIRS.get(slug):
            texp = {a for a, v in td.items() if v.get("status") in (None, "added", "modified", "inherited")}
            tmiss = {a for a in texp if a not in tf}
            tunl = {a for a in tf if a not in td and a > 0x04}
            for a in sorted(tmiss):
                print(f"  MISSING  tx type 0x{a:02x} declared but not in source"); problems += 1
            for a in sorted(tunl):
                print(f"  UNLISTED tx type 0x{a:02x} in source but not in chain.yaml"); problems += 1
            if not tmiss and not tunl:
                print(f"  tx types ok  ({len(tf)} in source)")

        # --- transaction envelope: cross-check `present` against the extracted types ---
        env = (c.get("tx_types") or {}).get("envelope")
        ENV = set(range(0x00, 0x05))
        if env is not None and TXTYPE_DIRS.get(slug) and (tf & ENV):
            want = parse_present(env.get("present"))
            for a, v in td.items():
                if a in ENV and v.get("status") in (None, "inherited", "modified", "added"):
                    want.add(a)
            # present must have a code path; a byte in source but not `present` is
            # the `removed` story (defined, network rejects) and is not an error
            missing = sorted(f"0x{a:02x}" for a in want - (tf & ENV) - {0x00})
            if missing:
                print(f"  ENVELOPE mismatch: declares {missing} present but no type "
                      f"byte for it in source"); problems += 1
            else:
                print(f"  envelope ok  ({len(want)}/5 EIP-2718 types)")

        # --- evidence rule, enforced. `src_doc:`/`src_live:` deliberately point
        # OUTSIDE the clone, so they are checked for shape, not for existence.
        raw = f.read_text()
        bad, nsym, nline, nopath = check_citations(raw, roots(slug, c))
        bad += check_live(raw) + check_tx_auth(c)
        for b in bad:
            print(f"  {b}"); problems += 1
        if not bad and (nsym or nline):
            print(f"  citations ok    {nsym} symbol(s) confirmed, "
                  f"{nline} line ref(s) in range"
                  + (f", {nopath} citing no path" if nopath else ""))
        print(f"  evidence  {tally}")

    print(f"\n{'=' * 60}")
    tot = sum(totals.values())
    if tot:
        mix = "  ".join(f"{k} {v} ({100 * v // tot}%)" for k, v in totals.items() if v)
        print(f"evidence mix across {tot} facts:  {mix}")
        print("  the aggregate tables merge these without distinction — by design, and")
        print("  reversible, because provenance is retained per fact in chain.yaml.")
    if skipped:
        print(f"documented rows (not verifiable, not drift): {', '.join(skipped)}")
    if unextracted:
        print(f"! NO EXTRACTOR, precompiles unchecked: {', '.join(unextracted)}")
        print("  these rows' precompile lists are taken on trust — write an extractor")
    print('DRIFT: ' + str(problems) + ' problem(s)' if problems
          else 'clean — chain.yaml matches source')
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())
