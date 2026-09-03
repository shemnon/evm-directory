#!/usr/bin/env python3
"""Shared data model over `chains/*/chain.yaml`.

Both `generate.py` (the top-level Markdown tables) and `site.py` (the static site
in `website/`) read the dataset through this module. Nothing here renders; it only
loads, orders, canonicalises and cross-indexes, so the two renderers cannot drift
apart on questions like "is `0x0100` the same address as `0x0000...0100`".
"""
import pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHAINS = ROOT / "chains"

# Display order: baseline first, then geth-line forks, then the OP Stack node ahead
# of its descendants, the rollups by proof system, the framework rows ahead of their
# descendants, then the independents and the stablecoin-gas chains. The original
# twelve keep their relative order; later rows are inserted next to their family
# rather than appended, so a column's neighbours are the rows it should be read
# against.
ORDER = ["ethereum",
         "bnb", "polygon", "avalanche-c", "avalanche-subnet", "kaia", "sei",
         "gnosis", "sonic", "berachain", "flare",
         "arbitrum",
         "op-stack", "optimism", "base", "worldchain", "opbnb", "celo", "mantle",
         "megaeth", "rise",
         "linea", "scroll", "taiko", "polygon-zkevm", "zksync-era",
         "rollkit",
         "cosmos-evm", "injective", "artela", "moonbeam",
         "tron", "monad", "hyperliquid", "hedera", "conflux", "taraxa",
         "autonomys",
         "iota-evm",
         "tempo", "arc", "plasma"]

SHORT = {"ethereum": "Ethereum", "bnb": "BNB", "polygon": "Polygon",
         "avalanche-c": "Avax C", "avalanche-subnet": "Avax subnet", "kaia": "Kaia",
         "sei": "Sei", "gnosis": "Gnosis", "sonic": "Sonic", "berachain": "Bera",
         "flare": "Flare", "arbitrum": "Arbitrum",
         "op-stack": "OP Stack", "optimism": "OP Mainnet", "base": "Base",
         "worldchain": "World", "opbnb": "opBNB", "celo": "Celo", "mantle": "Mantle",
         "megaeth": "MegaETH", "rise": "RISE",
         "linea": "Linea", "scroll": "Scroll", "taiko": "Taiko",
         "polygon-zkevm": "zkEVM", "zksync-era": "zkSync",
         "rollkit": "Rollkit",
         "cosmos-evm": "Cosmos EVM", "injective": "Injective", "artela": "Artela",
         "moonbeam": "Moonbeam",
         "tron": "Tron", "monad": "Monad", "hyperliquid": "Hyperliquid",
         "hedera": "Hedera", "conflux": "Conflux", "taraxa": "Taraxa",
         "autonomys": "Auto EVM",
         "iota-evm": "IOTA EVM",
         "tempo": "Tempo", "arc": "Arc", "plasma": "Plasma"}

MARK = {"added": "➕", "removed": "➖", "modified": "⚠️",
        "inherited": "=", "pending": "◌", "tombstoned": "⊘"}

# Address-keyed sections, in the order a chain page presents them.
ADDR_SECTIONS = ["precompiles", "tx_types", "system_contracts"]


def load():
    """slug -> parsed chain.yaml, for every chain directory that has one."""
    out = {}
    for d in sorted(CHAINS.iterdir()):
        f = d / "chain.yaml"
        if f.exists():
            out[d.name] = yaml.safe_load(f.read_text())
    return out


def sources(slug):
    """The input files a single chain's facts come from."""
    return [CHAINS / slug / "chain.yaml", CHAINS / slug / "SUMMARY.md"]


# --- row accessors ---------------------------------------------------------

def name(c):        return c["chain"]["name"]
def slug(c):        return c["chain"]["slug"]
def short(s):       return SHORT.get(s, s)
def documented(c):  return c["chain"].get("evidence") == "documented"
def is_stack(c):    return c["chain"].get("role") == "stack"
def is_chain(c):    return c["chain"].get("role") not in ("stack", "template")


def client(c, field, dflt="—"):
    """Documented rows carry no client — there is no public one to pin."""
    return (c.get("client") or {}).get(field, dflt)


def order(chains):
    return [s for s in ORDER if s in chains] + [s for s in chains if s not in ORDER]


def canon(a):
    """One address, one row. Rows write the same address in different widths —
    `0x0100` and `0x0000...0100` are both P256VERIFY — and keying on the raw string
    split them into two rows, so Sei's absence never lined up with the address it was
    absent from. Normalise to minimal even-length hex, which preserves the existing
    short form for precompiles and the full 40-digit form for predeploys."""
    try: h = f"{int(a, 16):x}"
    except Exception: return a
    return "0x" + h.rjust(2, "0").rjust(len(h) + len(h) % 2, "0")


def sortkey(a):
    try: return (0, int(a, 16))
    except Exception: return (1, 0)


# --- base precompile map synthesis ---------------------------------------------
# A chain records the mainnet base range (0x01-0x11 + P256VERIFY at 0x0100) as a
# condensed `precompiles.base_map` block rather than eighteen near-identical rows.
# The model expands it here into per-address entries so every renderer shows a
# verified `=` / `➖` in those cells instead of a blank that only *assumes*
# mainnet-standard behaviour. An explicit per-address entry always wins over the
# synthesized one; see SCHEMA.md.

_BASE_NAMES_CACHE = {}

def base_names():
    """{int addr -> name} for 0x01-0x11 and 0x100, read once from the baseline row
    so the name table is never duplicated."""
    if not _BASE_NAMES_CACHE:
        pc = (load().get("ethereum", {}).get("precompiles") or {})
        for k, v in pc.items():
            if isinstance(v, dict) and str(k).startswith("0x"):
                try: n = int(str(k), 16)
                except ValueError: continue
                if n in range(0x01, 0x12) or n == 0x100:
                    _BASE_NAMES_CACHE[n] = v.get("name", "")
    return _BASE_NAMES_CACHE


def _parse_present(spec):
    """"0x01-0x0a, 0x0c" / "0x01-0x11" / ["0x01", ...] -> set of ints."""
    if spec in (None, ""): return set()
    parts = spec if isinstance(spec, list) else str(spec).split(",")
    out = set()
    for p in parts:
        p = str(p).strip()
        if not p: continue
        if "-" in p[2:]:                       # a range, not a leading 0x
            lo, hi = p.split("-", 1)
            out |= set(range(int(lo, 16), int(hi, 16) + 1))
        else:
            out.add(int(p, 16))
    return out


def synth_base(c):
    """address -> synthetic entry for one chain's base precompile range, from its
    `precompiles.base_map`. Empty when the chain declares no base_map."""
    bm = (c.get("precompiles") or {}).get("base_map")
    if not isinstance(bm, dict):
        return {}
    names = base_names()
    present = _parse_present(bm.get("present"))
    disp = bm.get("status", "inherited")
    src = bm.get("src")
    src_live = bm.get("src_live")
    out = {}
    for n in range(0x01, 0x12):
        st = disp if n in present else "removed"
        e = {"name": names.get(n, ""), "status": st, "_synth": True}
        if src: e["src"] = src
        if src_live: e["src_live"] = src_live
        out[canon(hex(n))] = e
    p256 = bm.get("p256verify", False)
    st = {True: disp, False: "removed", "pending": "pending"}.get(p256, "removed")
    e = {"name": names.get(0x100, "P256VERIFY"), "status": st, "_synth": True}
    if src: e["src"] = src
    if src_live: e["src_live"] = src_live
    out[canon("0x100")] = e
    return out


def _addr_layer(c, section):
    """A row's own explicit address entries for a section, canonicalised."""
    return {canon(k): v for k, v in (c.get(section) or {}).items()
            if str(k).startswith("0x")}


def _resolve_addr(chains, s, section):
    """One chain's merged address->(entry, origin) map for a section.

    Layering, low to high:
      1. stack ancestor's synthesized base map
      2. this chain's synthesized base map — but a plain `inherited` synth is only a
         fallback (setdefault), while a `removed`/`pending` synth is a deliberate
         narrowing of `present` and takes precedence over an inherited explicit entry
      3. stack ancestor's explicit entries — except where step 2 already recorded a
         deliberate narrowing
      4. this chain's own explicit entries — always win
    """
    c = chains[s]
    pc = section == "precompiles"
    up = c["lineage"].get("upstream")
    stacked = up in chains and is_stack(chains[up])
    out = {}
    if stacked and pc:
        for k, v in synth_base(chains[up]).items():
            out[k] = (v, up)
    if pc:
        for k, v in synth_base(c).items():
            if v.get("status") == "inherited":
                out.setdefault(k, (v, s))
            else:
                out[k] = (v, s)                       # deliberate narrowing
    if stacked:
        for k, v in _addr_layer(chains[up], section).items():
            cur = out.get(k)
            narrowed = (cur and cur[1] == s and isinstance(cur[0], dict)
                        and cur[0].get("_synth")
                        and cur[0].get("status") != "inherited")
            if not narrowed:
                out[k] = (v, up)
    for k, v in _addr_layer(c, section).items():
        out[k] = (v, s)
    return out


def addr_rows(chains, section):
    """Collect address->{slug: entry} across chains, resolving stack inheritance
    and (for precompiles) synthesizing each chain's base precompile map."""
    table, origin = {}, {}
    for s in order(chains):
        for k, (v, who) in _resolve_addr(chains, s, section).items():
            table.setdefault(k, {})[s] = v
            origin[(k, s)] = who
    return table, origin


def effective(chains, s, section):
    """One chain's complete effective set for an address-keyed section:
    address -> (entry, origin_slug). Inherited stack entries and, for precompiles,
    the synthesized base map are included."""
    return _resolve_addr(chains, s, section)


def entry_name(entries):
    """A display name for an address, taken from whichever row bothered to give one."""
    return next((e.get("name", "") for e in entries if isinstance(e, dict) and e.get("name")), "")


# --- cross-cutting indexes -------------------------------------------------

def silent(chains):
    """Every `severity: high` finding in the dataset, as flat records.

    These are the divergences that produce wrong results with no revert and no
    error, and they are scattered across seven different sections — collecting
    them is the whole point of the index."""
    out = []
    def add(s, where, label, e):
        if isinstance(e, dict) and e.get("severity") == "high":
            out.append({"slug": s, "chain": name(chains[s]), "where": where,
                        "label": label, "note": " ".join((e.get("note") or "").split()),
                        "entry": e})
    for s in order(chains):
        c = chains[s]
        for sec in ("precompiles", "system_contracts", "tx_types"):
            # address keys only. `mutable_bytecode` and `dynamic_range` live in the
            # same mapping and are added below by name; iterating everything counted
            # BSC's bytecode rewrite twice, in the site AND in PRECOMPILES.md.
            for k, e in (c.get(sec) or {}).items():
                if isinstance(e, dict) and str(k).startswith("0x"):
                    add(s, sec, f"`{k}`{' ' + e['name'] if e.get('name') else ''}", e)
        for k, e in (c.get("eips") or {}).items():
            if isinstance(e, dict):
                add(s, "eips", f"EIP-{k}" if isinstance(k, int) else str(k), e)
        add(s, "precompiles", "dynamic_range",
            (c.get("precompiles") or {}).get("dynamic_range"))
        for kind in ("added", "removed", "modified"):
            for e in (c.get("header_fields") or {}).get(kind) or []:
                add(s, "header_fields", f"header `{(e or {}).get('name','?')}`", e)
            for e in (c.get("opcodes") or {}).get(kind) or []:
                add(s, "opcodes", f"`{(e or {}).get('op','?')}` {(e or {}).get('name','')}", e)
        for n, v in ((c.get("tx_authorization") or {}).get("schemes") or {}).items():
            add(s, "tx_authorization", n, v)
        sc = c.get("system_contracts") or {}
        if isinstance(sc, dict):
            add(s, "system_contracts", "mutable bytecode", sc.get("mutable_bytecode"))
        add(s, "fee_model", "fee model", c.get("fee_model"))
    return out


def evidence_tally(chains, s):
    """How a row's facts are footed: counts of src / src_doc / src_live.

    SCHEMA.md makes provenance part of each fact; this is what keeps the mix
    visible instead of letting a row drift quietly toward doc-only evidence."""
    tally = {"src": 0, "src_doc": 0, "src_live": 0}
    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in tally and isinstance(x, str): tally[k] += 1
                else: walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    walk(chains[s])
    return tally


def schemes(chains):
    """scheme name -> [(slug, entry, origin)], for the cryptography axis.

    Uses the inheritance-resolved set, so a stack descendant is credited with the
    schemes it actually accepts rather than only the ones it re-declares."""
    out = {}
    for s in order(chains):
        _, sch, org = tx_auth(chains, s)
        for n, v in sch.items():
            out.setdefault(n, []).append((s, v, org.get(n)))
    return out


def unpaired(chains):
    """`authorizes: protocol` with `precompile: none` — the chain accepts signatures
    its own contracts cannot check. `unsigned` is excluded by the caller, since a
    protocol-constructed transaction carries no signature to pair in the first place."""
    out = []
    for n, rows in schemes(chains).items():
        for s, v, org in rows:
            # credit the row that DECLARED it, not every descendant that inherits it
            if org != s: continue
            if v.get("authorizes") == "protocol" and v.get("precompile") in (None, "none"):
                out.append((s, n, v))
    return out


# Curve / scheme families, for the cryptography axis. `pq` is empty and that is
# the finding: no row in this dataset carries a post-quantum scheme, in a
# precompile or as a transaction signer.
FAMILIES = {
    "secp256k1": ["secp256k1", "secp256k1_utxo_credential", "secp256k1_role_based",
                  "secp256k1_accountkey_public", "secp256k1_weighted_multisig",
                  "accountkey_nil", "accountkey_fail"],
    "secp256r1 (P-256)": ["secp256r1", "secp256r1_webauthn"],
    "BLS12-381": ["bls12_381", "bls"],
    "ed25519": ["ed25519"],
    "sr25519": ["sr25519"],
    "SM2": ["sm2"],
    "post-quantum": [],
    "other": ["multisig", "programmable_eip1271", "unsigned"],
}
PQ_NAMES = ["ml-dsa", "ml_dsa", "slh-dsa", "slh_dsa", "falcon", "dilithium",
            "sphincs", "lamport", "winternitz", "xmss", "kyber", "ml-kem"]


def entry_label(entries):
    """Display label for an address that several chains declare.

    Picking one chain's name made the column order decide what an address is
    called, and hid the dataset's headline finding: `0x64`-`0x69` are BSC's
    cross-chain precompiles AND Arbitrum's ArbSys family, `0x78` is Arbitrum's
    deposit type AND Kaia's Ethereum envelope. Every distinct name is shown,
    most-declared first, so a collision reads as a collision."""
    counts = {}
    for e in entries:
        if isinstance(e, dict) and e.get("name"):
            counts[e["name"]] = counts.get(e["name"], 0) + 1
    return " / ".join(sorted(counts, key=lambda n: (-counts[n], n)))


def eip_entry(chains, s, num):
    """(entry, origin_slug) for one EIP on one chain, resolved through a stack
    ancestor. (None, None) when no row declares it.

    Shared by the Markdown matrix and the site so the two cannot disagree about
    what "OP Mainnet has EIP-4844" means when only the OP Stack row says so."""
    e = (chains[s].get("eips") or {}).get(num)
    if e is not None:
        return e, s
    up = chains[s]["lineage"].get("upstream")
    if up in chains and is_stack(chains[up]):
        e = (chains[up].get("eips") or {}).get(num)
        if e is not None:
            return e, up
    return None, None


def eip_status(chains, s, num):
    """Rendered status for an EIP cell. `?` means NOT RECORDED — never silently
    render an unverified fact as a positive claim."""
    e, org = eip_entry(chains, s, num)
    if e is None:
        return ("inherited" if chains[s]["chain"]["role"] == "baseline" else "unrecorded"), None
    st = e.get("status", "inherited")
    return ("unrecorded" if st == "unrecorded" else st), org


def all_eips(chains):
    """Every EIP key any row declares, integers first."""
    ks = {k for c in chains.values() for k in (c.get("eips") or {}) if k != "note"}
    return sorted(ks, key=lambda x: (isinstance(x, str), x))


def tx_auth(chains, s):
    """A chain's effective authorization set, resolving stack inheritance.

    Returns (fields, schemes, origin). OP Mainnet, World Chain and opBNB state only
    their own deltas — `optimism` declares nothing but a note saying so — and reading
    the raw row makes it look as though NOTHING can authorize a transaction on OP
    Mainnet. Inheritance is override-by-key, the same rule the address sections use."""
    c = chains[s]
    own = c.get("tx_authorization") or {}
    up = c["lineage"].get("upstream")
    base = (chains[up].get("tx_authorization") or {}) if (up in chains and is_stack(chains[up])) else {}

    fields, origin = {}, {}
    for k in ("key_binding", "signers_per_tx", "src", "src_live"):
        if k in own:    fields[k], origin[k] = own[k], s
        elif k in base: fields[k], origin[k] = base[k], up
    schemes = {}
    for n, v in (base.get("schemes") or {}).items():
        schemes[n], origin[n] = v, up
    for n, v in (own.get("schemes") or {}).items():
        schemes[n], origin[n] = v, s
    fields["note"] = own.get("note")
    fields["inherited_note"] = base.get("note") if base else None
    return fields, schemes, origin


def baseline_opcodes(chains):
    """The mainnet instruction set at the baseline fork: {"0x01": "ADD", ...}.

    Recorded in chains/ethereum/chain.yaml from the pinned jump table. Without it an
    opcode grid can only show deltas, and every row is divergent by construction —
    there is no way to render "this chain has ADD, unremarkably"."""
    return ((chains.get("ethereum", {}).get("opcodes") or {})
            .get("baseline_set") or {}).get("opcodes") or {}


# Mainnet fork order, oldest first. Used to sort and group rows by the fork they
# claim equivalence to; index in this list IS the recency ranking.
MAINNET_FORKS = ["frontier", "homestead", "tangerine", "spurious", "byzantium",
                 "constantinople", "petersburg", "istanbul", "muir", "berlin",
                 "london", "arrow", "gray", "paris", "shanghai", "cancun",
                 "prague", "osaka", "amsterdam"]


def fork_rank(name):
    """Recency of a mainnet fork; higher is newer. Unknown names sort oldest."""
    try: return MAINNET_FORKS.index(str(name).strip().lower())
    except ValueError: return -1


def last_fork_time(chains, s):
    """The most recent dated fork activation on a chain, or None.

    Many rows have no dated timeline at all — Arbitrum gates on ArbOS version and
    Polygon on block number — so this is genuinely absent rather than zero."""
    tl = (chains[s].get("forks") or {}).get("timeline") or []
    ts = [e.get("activation_time") for e in tl
          if isinstance(e, dict) and isinstance(e.get("activation_time"), int)]
    return max(ts) if ts else None


def by_baseline(chains):
    """[(fork, [slug, ...]), ...] — newest mainnet fork first, and within a fork the
    chain with the most recent dated activation first. Undated rows follow, in the
    standard display order."""
    groups = {}
    for s in order(chains):
        groups.setdefault(str(chains[s].get("baseline_fork", "—")).lower(), []).append(s)
    out = []
    for fork in sorted(groups, key=lambda f: -fork_rank(f)):
        rows = groups[fork]
        dated = sorted((s for s in rows if last_fork_time(chains, s)),
                       key=lambda s: -last_fork_time(chains, s))
        undated = [s for s in rows if not last_fork_time(chains, s)]
        out.append((fork, dated + undated))
    return out


# Codebase roots for the code-lineage view. A chain's client is a fork of one of
# these, possibly through an intermediate fork that is itself a row here.
CODEBASES = {
    "go-ethereum": "go-ethereum", "op-geth": "go-ethereum", "geth": "go-ethereum",
    "hyperledger-besu": "hyperledger-besu", "besu": "hyperledger-besu",
    "reth": "reth", "op-reth": "reth",
}


def code_parent(chains, s):
    """(parent, kind) for the code-lineage graph.

    kind is "row" when the parent is another chain in this dataset (opBNB's client is
    a fork of op-geth, which IS the op-stack row) and "codebase" when it is an
    upstream project with no row of its own."""
    c = chains[s]
    if s == "ethereum":
        return None, None
    up = c["lineage"].get("upstream")
    txt = " ".join(str(x) for x in [c["lineage"].get("fork_of"),
                                    (c.get("client") or {}).get("built_on"),
                                    (c.get("client") or {}).get("name")] if x).lower()
    # a client shared with, or forked from, another row's client
    if "op-geth" in txt and up != "ethereum":
        return "op-stack", "row"
    if (c.get("client") or {}).get("shared_with") in chains:
        return c["client"]["shared_with"], "row"
    for key, root in CODEBASES.items():
        if key in txt:
            return root, "codebase"
    if documented(c):
        return None, None
    return "independent", "codebase"
