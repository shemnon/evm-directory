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

def repo(slug):
    d = ROOT / "chains" / slug / "repos"
    return next((p for p in d.iterdir() if p.is_dir()), None) if d.exists() else None

def text(slug, rel):
    p = repo(slug)
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

EXTRACT = {"ethereum": ex_ethereum, "op-stack": ex_opstack, "bnb": ex_bnb,
           "avalanche-c": ex_avalanche_c, "avalanche-subnet": ex_avalanche_subnet,
           "tron": ex_tron, "worldchain": ex_worldchain}

TXTYPE_FILES = {
    "ethereum": ["core/types/transaction.go"], "bnb": ["core/types/transaction.go"],
    "op-stack": ["core/types/transaction.go", "core/types/deposit_tx.go"],
    "avalanche-c": [], "avalanche-subnet": [], "tron": [], "worldchain": [],
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

        r = repo(slug)
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
        # entries a chain declares as removed/pending are expected NOT to be in source
        expect = {a for a, v in dec.items()
                  if v.get("status") in (None, "added", "modified", "tombstoned", "inherited")
                  # inherited from a stack ancestor: verified in the ancestor's repo
                  and not v.get("inherited_from")}
        if slug in EXTERNAL_BASE:
            expect = {a for a in expect if a not in set(range(0x01, 0x12))}
        missing = {a for a in expect if a not in found}
        unlisted = {a for a in found if a not in dec and a not in MAINNET_STD}
        for a in sorted(missing):
            print(f"  MISSING  precompile 0x{a:02x} declared but not found in source"); problems += 1
        for a in sorted(unlisted):
            print(f"  UNLISTED precompile 0x{a:02x} in source but not in chain.yaml"); problems += 1
        if not missing and not unlisted:
            print(f"  precompiles ok  ({len(found)} in source, {len(dec)} declared)")

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
