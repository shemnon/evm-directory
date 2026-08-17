#!/usr/bin/env python3
"""Re-extract facts from the pinned clones and diff them against chain.yaml.

The dataset's whole claim is "from source, not docs" — but facts reach chain.yaml
by a human reading a file once. This closes that loop: it re-reads the source and
reports both directions of drift.

  MISSING  declared in chain.yaml, not found in source  (transcription error)
  UNLISTED found in source, not declared in chain.yaml  (coverage gap — worse)

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

TXTYPE_FILES = {
    "ethereum": ["core/types/transaction.go"], "bnb": ["core/types/transaction.go"],
    "op-stack": ["core/types/transaction.go", "core/types/deposit_tx.go"],
    "polygon": ["core/types/transaction.go"],
    "opbnb": ["core/types/transaction.go", "core/types/deposit_tx.go"],
    "arbitrum": ["go-ethereum/core/types/transaction.go"],
    "avalanche-c": [], "avalanche-subnet": [], "tron": [], "worldchain": [],
    "optimism": [], "base": [],
}
def ex_txtypes(slug):
    out = set()
    for rel in TXTYPE_FILES.get(slug, []):
        for m in re.finditer(r"TxType\s*=\s*(0x[0-9a-fA-F]+)", text(slug, rel)):
            out.add(int(m.group(1), 16))
    return out

def declared(c, section):
    return {int(k, 16): v for k, v in (c.get(section) or {}).items()
            if isinstance(k, str) and k.startswith("0x") and isinstance(v, dict)}

def main():
    problems = 0
    for f in sorted((ROOT / "chains").glob("*/chain.yaml")):
        slug = f.parent.name
        c = yaml.safe_load(f.read_text())
        print(f"\n{slug}  ({c['client']['name']} {c['client']['version']})")

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

        # --- precompiles, both directions ---
        found, dec = EXTRACT[slug](), declared(c, "precompiles")
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

        # --- tx types ---
        tf, td = ex_txtypes(slug), declared(c, "tx_types")
        if TXTYPE_FILES.get(slug):
            texp = {a for a, v in td.items() if v.get("status") in (None, "added", "modified", "inherited")}
            tmiss = {a for a in texp if a not in tf}
            tunl = {a for a in tf if a not in td and a > 0x04}
            for a in sorted(tmiss):
                print(f"  MISSING  tx type 0x{a:02x} declared but not in source"); problems += 1
            for a in sorted(tunl):
                print(f"  UNLISTED tx type 0x{a:02x} in source but not in chain.yaml"); problems += 1
            if not tmiss and not tunl:
                print(f"  tx types ok  ({len(tf)} in source)")

        # --- evidence rule: src: must point at a real file ---
        bad = set()
        for m in re.finditer(r"src(?:_\w+)?: [\"']?([^\s,}:\"']+\.(?:go|java|rs|proto|md))", f.read_text()):
            if r and not (r / m.group(1)).exists(): bad.add(m.group(1))
        for b in sorted(bad):
            print(f"  BAD SRC  {b} does not exist in the pinned clone"); problems += 1

    print(f"\n{'=' * 60}\n{'DRIFT: ' + str(problems) + ' problem(s)' if problems else 'clean — chain.yaml matches source'}")
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())
