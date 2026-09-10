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

`--no-clones` drops every check that reads source and keeps the ones that read
chain.yaml alone. That is what CI runs, because the clones are 6.1 GiB; it is a
weaker gate by definition, and says so in its output. See SITE.md.
"""
import argparse, json, pathlib, re, sys, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAINNET_STD = set(range(0x01, 0x12)) | {0x100}   # 0x01-0x11 plus P256VERIFY

# Chains whose BASE precompiles come from a dependency rather than this repo:
# coreth/subnet-evm consume ava-labs/libevm, so 0x01-0x11 are not in the tree.
# cronos joins them for a different reason: its EVM is `evmos/ethermint`
# replaced onto crypto-org-chain's fork, and go-ethereum itself is replaced
# onto crypto-org-chain/go-ethereum, so 0x01-0x11 are in neither of its clones.
EXTERNAL_BASE = {"avalanche-c", "avalanche-subnet", "cronos"}

def repo(slug, chain=None):
    """The clone holding this row's evidence. Rows may carry companion repos, and
    rows with client.shared_with borrow their ancestor's clone.

    With no `chain` the row's own chain.yaml is read for it. Falling back to the
    first clone alphabetically instead was a trap that only stayed quiet because
    every row with an extractor happened to sort its client first: mantle sorts
    mantle-v2 before op-geth, linea sorts besu before the monorepo, and an
    extractor for either would have silently read the wrong tree."""
    if chain is None:
        f = ROOT / "chains" / slug / "chain.yaml"
        if f.exists(): chain = yaml.safe_load(f.read_text())
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

# ---- extractor protocol ---------------------------------------------------
class ExtractError(Exception):
    """An extractor could not establish what it asserts. Raised, not returned,
    because a thin "this client does not override upstream" extractor has no
    address set of its own to disagree with — its entire content is the
    assertion, so a silent empty set would read as `precompiles ok (0 in
    source)` and be worse than no extractor at all."""

class Found:
    """An extraction: `addrs` is every address the dispatch table answers at,
    `dead` the subset that is present as an address but does not WORK.

    The two are not the same question and chain.yaml already distinguishes them.
    Scroll's Galileo map holds `&ripemd160hashDisabled{}` at 0x03; Linea's Besu
    holds a stock RIPEMD160 but the block's trace limit for it is 0, so a call
    to it can never be included. Both are `tombstoned`/`removed` rows that must
    still be FOUND at their address (or they'd read MISSING), and neither may
    count towards base_map's `present`, which means functionally present."""
    def __init__(self, addrs, dead=()):
        self.addrs, self.dead = set(addrs), set(dead)

def unpack(r):
    return (r.addrs, r.dead) if isinstance(r, Found) else (set(r), set())

def companion(slug, name):
    """A named clone in this row's repos/ — for rows whose evidence is split
    across repos (sei's vendored geth, linea's Besu)."""
    d = ROOT / "chains" / slug / "repos" / name
    if not d.is_dir(): raise ExtractError(f"{slug}: no companion clone {name}/")
    return d

# ---- go / geth ------------------------------------------------------------
def go_map(s, name):
    """The literal behind `var <name> = ...`, following `var A = B` aliases.
    op-geth writes `var PrecompiledContractsMantleArsia = PrecompiledContractsMantleLimb`,
    so the name a chain.yaml cites is not always the name of the literal."""
    seen = set()
    while name not in seen:
        seen.add(name)
        m = re.search(rf"^var {re.escape(name)}\s*=\s*(\w+)\s*$", s, re.M)
        if not m: break
        name = m.group(1)
    b = block(s, f"var {name} = ")
    if not b: raise ExtractError(f"no map literal named {name}")
    return b

def go_named_entries(blk, names):
    """address -> implementation type, for a map keyed by named address constants
    rather than literals (coreth's `nativeasset.NativeAssetCallAddr: makePrecompile(
    &nativeasset.DeprecatedContract{})`)."""
    out = {}
    for m in re.finditer(r"(?:\w+\.)?(\w+):\s*[\w.]*\(?&(?:\w+\.)?(\w+)\{", blk):
        if m.group(1) in names: out[names[m.group(1)]] = m.group(2)
    return out

def go_map_entries(blk):
    """address -> implementation type, for a geth-style map literal. The type is
    how a tombstone announces itself (`&blake2FDisabled{}`)."""
    out = {}
    for m in re.finditer(r"(common\.(?:Bytes|Hex)ToAddress\([^)]*\)):\s*&?(\w+)", blk):
        a = go_addrs(m.group(1))
        if a: out[next(iter(a))] = m.group(2)
    return out

# geth carries a Verkle/UBT switch arm on every fork ladder. It is not on any
# mainnet schedule and aliases an older map (Berlin), so taking the first arm
# blindly would report sei as a Berlin chain. Skip the unscheduled arms only.
GETH_UNSCHEDULED = {"IsVerkle", "IsUBT"}

def geth_live_fork(s):
    """The fork whose map the client selects at its newest scheduled rule, read
    from the switch rather than from a name someone typed into chain.yaml."""
    for fn in ("activePrecompiledContracts", "ActivePrecompiles",
               "ActivePrecompiledContracts"):
        b = block(s, f"func {fn}(")
        for rule, fork in re.findall(
                r"case rules\.(\w+):\s*\n\s*return Precompiled(?:Contracts|Addresses)(\w+)", b):
            if rule not in GETH_UNSCHEDULED: return fork
    raise ExtractError("no fork arm in the precompile switch")

def geth_active(s):
    """(entries, fork) for the map this client selects at its newest fork."""
    fork = geth_live_fork(s)
    return go_map_entries(go_map(s, f"PrecompiledContracts{fork}")), fork

# ---- besu -----------------------------------------------------------------
BESU_REGISTRY = ("evm/src/main/java/org/hyperledger/besu/evm/precompile/"
                 "MainnetPrecompiledContracts.java")
BESU_ADDRESS = "datatypes/src/main/java/org/hyperledger/besu/datatypes/Address.java"

def besu_registry(root, fork):
    """Every address `populateFor<fork>` puts in the registry, following the
    call chain (populateForCancun -> populateForIstanbul -> ...)."""
    reg, adr = root / BESU_REGISTRY, root / BESU_ADDRESS
    if not reg.exists() or not adr.exists():
        raise ExtractError(f"{root.name} is not a Besu tree")
    names = {m.group(1): int(m.group(2), 16) for m in re.finditer(
        r"public static final Address (\w+) = Address\.precompiled\((0x[0-9a-fA-F]+)\)",
        adr.read_text(errors="replace"))}
    s, out, todo, seen = reg.read_text(errors="replace"), set(), [fork], set()
    while todo:
        f = todo.pop()
        if f in seen: continue
        seen.add(f)
        b = block(s, f"static void populateFor{f}(", "\n  }")
        if not b: raise ExtractError(f"Besu has no populateFor{f}")
        for m in re.finditer(r"registry\.put\(\s*(?:Address\.)?(\w+)", b):
            if m.group(1) in names: out.add(names[m.group(1)])
        todo += re.findall(r"populateFor(\w+)\(registry", b)
    return out

BESU_FORKS = ["Frontier", "Homestead", "Byzantium", "Constantinople", "Istanbul",
              "Berlin", "London", "Shanghai", "Cancun", "Prague", "Osaka"]

def besu_genesis_fork(cfg):
    """Newest fork the genesis file activates. Besu's built-in chain files carry
    `<fork>Block` / `<fork>Time` keys, so the ladder is in the tree, not in a note."""
    live = None
    for f in BESU_FORKS:
        if any(k.lower() in (f.lower() + "block", f.lower() + "time") for k in cfg):
            live = f
    if live is None: raise ExtractError("genesis activates no known fork")
    return live

# ---- rust -----------------------------------------------------------------
def rust_prod(p):
    """A .rs file with its inline `#[cfg(test)] mod tests` cut off. Every reth
    fork keeps its precompile-override tests next to the code that does not
    override anything; counting those as overrides would fail every check."""
    s = p.read_text(errors="replace")
    i = s.find("#[cfg(test)]")
    return s[:i] if i >= 0 else s

def no_local_override(src, stock, mutators):
    """Assert a vendored-EVM client leaves the upstream precompile table alone:
    `stock` (the upstream constructor) is called, and no `mutators` token appears
    in production code anywhere except on that same line.

    This is the whole extractor for a client that adds nothing. It cannot see
    what upstream's table CONTAINS — that lives in a crate, not in the clone —
    so it verifies the only thing the clone can answer: that nothing here
    changes it. When that stops being true the assertion fails loudly rather
    than the address set quietly staying right for the wrong reason."""
    hits = []
    for f in sorted(src.rglob("*.rs")):
        for n, line in enumerate(rust_prod(f).splitlines(), 1):
            if stock in line: hits.append(("stock", f, n))
            elif any(m in line for m in mutators): hits.append(("override", f, n))
    if not any(k == "stock" for k, _, _ in hits):
        raise ExtractError(f"upstream constructor `{stock}` is gone — this client "
                           f"no longer builds its precompiles from the stock table")
    bad = [f"{f.relative_to(src)}:{n}" for k, f, n in hits if k == "override"]
    if bad:
        raise ExtractError("local precompile override in production code: "
                           + ", ".join(bad[:4]))

# ---- c# / nethermind ------------------------------------------------------
def cs_ladder(d):
    """Nethermind names its fork files `NN_Name.cs`, so the ladder order is in
    the filenames. -> [(NN, name, path)], oldest first."""
    out = []
    for p in sorted(d.glob("*.cs")):
        n, _, rest = p.name.partition("_")
        if n.isdigit() and rest: out.append((int(n), rest[:-3], p))
    return out

def cs_flags(ladders, upto):
    """EIP flags in force at rung `upto`, applying each fork's `spec.IsEipNEnabled`
    deltas in ladder order. A chain ladder (GnosisForks) is applied after the
    mainnet delta at the same rung, which is the order NamedGnosisReleaseSpec
    itself uses: `base.Apply(spec)` first, then the chain's overrides."""
    flags, steps = {}, []
    for rank, d in enumerate(ladders):
        steps += [(n, rank, p) for n, _, p in cs_ladder(d) if n <= upto]
    for _, _, p in sorted(steps, key=lambda t: (t[0], t[1])):
        for m in re.finditer(r"spec\.(Is\w+Enabled)\s*=\s*(true|false)",
                             p.read_text(errors="replace")):
            flags[m.group(1)] = m.group(2) == "true"
    return flags

def cs_eval(expr, flags):
    """Evaluate a C# boolean guard over those flags. The guards in
    BuildPrecompilesCache are flag names joined by && / ||; anything richer is
    refused rather than guessed at."""
    e = re.sub(r"\b(Is\w+)\b", lambda m: str(bool(flags.get(m.group(1)))), expr)
    e = e.replace("&&", "and").replace("||", "or")
    if not re.fullmatch(r"[\s()]*(True|False)([\s()]*(and|or)[\s()]*(True|False))*[\s()]*", e):
        raise ExtractError(f"unparsed precompile guard: {expr!r}")
    return eval(e, {"__builtins__": {}}, {})

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
    granite = block(s, "var PrecompiledContractsGranite = ")
    a = resolve(granite, names)
    a |= go_addrs(na)
    a |= go_addrs(text("avalanche-c", "precompile/contracts/warp/module.go"))
    # the three native-asset addresses are still IN the live map, mapped to
    # `DeprecatedContract`, whose Run does nothing but return ErrExecutionReverted.
    # Reading only the addresses made a burned address look like a working one.
    dead = {addr for addr, impl in go_named_entries(granite, names).items()
            if impl == "DeprecatedContract"}
    return Found({x for x in a if x > 0xff or x in MAINNET_STD}, dead)

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

# --- geth forks that keep their own fork ladder in core/vm/contracts.go -----
def ex_mantle():
    """op-geth fork. The live map is an ALIAS (`MantleArsia = MantleLimb`), which
    is why go_map follows aliases rather than taking the cited name literally."""
    e, _ = geth_active(text("mantle", "core/vm/contracts.go"))
    return set(e)

def ex_celo():
    """op-geth fork. Celo's own map is a SECOND registry (`PrecompiledCeloContracts*`,
    a different value type) consulted only after the ethereum/OP map misses, so it
    cannot shadow a mainnet address — but it is still live, and both are the set."""
    s = text("celo", "core/vm/contracts.go")
    e, _ = geth_active(s)
    cel2 = text("celo", "core/vm/celo_contracts.go")
    return set(e) | resolve(go_map(s, "PrecompiledCeloContractsCel2"), consts(cel2))

def ex_scroll():
    """l2geth fork. 0x03 and 0x09 are IN the live map, as `*Disabled` stubs: the
    address answers, the call burns the gas and errors. That is `tombstoned`, not
    absent, and only the implementation type says so."""
    e, _ = geth_active(text("scroll", "core/vm/contracts.go"))
    return Found(e, {a for a, t in e.items() if t.endswith("Disabled")})

def ex_sei():
    """Two clones: the vendored geth fork supplies the base map (its ladder tops
    out at Prague — no Osaka arm, hence no 0x0100 from the base), and sei-chain
    supplies thirteen Cosmos-module precompiles, installed by
    ActivePrecompiledContracts only where the base map has no entry."""
    g = (companion("sei", "go-ethereum") / "core/vm/contracts.go").read_text(errors="replace")
    e, _ = geth_active(g)
    s = text("sei", "precompiles/setup.go")
    names = {}
    for f in sorted((repo("sei") / "precompiles").glob("*/*.go")):
        if f.name.endswith("_test.go"): continue
        for m in re.finditer(r'(\w+Address)\s*=\s*"(0x[0-9a-fA-F]{40})"', f.read_text(errors="replace")):
            names[m.group(1)] = int(m.group(2), 16)
    custom = {names[m] for m in re.findall(r"ecommon\.HexToAddress\(\w+\.(\w+)\)",
                                           block(s, "func GetCustomPrecompiles(", "\n}"))
              if m in names}
    if not custom: raise ExtractError("sei: GetCustomPrecompiles resolved to nothing")
    return set(e) | custom

# --- vendored EVMs that override nothing -----------------------------------
def ex_berachain():
    """bera-reth builds its precompiles with the stock revm constructor and never
    touches the result, so the live set IS upstream's at the configured spec. The
    table is in the revm crate, not in this clone; what the clone can prove is
    that nothing here changes it, and that is what this asserts."""
    src = repo("berachain") / "src"
    no_local_override(src, "PrecompilesMap::from_static(Precompiles::new(",
                      ("precompiles_mut(", "apply_precompile", "PrecompilesMap::new"))
    return set(MAINNET_STD)

def ex_linea():
    """Linea's execution client is stock Besu (cloned as a companion at the pinned
    commit); the monorepo holds no precompile of its own. The divergence is not in
    the registry at all — it is the per-block trace limit, and a limit of ZERO makes
    a call to that precompile unincludable in any block. So the registry gives the
    addresses and trace-limits.mainnet.toml gives which of them are dead."""
    besu = companion("linea", "besu")
    cfg = json.loads((besu / "config/src/main/resources/linea-mainnet.json")
                     .read_text())["config"]
    addrs = besu_registry(besu, besu_genesis_fork(cfg))
    limits = text("linea", "linea-besu/package/linea-besu/config/trace-limits.mainnet.toml")
    if not limits: raise ExtractError("linea: no mainnet trace-limit file")
    dead = set()
    for key, a in LINEA_LIMIT.items():
        m = re.search(rf"^{key}\s*=\s*(\d+)", limits, re.M)
        if m and int(m.group(1)) == 0: dead.add(a)
    return Found(addrs, dead)

# One per address: the limit that counts CALLS to it. Zero means no block can
# contain a call to that precompile. Secondary limits (rounds, miller loops,
# LARGE_MODEXP) cap throughput within a call and are deliberately not here.
LINEA_LIMIT = {
    "PRECOMPILE_ECRECOVER_EFFECTIVE_CALLS": 0x01, "PRECOMPILE_SHA2_BLOCKS": 0x02,
    "PRECOMPILE_RIPEMD_BLOCKS": 0x03, "PRECOMPILE_MODEXP_EFFECTIVE_CALLS": 0x05,
    "PRECOMPILE_ECADD_EFFECTIVE_CALLS": 0x06, "PRECOMPILE_ECMUL_EFFECTIVE_CALLS": 0x07,
    "PRECOMPILE_ECPAIRING_FINAL_EXPONENTIATIONS": 0x08,
    "PRECOMPILE_BLAKE_EFFECTIVE_CALLS": 0x09,
    "PRECOMPILE_BLS_POINT_EVALUATION_EFFECTIVE_CALLS": 0x0a,
    "PRECOMPILE_BLS_G1_ADD_EFFECTIVE_CALLS": 0x0b,
    "PRECOMPILE_BLS_G1_MSM_EFFECTIVE_CALLS": 0x0c,
    "PRECOMPILE_BLS_G2_ADD_EFFECTIVE_CALLS": 0x0d,
    "PRECOMPILE_BLS_G2_MSM_EFFECTIVE_CALLS": 0x0e,
    "PRECOMPILE_BLS_PAIRING_CHECK_MILLER_LOOPS": 0x0f,
    "PRECOMPILE_BLS_MAP_FP_TO_G1_EFFECTIVE_CALLS": 0x10,
    "PRECOMPILE_BLS_MAP_FP2_TO_G2_EFFECTIVE_CALLS": 0x11,
    "PRECOMPILE_P256_VERIFY_EFFECTIVE_CALLS": 0x100,
}

def ex_hedera():
    """Java. Hedera's EVM is Besu-the-library, so the base map is one call:
    V0xxModule.providePrecompileContractRegistry populates the registry from
    MainnetPrecompiledContracts and adds nothing. Which module is live comes from
    the `evm.version` default, and the fork's membership from Besu itself — the
    clone next door at chains/linea/repos/besu, since hedera consumes Besu as a
    Maven artifact and has no Besu tree of its own.

    Two rungs of that are assertions rather than readings: the borrowed Besu is a
    different version from the pinned one (checked, below), and a change to
    populateForCancun's membership there would land here as drift to investigate.
    That is the intended failure mode. Everything ABOVE 0x0a on this chain is the
    system-account sink, which is a predicate, not an address list, and is carried
    as precompiles.dynamic_range."""
    cfg = text("hedera", "hedera-node/hedera-config/src/main/java/com/hedera/node/"
                         "config/data/ContractsConfig.java")
    m = re.search(r'ConfigProperty\(value = "evm\.version", defaultValue = "v(\d+)\.(\d+)"', cfg)
    if not m: raise ExtractError("hedera: no evm.version default in ContractsConfig")
    ver = f"v{int(m.group(1)):01d}{int(m.group(2)):02d}"
    mod = text("hedera", f"hedera-node/hedera-smart-contract-service-impl/src/main/java/"
                         f"com/hedera/node/app/service/contract/impl/exec/{ver}/"
                         f"{ver.upper()}Module.java")
    body = block(mod, "static PrecompileContractRegistry providePrecompileContractRegistry(",
                 "\n    }")
    if not body: raise ExtractError(f"hedera: no registry provider in {ver.upper()}Module")
    forks = re.findall(r"MainnetPrecompiledContracts\.populateFor(\w+)\(", body)
    extra = re.findall(r"\.put\(\s*(\w+)", body)
    if len(forks) != 1 or extra:
        raise ExtractError(f"hedera: {ver.upper()}Module no longer populates from one "
                           f"Besu fork alone (forks={forks}, puts={extra})")
    pin = text("hedera", "hiero-dependency-versions/build.gradle.kts")
    if not re.search(r'val besu = "[\d.]+"', pin):
        raise ExtractError("hedera: no Besu version pin to check the borrowed tree against")
    return besu_registry(companion("linea", "besu"), forks[0])

# --- reimplementations -----------------------------------------------------
def ex_monad():
    """C++. `resolve_precompile` is a chain of CASE(addr, ...) macros under
    `if constexpr` revision gates, and `is_precompile` adds the two Monad
    contracts. Every gate in resolve_precompile is satisfied at the live
    revision (Monad is past Prague-equivalent and has EIP-7951), so the CASE
    list is the set; the two Monad addresses are gated on MONAD_FOUR and
    MONAD_NINE, both live, and resolve from `constexpr Address X{0x....}`."""
    r = repo("monad")
    eth = block((r / "category/execution/ethereum/precompiles.cpp").read_text(errors="replace"),
                "std::optional<PrecompiledContract> resolve_precompile(", "\n}")
    addrs = {int(m, 16) for m in re.findall(r"CASE\((0x[0-9a-fA-F]+),", eth)}
    if not addrs: raise ExtractError("monad: resolve_precompile has no CASE arms")
    mon = block((r / "category/execution/monad/monad_precompiles.cpp").read_text(errors="replace"),
                "bool is_precompile(", "\n}")
    names = {}
    for f in sorted(r.rglob("*.hpp")):
        # both spellings occur: `Address STAKING_CA{0x1000}` and
        # `Address RESERVE_BALANCE_CA = Address{0x1001}`
        for m in re.finditer(r"inline constexpr Address (\w+)\s*(?:=\s*Address)?\{(0x[0-9a-fA-F]+)\}",
                             f.read_text(errors="replace")):
            names[m.group(1)] = int(m.group(2), 16)
    for n in re.findall(r"address == (?:\w+::)?(\w+)", mon):
        if n in names: addrs.add(names[n])
    return addrs

def ex_zksync_era():
    """EraVM has no precompile map: the "precompiles" are Yul contracts DEPLOYED
    at those addresses by genesis. SYSTEM_CONTRACT_LIST is that genesis list, and
    the `precompiles/` source directory is what separates a precompile from an
    ordinary system contract in it. Addresses are H160 byte arrays, not literals.

    Nothing here reports the tombstoned 0x03/0x09/0x0a-0x11: those are absent by
    an ADDRESS-SPACE rule (kernel-space, below 2^16, with no deployed code), which
    is a predicate over the complement of this list rather than an entry in it."""
    r = repo("zksync-era")
    lst = block((r / "core/lib/types/src/system_contracts.rs").read_text(errors="replace"),
                "static SYSTEM_CONTRACT_LIST", "\n];")
    consts = {}
    for f in sorted((r / "core/lib/constants/src").glob("*.rs")):
        for m in re.finditer(r"pub const (\w+): Address = H160\(\[([^\]]*)\]\)",
                             f.read_text(errors="replace")):
            b = re.findall(r"0x[0-9a-fA-F]{2}", m.group(2))
            if len(b) == 20: consts[m.group(1)] = int("".join(x[2:] for x in b), 16)
    out = set()
    for path, name, addr in re.findall(
            r'\(\s*"([^"]*)",\s*\n\s*"(\w+)",\s*\n\s*(\w+),', lst):
        if path == "precompiles/" and addr in consts: out.add(consts[addr])
    if not out: raise ExtractError("zksync-era: no precompiles/ entries in SYSTEM_CONTRACT_LIST")
    return out

def ex_gnosis():
    """C#. Nethermind separates the IMPLEMENTATION map (EthereumPrecompileProvider,
    every precompile it can run) from the ACTIVE set (ReleaseSpec.BuildPrecompilesCache,
    gated per EIP), and only the second is this chain's answer — so both are read
    and intersected. The EIP flags come from walking the fork ladder to the newest
    rung GnosisSpecProvider actually schedules; the file-name prefixes ARE the
    ladder order.

    Limit: a fork at the head of the schedule that has not yet activated on
    mainnet would be counted. Gnosis's newest scheduled rung is Osaka, timestamped
    2026-04-14 and long since live."""
    n = repo("gnosis") / "src/Nethermind"
    impl = (n / "Nethermind.Blockchain/EthereumPrecompileProvider.cs").read_text(errors="replace")
    names = {}
    for f in sorted((n / "Nethermind.Evm.Precompiles").glob("*.cs")):
        m = re.search(r"public static Address Address \{ get; \} = Address\.FromNumber\(([\dxa-fA-F]+)\)",
                      f.read_text(errors="replace"))
        if m: names[f.stem] = int(m.group(1), 0)
    runnable = {names[c] for c in re.findall(r"\[(\w+)\.Address\]", impl) if c in names}
    if not runnable: raise ExtractError("gnosis: EthereumPrecompileProvider resolved to nothing")

    spec = (n / "Nethermind.Specs/GnosisSpecProvider.cs").read_text(errors="replace")
    sched = re.findall(r"\]\s*=\s*(\w+)\.Instance", block(spec, "new ForkSchedule", "\n        },"))
    if not sched: raise ExtractError("gnosis: no fork schedule")
    gf = n / "Nethermind.Specs/GnosisForks"
    rung = next((i for i, name, _ in cs_ladder(gf) if name == sched[-1]), None)
    if rung is None: raise ExtractError(f"gnosis: {sched[-1]} is not on the ladder")
    flags = cs_flags([n / "Nethermind.Specs/Forks", gf], rung)

    addrs = {m.group(1): int(m.group(2), 0) for m in re.finditer(
        r"public static readonly AddressAsKey (\w+) = Address\.FromNumber\(([\dxa-fA-F]+)\)",
        (n / "Nethermind.Core/Precompiles/PrecompiledAddresses.cs").read_text(errors="replace"))}
    body = block((n / "Nethermind.Specs/ReleaseSpec.cs").read_text(errors="replace"),
                 "public virtual FrozenSet<AddressAsKey> BuildPrecompilesCache()", "\n    }")
    def named(t): return {addrs[x] for x in re.findall(r"PrecompiledAddresses\.(\w+)", t) if x in addrs}
    active = named(block(body, "cache =", "];"))
    for m in re.finditer(r"if \(([^)]+)\)\s*(\{[^{}]*\}|[^\n]*)", body):
        if cs_eval(m.group(1), flags): active |= named(m.group(2))
    if not active: raise ExtractError("gnosis: BuildPrecompilesCache resolved to nothing")
    return active & runnable

# --- op-geth forks that never advanced the precompile ladder ---------------
def ex_blast():
    """op-geth fork, and the map that matters is the OLD one. blast-geth carries a
    modern params/config.go (Prague, Osaka, BPO) over a geth-1.13 core/vm/contracts.go
    whose ActivePrecompiles has no Prague or Osaka case, so
    PrecompiledContractsCancun IS the live set. The 0x0100 entry in it is Blast's own
    state-writing `blast` precompile, not P256VERIFY.

    Raises if a Prague/Osaka rung ever appears, because at that moment the Cancun map
    stops being the answer and every base-map claim on the row goes stale."""
    s = text("blast", "blast-geth/core/vm/contracts.go")
    if not s: raise ExtractError("blast: blast-geth/core/vm/contracts.go not found")
    body = block(s, "func ActivePrecompiles(rules params.Rules)")
    if "rules.IsPrague" in body or "rules.IsOsaka" in body:
        raise ExtractError("blast: ActivePrecompiles gained a Prague/Osaka rung — "
                           "PrecompiledContractsCancun is no longer the live set")
    a = go_addrs(block(s, "var PrecompiledContractsCancun = "))
    if not a: raise ExtractError("blast: no PrecompiledContractsCancun literal")
    return a


# --- java / rskj -----------------------------------------------------------
def rsk_heights(p):
    """fork name -> mainnet activation height, and rule -> height overrides, from
    config/main.conf. -1 means never."""
    cfg = (p / "rskj-core/src/main/resources/config/main.conf").read_text(errors="replace")
    heights = {k: int(v) for k, v in re.findall(
        r"(\w+)\s*=\s*(-?\d+)", block(cfg, "hardforkActivationHeights = {", "\n    }"))}
    over = {k.lower(): int(v) for k, v in re.findall(
        r"(\w+)\s*=\s*(-?\d+)", block(cfg, "consensusRules = {", "\n    }"))}
    if not heights: raise ExtractError("rootstock: no hardforkActivationHeights in main.conf")
    return heights, over


def ex_rootstock():
    """Java, and the live set is a function of TWO config files rather than of a map
    literal. `getContractForAddress` answers unconditionally for GENESIS_ADDRESSES
    and conditionally for CONSENSUS_ENABLED_ADDRESSES, each gated on a ConsensusRule;
    reference.conf maps a rule to a FORK NAME, config/main.conf maps a fork name to a
    mainnet BLOCK HEIGHT, and main.conf may additionally pin one rule to a height of
    its own. A height of -1 means never, which is how RSKIP144 (parallel execution)
    stays out of this set despite being fully implemented in the tree."""
    p = repo("rootstock")
    if p is None: raise ExtractError("rootstock: no clone")
    src = (p / "rskj-core/src/main/java/org/ethereum/vm/PrecompiledContracts.java"
           ).read_text(errors="replace")
    addr = {f"{m.group(1)}_ADDR": int(m.group(2), 16) for m in re.finditer(
        r'public static final String (\w+)_ADDR_STR = "([0-9a-fA-F]{40})"', src)}
    if not addr: raise ExtractError("rootstock: no *_ADDR_STR constants")

    genesis = [n for n in re.findall(r"(\w+_ADDR)\b",
                                     block(src, "GENESIS_ADDRESSES", "));"))]
    if not genesis: raise ExtractError("rootstock: GENESIS_ADDRESSES did not parse")
    gated = re.findall(r"SimpleEntry<>\((\w+_ADDR),\s*ConsensusRule\.(RSKIP\d+)\)",
                       block(src, "CONSENSUS_ENABLED_ADDRESSES", "\n    );"))
    if not gated: raise ExtractError("rootstock: CONSENSUS_ENABLED_ADDRESSES did not parse")

    ref = (p / "rskj-core/src/main/resources/reference.conf").read_text(errors="replace")
    rule_fork = {k.lower(): v for k, v in re.findall(
        r"(\w+)\s*=\s*([A-Za-z]\w*)", block(ref, "consensusRules = {", "\n        }"))}
    heights, over = rsk_heights(p)

    def live(rule):
        r = rule.lower()
        h = over.get(r)
        if h is None:
            h = heights.get(rule_fork.get(r, ""))
        return h is not None and h >= 0

    out = {addr[n] for n in genesis if n in addr}
    out |= {addr[n] for n, rule in gated if n in addr and live(rule)}
    if not out: raise ExtractError("rootstock: resolved to no live precompiles")
    return out


# --- geth forks that append a consensus-engine set to the fork ladder -------
def ex_core():
    """BSC fork. ActivePrecompiles selects PrecompiledContractsPrague (the newest
    rung CoreChainConfig reaches — there is no Osaka time) and then APPENDS the two
    Satoshi maps when rules.IsSatoshi, which holds on every Core network because
    CoreChainConfig sets a Satoshi block. The live set is the union of the three."""
    s = text("core", "core/vm/contracts.go")
    if not s: raise ExtractError("core: core/vm/contracts.go not found")
    a = go_addrs(block(s, "var PrecompiledContractsPrague = "))
    if not a: raise ExtractError("core: no PrecompiledContractsPrague literal")
    for n in ("PrecompiledContractsSatoshiHashPower", "PrecompiledContractsSatoshiPrague"):
        b = block(s, f"var {n} = ")
        if not b: raise ExtractError(f"core: no {n} literal")
        a |= go_addrs(b)
    return a


# --- cosmos: the assertion is that nothing is registered -------------------
def ex_cronos():
    """The three Cronos precompiles are DEFINED and NOT REGISTERED: app/app.go hands
    the EVM keeper an empty `[]evmkeeper.CustomContractFn{}`, and that slice is the
    only registration path in the tree. So the live custom set is empty and the base
    set comes from an unvendored go-ethereum fork (hence EXTERNAL_BASE).

    Returning the empty set is exactly the case the ExtractError docstring warns
    about — so the assertion is enforced instead of implied: if the slice ever stops
    being empty, or the call site disappears, this raises rather than reporting
    `precompiles ok (0 in source)`."""
    r = repo("cronos")
    if r is None: raise ExtractError("cronos: no clone")
    app = (r / "app/app.go").read_text(errors="replace")
    m = re.search(r"\[\]evmkeeper\.CustomContractFn\{([^}]*)\}", app)
    if m is None:
        raise ExtractError("cronos: no []evmkeeper.CustomContractFn{...} in app/app.go — "
                           "the registration site this row rests on has moved")
    if m.group(1).strip():
        raise ExtractError("cronos: CustomContractFn slice is no longer empty: "
                           + " ".join(m.group(1).split())[:90])
    return set()


EXTRACT = {"ethereum": ex_ethereum, "op-stack": ex_opstack, "bnb": ex_bnb,
           "avalanche-c": ex_avalanche_c, "avalanche-subnet": ex_avalanche_subnet,
           "tron": ex_tron, "worldchain": ex_worldchain, "optimism": ex_optimism,
           "arbitrum": ex_arbitrum, "polygon": ex_polygon, "opbnb": ex_opbnb,
           "base": ex_base,
           "mantle": ex_mantle, "celo": ex_celo, "scroll": ex_scroll, "sei": ex_sei,
           "berachain": ex_berachain, "linea": ex_linea, "hedera": ex_hedera,
           "monad": ex_monad, "zksync-era": ex_zksync_era, "gnosis": ex_gnosis,
           "blast": ex_blast,
           "rootstock": ex_rootstock,
           "core": ex_core,
           "cronos": ex_cronos}

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
    "blast": "blast-geth/core/types",
    # rootstock is Java and has no EIP-2718 envelope at all.
    "rootstock": None,
    "core": "core/types",
    # cronos keeps its transaction types in an unvendored go-ethereum fork.
    "cronos": None,
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
    aggregate tables'), so this counter is the only place the ratio is visible.

    `unrecorded` is counted apart from `none`, and the split is the point. A
    `status: unrecorded` row carries no evidence BY CONSTRUCTION — SCHEMA.md defines
    it as "deliberately not established", recorded so the aggregate tables render `?`
    instead of falling back to `inherited` and silently asserting mainnet equivalence.
    Folding those into `none` made a deliberate declaration indistinguishable from a
    missing citation, so the bucket could never be driven down and nobody could tell
    which part of it was real work. `none` now means only the second thing: a fact
    that asserts something and does not say how it is known."""
    t = {"src": 0, "src_live": 0, "src_doc": 0, "unrecorded": 0, "none": 0}
    for sec in PROV_SECTIONS:
        d = c.get(sec) or {}
        if not isinstance(d, dict): continue
        for v in d.values():
            if not isinstance(v, dict): continue
            for k in ("src", "src_live", "src_doc"):
                if k in v: t[k] += 1; break
            else: t["unrecorded" if v.get("status") == "unrecorded" else "none"] += 1
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
    first, which is how the second of those survived.

    `rs=None` is the clone-less mode (`--no-clones`, used in CI): resolving a path
    needs the clone, so only the citation's SHAPE is checked — a line ref has to be
    a real range. That catches `:0` and `:120-90` without fetching 6 GiB of source;
    it cannot catch a path that does not exist or a line past EOF."""
    bad, nsym, nline, nopath = [], 0, 0, 0
    for m in re.finditer(r"(?<![_\w])src: (.+)", raw):
        found = CITE.findall(m.group(1))
        if not found: nopath += 1      # prose or a bare directory — nothing to resolve
        for path, ref in found:
            end = None
            if ref and LINEREF.match(ref):
                lo, _, hi = ref.partition("-")
                lo, end = int(lo), int(hi or lo)
                if lo < 1 or end < lo:
                    bad.append(f"BAD LINE  {path}:{ref} is not a line range"); continue
            if rs is None:             # no clones: shape is all that can be checked
                if end: nline += 1
                continue
            f = resolve_cite(path, rs)
            if f is None:
                bad.append(f"BAD SRC   {path} does not exist in any pinned clone"); continue
            if not ref: continue
            body = f.read_text(errors="replace")
            if end:
                n = body.count("\n") + 1
                if end > n:
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

LIVE_STATES = {"prelaunch", "halted", "unreachable"}
DEAD_HOW = {"shutdown", "abandoned", "unrecorded"}
RECOURSE = {"claims", "migration", "none", "unrecorded"}

def check_liveness(c):
    """Validate `live_state:` and `dead:` against SCHEMA.md.

    Runs in CI: reads chain.yaml alone, needs neither a clone nor a network. Every
    rule here corresponds to a mistake that was actually made in this dataset.

    - Moonbeam carried `live: true` while its own SUMMARY.md established that the
      EVM had been switched off at the probed block. A row cannot say both.
    - `shutdown` asserts an INTENTION, and no probe returns one. It is the one
      place in this schema where `src_doc:` is the only admissible evidence.
    - `abandoned` has no last block by construction — the endpoints that could have
      named one were gone before anyone looked. It must instead bound the ending
      with a dark window, or it is a hunch wearing a schema key.
    - `abandoned` with a claims or migration recourse is self-contradictory: a
      recovery process is something an operator announces, and an operator who
      announced one did not stop answering."""
    ch, out = c["chain"], []
    st, mb = ch.get("live_state"), ch.get("dead")
    if st is not None and st not in LIVE_STATES:
        out.append(f"BAD STATE live_state: {st!r} is not one of "
                   f"{'/'.join(sorted(LIVE_STATES))}")
    if st and ch.get("live"):
        out.append(f"CONTRADICTION  live: true with live_state: {st} — "
                   f"live_state is only meaningful when live is false")
    if ch.get("live") is False and not st:
        out.append("NO STATE  live: false without a live_state — `prelaunch`, "
                   "`halted` and `unreachable` are three different situations "
                   "and a reader cannot tell which from `false` alone")
    if not isinstance(mb, dict):
        if mb is not None:
            out.append(f"BAD DEAD  dead: must be a mapping, got {type(mb).__name__}")
        return out
    if ch.get("live"):
        out.append("CONTRADICTION  dead: with live: true")
    if st == "prelaunch":
        out.append("CONTRADICTION  dead: with live_state: prelaunch — a chain that "
                   "never started cannot have ended")

    e, r = mb.get("how"), mb.get("recourse")
    if e not in DEAD_HOW:
        out.append(f"BAD HOW  dead.how: {e!r} is not one of "
                   f"{'/'.join(sorted(DEAD_HOW))}")
    if r is not None and r not in RECOURSE:
        out.append(f"BAD RECOURSE  dead.recourse: {r!r} is not one of "
                   f"{'/'.join(sorted(RECOURSE))}")

    if e == "shutdown":
        if not mb.get("src_doc"):
            out.append("UNEVIDENCED  dead.how: shutdown asserts an intention and "
                       "carries no src_doc: — intent is not probeable, so a document "
                       "is the only evidence there can be")
        if not mb.get("announced"):
            out.append("NO ANNOUNCEMENT  dead.how: shutdown without an announced: "
                       "date — a shutdown nobody dated was not scheduled")
        if not isinstance(mb.get("last_block"), int):
            out.append("NO LAST BLOCK  dead.how: shutdown without an integer "
                       "last_block: — someone was watching, so the height is knowable")
    elif e == "abandoned":
        a, b = mb.get("dark_after"), mb.get("dark_before")
        if not (a and b):
            out.append("UNBOUNDED  dead.how: abandoned without dark_after:/dark_before: "
                       "— it is established by bounding when the chain went dark; "
                       '"it seems dead" is not an observation')
        elif hasattr(a, "year") and hasattr(b, "year") and a > b:
            out.append(f"BAD WINDOW  dark_after: {a} is later than dark_before: {b}")
        if not mb.get("dark_evidence"):
            out.append("UNEVIDENCED  dead.how: abandoned with no dark_evidence: — the window "
                       "has to say what established it")
        if r in ("claims", "migration"):
            out.append(f"CONTRADICTION  dead.how: abandoned with recourse: {r} — a "
                       f"recovery process is announced by an operator, and an "
                       f"operator who announced one did not stop answering")
    return out


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
    ap = argparse.ArgumentParser(
        description="Re-extract facts from the pinned clones and diff them against "
                    "chain.yaml.",
        epilog="Run tools/clone.sh first. See SITE.md.")
    ap.add_argument("--no-clones", action="store_true",
                    help="skip every check that needs a pinned clone (source "
                         "extraction, base map, envelope, citation resolution) and "
                         "run only the checks that read chain.yaml alone")
    ap.add_argument("slugs", nargs="*", metavar="SLUG",
                    help="check only these rows (default: every row). Useful while "
                         "writing one; the evidence tally and the NO EXTRACTOR list "
                         "then describe only what was run, not the dataset")
    a = ap.parse_args()
    no_clones = a.no_clones
    only = set(a.slugs)
    known = {f.parent.name for f in (ROOT / "chains").glob("*/chain.yaml")}
    unknown = only - known
    if unknown:
        print(f"no such row: {', '.join(sorted(unknown))}")
        return 2

    problems = 0
    totals = {"src": 0, "src_live": 0, "src_doc": 0, "unrecorded": 0, "none": 0}
    skipped, unextracted = [], []
    if no_clones:
        print("--no-clones: chain.yaml is checked against ITSELF, not against source.\n"
              "  running: pin presence, base-map/envelope declaration, opcode keys,\n"
              "  tx-authorization vocabulary, citation shape, evidence tally.")
    for f in sorted((ROOT / "chains").glob("*/chain.yaml")):
        slug = f.parent.name
        if only and slug not in only: continue
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
            for b in check_live(f.read_text()) + check_tx_auth(c) + check_liveness(c):
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

        if no_clones:
            # With no clone there is nothing to compare a pin against, so the pin is
            # checked for PRESENCE and shape. A row that declares no commit — or a
            # short one, or a branch name where a commit belongs — is unpinnable
            # evidence, and that IS catchable without the source.
            pin = cl.get("commit")
            if not re.fullmatch(r"[0-9a-f]{40}", str(pin or "")):
                print(f"  ! NO PIN  client.commit is {pin!r}, want a 40-hex commit")
                problems += 1
            else:
                print(f"  pin declared  {pin[:8]}  (no clone to compare against)")
        else:
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
        ex = None if no_clones else EXTRACT.get(slug)
        if ex is None and not no_clones:
            print("  ! NO EXTRACTOR — precompile list NOT cross-checked against source")
            unextracted.append(slug)
        if ex is not None:
            # A thin "this client overrides nothing upstream" extractor has no set
            # of its own to disagree with, so it reports failure by raising. That
            # IS drift: the assertion the row rests on has stopped holding.
            try:
                found, dead = unpack(ex())
            except ExtractError as e:
                print(f"  ! EXTRACTOR  {e}"); problems += 1; found = None
        if ex is not None and found is not None:
            dec = declared(c, "precompiles")
            # a dynamic range is a predicate, not an address; nothing to enumerate
            dyn = (c.get("precompiles") or {}).get("dynamic_range")
            # entries a chain declares as removed/pending are expected NOT to be in source
            expect = {a for a, v in dec.items()
                      if v.get("status") in (None, "added", "modified", "inherited")
                      # inherited from a stack ancestor: verified in the ancestor's repo
                      and not v.get("inherited_from")}
            # `tombstoned` is deliberately NOT expected-in-source, because a chain
            # can kill an address two ways and they look opposite in the tree.
            # Scroll leaves 0x03 IN the map as `&ripemd160hashDisabled{}`; zkSync
            # kills 0x03 by leaving it OUT and reverting every kernel-space address
            # with no deployed code. Demanding presence made the second look like a
            # transcription error. What is actually forbidden is a tombstone the
            # source still runs, and that is checked below.
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
            # An address whose entry in source is a disabled stub, or whose
            # block-level limit is zero, is present but does not work. chain.yaml
            # has a word for that and it is not `inherited`.
            mislabelled = 0
            for a in sorted(dead):
                st = dec.get(a, {}).get("status")
                if st not in ("tombstoned", "removed"):
                    print(f"  DEAD     0x{a:02x} is present but non-functional in source; "
                          f"chain.yaml says status={st or 'inherited (implicit)'}")
                    problems += 1; mislabelled += 1
            # the other direction: a row may declare an address dead only if the
            # source either does not have it, or has it in a state that does not run
            for a in sorted(a for a, v in dec.items()
                            if v.get("status") in ("tombstoned", "removed")):
                if a in found and a not in dead:
                    print(f"  ALIVE    0x{a:02x} declared "
                          f"{dec[a]['status']} but source has a working implementation")
                    problems += 1; mislabelled += 1
            if not missing and not unlisted and not mislabelled:
                extra = "  +1 dynamic range (not enumerable)" if dyn else ""
                dx = f", {len(dead)} present-but-dead" if dead else ""
                print(f"  precompiles ok  ({len(found)} in source{dx}, "
                      f"{len(dec)} declared){extra}")

            # --- base map: cross-check `present` against the extracted map ---
            bm = (c.get("precompiles") or {}).get("base_map")
            BASE = set(range(0x01, 0x12))
            if (bm is not None and (found & BASE)
                  and slug not in EXTERNAL_BASE):
                want = parse_present(bm.get("present"))
                for a, v in dec.items():          # explicit base entries count as present
                    if a in BASE and v.get("status") in (None, "inherited", "modified"):
                        want.add(a)
                src_base = {a for a in found - dead if a in BASE}
                if bm.get("p256verify") is True or (
                        0x100 in dec and dec[0x100].get("status")
                        in (None, "inherited", "modified")):
                    want.add(0x100)
                if 0x100 in found - dead:
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
        bad, nsym, nline, nopath = check_citations(
            raw, None if no_clones else roots(slug, c))
        bad += check_live(raw) + check_tx_auth(c) + check_liveness(c)
        for b in bad:
            print(f"  {b}"); problems += 1
        if not bad and (nsym or nline):
            # no_clones cannot confirm a symbol at all, so it says what it did do
            # rather than borrowing the wording of a check it did not run
            print(f"  citations shape ok  {nline} line ref(s) well-formed"
                  if no_clones else
                  f"  citations ok    {nsym} symbol(s) confirmed, "
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
        print("  `unrecorded` is evidence-free on purpose (SCHEMA.md); `none` is not —")
        print("  every `none` is a claim with no stated way of knowing it.")
    if skipped:
        print(f"documented rows (not verifiable, not drift): {', '.join(skipped)}")
    if unextracted:
        print(f"! NO EXTRACTOR, precompiles unchecked: {', '.join(unextracted)}")
        print("  these rows' precompile lists are taken on trust — write an extractor")
    if only:
        print(f"! PARTIAL RUN: only {', '.join(sorted(only))}. The tally above is "
              f"not the dataset's.")
    if no_clones:
        print("! --no-clones: NOTHING here was checked against source. The pinned "
              "clones are\n  the only thing that can catch drift; run "
              "`tools/clone.sh && tools/verify.py` locally.")
    print('DRIFT: ' + str(problems) + ' problem(s)' if problems
          else 'clean — chain.yaml is internally consistent (source NOT checked)'
          if no_clones else 'clean — chain.yaml matches source')
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())
