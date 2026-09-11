#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render the static site in `website/` from the dataset.

Inputs are `chains/*/chain.yaml`, `chains/*/SUMMARY.md`, `findings.yaml`,
`operators.yaml`, `SCHEMA.md` and `README.md`. Nothing in `website/` is hand-edited; see SITE.md for the build model.

Every page leads with its grid — the rolled-up chain x entry table the axis exists to
show. Caveats, per-entry detail and notes sit below it. Every output page declares the
input files it reads, so a plain `site.py` run rebuilds only what actually moved.
"""
import argparse, datetime, hashlib, html, json, pathlib, re, shutil, sys, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import model
from model import ROOT, order, short, name, canon, sortkey, is_stack, documented, client

import yaml
import markdown as _md

OUT = ROOT / "website"
ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
MANIFEST = OUT / ".manifest.json"

# The repository, for the few links that leave the site: the issue form behind "Report an
# inaccuracy", the operator disclosure in CONTRIBUTING.md, and the data license. They are
# navigation, not requests — see prompts/website/00-brief.md, rule 6.
REPO = "https://github.com/shemnon/evm-directory"

AXES = [
    ("precompiles",      "Precompiles",        "Every precompile address in the dataset, per chain and per address."),
    ("tx-types",         "Transaction types",  "EIP-2718 type bytes per chain, and transactions carrying no type byte."),
    ("opcodes",          "Opcodes",            "The full instruction set per chain, and execution environments that are not the EVM."),
    ("cryptography",     "Cryptography",       "Which algorithms can authorize a transaction, and which have a precompile that verifies them."),
    ("system-contracts", "System contracts",   "Real bytecode at fixed addresses: predeploys, genesis allocs and client-installed code."),
    ("eips",             "EIP activation set", "Which EIPs are live on each chain, stated against mainnet at that chain's baseline fork."),
    ("fees-envelope",    "Fees & envelope",    "Metering and fee markets per chain, and header fields that differ from mainnet."),
    ("lineage",          "Lineage",            "Code ancestry and fork ancestry, tracked separately."),
    ("ordering",         "Ordering & execution", "What happens to a transaction between being ordered and being executed."),
    ("p2p",              "P2P & limits",       "How big a transaction, block or message may be, who enforces each bound, and which transports carry them."),
]
AXIS_TITLE = {k: t for k, t, _ in AXES}

# The lifecycle axis. Mainnet cannot reach the ordered-but-invalid state at all —
# validation precedes ordering — so `unreachable` is the baseline every other
# verdict is a delta against, and the axis only has rows once a chain splits the two.
LIFECYCLE = [
    ("ordered_then_invalid", "Ordered, then invalid",
     "A transaction fixed in an order, then found invalid when it executes."),
    ("nonce_on_failure",     "Nonce on failure",
     "Whether a transaction that did no work still spends the sender's nonce."),
    ("duplicate_inclusion",  "Duplicate inclusion",
     "The same transaction landing in more than one block."),
    ("insufficient_balance", "Insufficient balance",
     "A sender who cannot cover the gas the order already committed to."),
    ("ordering",             "Ordering vs. execution",
     "Whether the order commits before the content is known."),
    ("parallel_execution",   "Parallel execution", "Consensus-visible concurrency."),
    ("preconfirmation",      "Preconfirmation",
     "A result published before its enclosing block is sealed."),
]
LIFECYCLE_TITLE = {k: t for k, t, _ in LIFECYCLE}


# The p2p axis. Order is deliberate: the two numbers people conflate first, then the
# ceilings that actually bind, then how the bytes move.
P2P = [
    ("max_tx_bytes",      "Max transaction",
     "The largest transaction the network will carry — usually mempool policy, not a rule."),
    ("max_blob_tx_bytes", "Max blob transaction",
     "Blob-carrying transactions are capped separately, and the cap includes the blobs."),
    ("max_block_bytes",   "Max block",
     "The encoded block ceiling. Consensus-enforced only where EIP-7934 is live."),
    ("max_message_bytes", "Max p2p message",
     "The largest single protocol message the transport will move."),
    ("fragmentation",     "Fragmentation",
     "Whether a message too large for one unit is split, and whether the pieces are recoverable."),
    ("transports",        "Transports",
     "Which p2p protocols the chain actually speaks, and at which layer."),
]
P2P_TITLE = {k: t for k, t, _ in P2P}

# `tier` is the axis's load-bearing field: it says WHO rejects an oversized item, which
# is the difference between "invalid" and "merely unroutable". See SCHEMA.md.
TIER_TITLE = {
    "consensus": "consensus — every validating node rejects; the block is invalid",
    "policy":    "policy — the local mempool refuses it; a block containing it is still valid",
    "transport": "transport — the wire cannot carry it; the connection errors",
}


def fmt_bytes(n):
    """Exact binary sizes read as KiB/MiB; anything else keeps its digits. A limit of
    95,000 is not 92.8 KiB in any useful sense — it was chosen in decimal, against an
    L1 batch budget, and rounding it hides where it came from."""
    if not isinstance(n, int) or isinstance(n, bool):
        return str(n)
    for unit, sz in (("MiB", 1 << 20), ("KiB", 1 << 10)):
        if n >= sz and n % sz == 0:
            return f"{n // sz} {unit}"
    return f"{n:,} B"


def lifecycle(chains, slug, section="tx_lifecycle"):
    """A chain's effective answers for a keyed-question section. A row whose
    `lineage.upstream` names a stack node inherits that node's answers key by key, and
    overrides the ones it states itself — the same override-by-key rule the address
    sections use. Returns {key: (entry, origin_slug)}; origin != slug means inherited.

    `section` selects the axis: `tx_lifecycle` (ordering) or `p2p` (wire limits). Both
    have the same shape, so they share the walk rather than duplicating it."""
    out = {}
    chain = [slug]
    seen = {slug}
    up = chains[slug]["lineage"].get("upstream")
    while up in chains and is_stack(chains[up]) and up not in seen:
        chain.append(up); seen.add(up)
        up = chains[up]["lineage"].get("upstream")
    for s in reversed(chain):                       # ancestor first, descendant wins
        for k, v in (chains[s].get(section) or {}).items():
            if isinstance(v, dict):
                out[k] = (v, s)
    return out


# --------------------------------------------------------------------------
# html helpers
# --------------------------------------------------------------------------

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def strip_tags(s):
    """The lede reaches layout() already rendered to HTML. The meta description is
    plain text, so tags come out and entities come back — without the unescape a
    lede containing `->` ships as `-&amp;gt;`."""
    return re.sub(r"<[^>]+>", "", str(s or ""))


def flat(s):
    """Collapse the YAML block scalars' hard wrapping back into one paragraph."""
    return " ".join(str(s or "").split())


def rel(depth):
    return "../" * depth


def slugify(s):
    return re.sub(r"[^0-9a-z]+", "-", str(s).lower()).strip("-")


NAV = [("index.html", "Overview"), ("chains/index.html", "Chains")] + \
      [(f"axes/{k}.html", t) for k, t, _ in AXES] + \
      [("silent-divergences.html", "Silent divergences")]


def chain_picker(chains, depth):
    """Header control selecting which chain columns every grid shows.

    Persisted in localStorage, so a reader who cares about four chains keeps that
    view as they move between axes instead of re-narrowing on each page."""
    boxes = "".join(
        f'<label><input type="checkbox" data-chain-toggle="{esc(s)}" checked> '
        f'{esc(short(s))}</label>' for s in order(chains))
    return (f'<details class="picker"><summary id="picker-label">Chains: all</summary>'
            f'<div class="menu"><div class="acts">'
            f'<button type="button" data-chain-all>All</button>'
            f'<button type="button" data-chain-none>None</button></div>'
            f'{boxes}</div></details>')


def layout(path, title, lede, body, wide=False, depth=None, chains=None):
    d = path.count("/") if depth is None else depth
    r = rel(d)
    nav = "".join(
        f'<a href="{r}{esc(h)}"{" class=\"on\"" if h == path else ""}>{esc(t)}</a>'
        for h, t in NAV)
    picker = chain_picker(chains, d) if chains else ""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    # On a chain page the correction form opens with the chain already filled in.
    page_slug = path[len("chains/"):-len(".html")] if (
        path.startswith("chains/") and path != "chains/index.html") else None
    report = (f"{REPO}/issues/new?template=correction.yml&chain={page_slug}" if page_slug
              else f"{REPO}/issues/new/choose")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · EVM Directory</title>
<meta name="description" content="{esc(html.unescape(strip_tags(flat(lede))))[:300]}">
<link rel="stylesheet" href="{r}assets/site.css">
</head><body>
<header class="top">
  <span class="brand"><a href="{r}index.html">EVM Directory</a></span>
  <nav>{nav}</nav>
  {picker}
</header>
<main{' class="wide"' if wide else ''}>
<h1>{esc(title)}</h1>
{f'<p class="lede">{lede}</p>' if lede else ''}
{body}
</main>
<footer>Generated {stamp} · Data <a href="{REPO}/blob/main/LICENSE-DATA">CC0</a> (a <a href="{REPO}">link back</a> is appreciated) · <a href="{esc(report)}">Report an inaccuracy</a></footer>
<script src="{r}assets/site.js"></script>
</body></html>
"""


def h2(text, anchor=None):
    a = anchor or slugify(re.sub(r"<[^>]+>", "", text))
    return f'<h2 id="{esc(a)}">{text}<a class="anchor" href="#{esc(a)}">#</a></h2>'


def h3(text, anchor=None):
    a = anchor or slugify(re.sub(r"<[^>]+>", "", text))
    return f'<h3 id="{esc(a)}">{text}<a class="anchor" href="#{esc(a)}">#</a></h3>'


def table(headers, rows, cls="", tid=None, pin=False, row_attrs=None, col_chains=None,
          row_chains=None):
    """rows: list of lists of already-escaped HTML cells.

    col_chains, if given, is a list of slugs (or None) parallel to `headers`, tagging
    each column with the chain it belongs to so the header picker can hide it.

    row_chains is the same idea for the flipped orientation — chains as ROWS — where the
    picker has to hide a `<tr>` instead of a column. `.col-off` is `display: none`, which
    works on either, so one CSS rule and one JS pass serve both."""
    c = " ".join(x for x in [cls, "pin" if pin else ""] if x)
    cc = col_chains or [None] * len(headers)
    th = "".join(f'<th{f" data-chain=\"{esc(s)}\"" if s else ""}>{x}</th>'
                 for x, s in zip(headers, cc))
    ra = row_attrs or [""] * len(rows)
    rc = row_chains or [None] * len(rows)
    tb = "".join(
        f"<tr{a}{f' data-chain=\"{esc(rs)}\"' if rs else ''}>"
        + "".join(f'<td{f" data-chain=\"{esc(s)}\"" if s else ""}>{x}</td>'
                  for x, s in zip(r, cc)) + "</tr>"
        for r, a, rs in zip(rows, ra, rc))
    i = f' id="{esc(tid)}"' if tid else ""
    return (f'<div class="scroll"><table class="{c}"{i}>'
            f"<thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>")


def kv(pairs):
    rows = "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>"
                   for k, v in pairs if v not in (None, "", "—"))
    return f'<div class="scroll"><table class="kv"><tbody>{rows}</tbody></table></div>'


def filter_box(tid, label="filter", uniform=False):
    """`uniform` may be True for the default wording, or a string for the flipped grids,
    where "every chain agrees" is a property of a COLUMN and the useful question becomes
    whether a chain differs from mainnet at all."""
    txt = uniform if isinstance(uniform, str) else "hide rows where every chain agrees"
    u = (f'<label class="chk"><input type="checkbox" data-uniform-for="{tid}"> '
         f'{esc(txt)}</label>') if uniform else ""
    return (f'<div class="filter"><label for="f-{tid}">{esc(label)}</label>'
            f'<input id="f-{tid}" type="search" data-filter="{tid}" '
            f'placeholder="filter rows…" autocomplete="off">'
            f'{u}<span class="count" id="{tid}-count"></span></div>')


def note(body, kind="note", label=None):
    lbl = f'<span class="lbl">{esc(label)}</span>' if label else ""
    return f'<div class="{kind}">{lbl}{body}</div>'


def liveness_banner(c):
    """The first thing on a chain page that is not a running network.

    A reader arrives on a chain page to decide whether to build against it. If the
    answer is "you cannot, it is gone", that has to come before the deltas they came
    for, which are now history. Liveness is a chain attribute, not fact provenance,
    so this is not covered by the chain-page-only rule; the chains index and
    MATRIX.md carry it too."""
    ch = c["chain"]
    st, mb = ch.get("live_state"), ch.get("dead")
    if not st and not mb: return None

    if mb:
        e, r = mb.get("how"), mb.get("recourse")
        aband = e == "abandoned"
        B = []
        if aband:
            B.append("<p><b>This chain went dark.</b> Nobody announced a shutdown, "
                     "no claims window was published, and no last block was ever "
                     "recorded — every endpoint that could have named one was "
                     "already gone before this row existed.</p>")
            a, b = mb.get("dark_after"), mb.get("dark_before")
            if a and b:
                B.append(f"<p>Last observably alive <b>{esc(a)}</b>; first observably "
                         f"gone <b>{esc(b)}</b>. The ending is bounded by that window, "
                         f"not by a height — which is the difference between this and "
                         f"a chain that was switched off.</p>")
        else:
            B.append("<p><b>This chain was shut down deliberately.</b> ")
            if mb.get("last_block") is not None:
                B.append(f'Last block <code>{esc(mb["last_block"])}</code>'
                         + (f' at {esc(mb["last_block_at"])}' if mb.get("last_block_at") else "")
                         + ". ")
            if mb.get("last_block_with_transactions") is not None:
                B.append("It stopped accepting transactions earlier, at block "
                         f'<code>{esc(mb["last_block_with_transactions"])}</code>. ')
            if mb.get("announced"):
                B.append(f'Announced {esc(mb["announced"])}.')
            B.append("</p>")

        RECOURSE = {
            "claims": "An interface exists to recover assets.",
            "migration": "Holdings were migrated elsewhere.",
            "none": "<b>There is no way to recover anything, and nobody left to ask.</b>",
            "unrecorded": "Whether anything can be recovered is not established.",
        }
        if r in RECOURSE:
            extra = ""
            if mb.get("user_deadline"): extra = f' Holders have until <b>{esc(mb["user_deadline"])}</b>.'
            if mb.get("successor"): extra += f' Successor: {esc(mb["successor"])}.'
            B.append(f'<p>{RECOURSE[r]}{extra}</p>')

        B.append("<p>The facts on this page are <b>final</b> — nothing further will "
                 "happen on this network, so they can no longer be contradicted — but "
                 "this is a historical record, not a chain to integrate with. The "
                 "client pin no longer moves.</p>")
        if mb.get("note"):
            B.append(markdown(flat(mb["note"])))
        if mb.get("dark_evidence"):
            B.append("<p class=\"legend\">How the window was established: "
                     + "; ".join(esc(x) for x in mb["dark_evidence"]) + "</p>")
        if mb.get("src_doc"):
            B.append(f'<p class="legend">Announcement: '
                     f'<a href="{esc(mb["src_doc"])}">{esc(mb["src_doc"])}</a></p>')
        return note("".join(B), "hot",
                    "dead · abandoned" if aband else "dead · shutdown")

    if st == "unreachable":
        return note(
            "<p><b>No endpoint for this chain answers</b>, so whether it is still "
            "running is <em>unknown</em>. Nothing was observed to stop. Every fact "
            "here rests on source alone.</p>", "hot", "unreachable")
    if st == "halted":
        return note("<p><b>This chain has stopped producing blocks.</b> Its facts are "
                    "frozen at the last block observed.</p>", "hot", "halted")
    if st == "prelaunch":
        return note(
            "<p><b>This chain has never produced a mainnet block.</b> Its facts rest "
            "on source and, where a live probe appears, on a <em>testnet</em> — which "
            "may run a different fork schedule than mainnet will. Read every live "
            "claim as \u201cthe testnet does this\u201d.</p>", "note", "prelaunch")
    return None


def anchor_id(section, key):
    """Stable per-entry anchor on a chain page, e.g. `precompiles-0x64`."""
    return f"{section.replace('_', '-')}-{re.sub(r'[^0-9a-zA-Z]+', '', str(key)).lower()}"


LEGEND = ('<p class="legend">'
          '<span class="s-added">➕</span> added · '
          '<span class="s-removed">➖</span> removed / never adopted · '
          '<span class="s-modified">⚠️</span> modified (same address, different behaviour) · '
          '<span class="s-tombstoned">⊘</span> tombstoned (present but always reverts) · '
          '<span class="s-inherited">=</span> same as mainnet · '
          '<span class="s-inherited">=<sup>g</sup></span> same behaviour, different gas · '
          '◌ pending · ◐ opt-in per deployment · ⏳ tombstoning scheduled · '
          '<span class="s-inherited">?</span> not recorded</p>')


def mark(entry, this_slug=None, origin=None, aggregate=False):
    """The grid cell for one entry.

    A `modified` entry whose divergence is pricing only renders as "same, different
    gas" rather than as a warning: it returns the right answer and costs more, which
    is a different class of problem from one that returns a different answer.

    HARD RULE: provenance — where a fact came from, including stack-ancestor
    inheritance (`†`) — appears ONLY on chain-specific pages. `aggregate=True`
    (every axis/index grid) suppresses it, so two chains that agree on a fact read
    as identical there regardless of which one declared it."""
    if entry is None:
        return ""
    st = entry.get("status", "inherited")
    gas_only = st == "modified" and entry.get("divergence") == "gas"
    if gas_only:
        g, cls, tip = "=<sup>g</sup>", "inherited", "same behaviour, different gas"
    else:
        g, cls, tip = model.MARK.get(st, st), st, st
    if entry.get("availability") == "optional": g += "◐"
    if entry.get("tombstoned_at"): g += "⏳"
    if entry.get("pending_conflict"): g += "‼️"
    if not aggregate and origin and this_slug and origin != this_slug:
        g += "†"; tip += f" (from {origin})"
    if entry.get("severity") == "high": tip += " — silent divergence"
    return f'<span class="s-{esc(cls)}" title="{esc(tip)}">{g}</span>'


def cell_link(slug, section, key, inner):
    """A grid mark, linked to that chain's own entry."""
    return (f'<a class="cl" href="../chains/{esc(slug)}.html#{esc(anchor_id(section, key))}">'
            f'{inner}</a>')


def uniform_attr(cells):
    """Flag a row in which every chain says the same thing."""
    return ' data-uniform="1"' if len(set(cells)) <= 1 else ""


def chain_grid(chains, slugs, cols, cell_fn, tid):
    """Chains as ROWS, metrics as COLUMNS.

    This is the orientation for any grid whose cells carry VALUES — a size, a verdict, a
    fee market — rather than single-character marks. A symbol grid reads fine with 47
    columns because each cell is one glyph and the eye scans a row of them; a value grid
    does not, because every column has to be wide enough for its widest string and the
    table runs off the screen. Flipped, the widths are bounded by the number of metrics,
    the chain names sit in the pinned first column where the chains index already puts
    them, and the free-text filter starts matching chain names, which is what a reader
    typing in that box usually wants.

    Symbol grids (header fields, opcodes, the address sections) deliberately keep the
    other orientation. `cell_fn(slug, key)` returns the finished HTML for one cell."""
    head = ["Chain"] + [f'<span title="{esc(b)}">{esc(l)}</span>' for _, l, b in cols]
    rows, attrs = [], []
    for s in slugs:
        rows.append([f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>']
                    + [cell_fn(s, k) for k, _, _ in cols])
        # The baseline row is what "matches mainnet" is measured against, so the JS needs
        # to find it without knowing the slug.
        attrs.append(' data-baseline="1"' if s == "ethereum" else "")
    return table(head, rows, cls="flip", tid=tid, pin=True,
                 row_attrs=attrs, row_chains=slugs)


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------

def markdown(text):
    return _md.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def inline_md(text):
    h = markdown(flat(text)).strip()
    if h.startswith("<p>") and h.endswith("</p>") and h.count("<p>") == 1:
        h = h[3:-4]
    return h


def fee_components(raw):
    """`fee_model.extra_components` is a LIST, of plain strings or {name, note, severity}
    entries — but both the axis grid and the chain page passed it through str(), so every
    chain that had one rendered a Python repr: braces, quotes and all. Returns
    (short, full): names for the grid cell, names with their notes for the chain page."""
    if not isinstance(raw, list):
        return flat(raw), flat(raw)
    names, full = [], []
    for x in raw:
        if isinstance(x, dict):
            n = str(x.get("name", "?"))
            names.append(n)
            full.append(f"{n} — {flat(x['note'])}" if x.get("note") else n)
        else:
            names.append(flat(x))
            full.append(flat(x))
    return ", ".join(names), "; ".join(full)


def teaser(text, limit=240):
    """Trim to a sentence or clause boundary rather than mid-word."""
    s = flat(text)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in (". ", " — ", "; ", ", "):
        i = cut.rfind(sep)
        if i > limit * 0.45:
            return cut[:i + (1 if sep == ". " else 0)].rstrip(" ,;—")
    return cut.rsplit(" ", 1)[0] + "…"


LINK_MAP = {
    "README.md": "index.html",
    "MATRIX.md": "index.html", "PRECOMPILES.md": "axes/precompiles.html",
    "TX-TYPES.md": "axes/tx-types.html", "LINEAGE.md": "axes/lineage.html",
}


def relink(body, depth):
    """Repoint the repo's own Markdown cross-links at their rendered pages."""
    r = rel(depth)

    def sub(m):
        href = m.group(1)
        if href.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        frag = ""
        if "#" in href:
            href, frag = href.split("#", 1)
            frag = "#" + frag
        c = re.match(r"(?:\.\./)?(?:chains/)?([a-z0-9-]+)/(?:SUMMARY\.md|chain\.yaml|)$", href)
        if c:
            return f'href="{r}chains/{c.group(1)}.html{frag}"'
        base = href.lstrip("./")
        if base in LINK_MAP:
            return f'href="{r}{LINK_MAP[base]}{frag}"'
        if re.fullmatch(r"(?:axes|chains)/[a-z0-9-]+\.html|"
                        r"index\.html|silent-divergences\.html", base):
            return f'href="{r}{base}{frag}"'
        return m.group(0)

    return re.sub(r'href="([^"]+)"', sub, body)


def render_md(text, depth):
    return f'<div class="prose">{relink(markdown(text), depth)}</div>'


# --------------------------------------------------------------------------
# notes (findings.yaml)
# --------------------------------------------------------------------------

def load_notes(chains=None):
    """`chains:` is either a list of slugs or a slug -> gloss mapping. The mapping
    form is what a chain page renders: that chain's slice of the note and nothing
    else. Both forms normalize to `slugs` (routing) plus `gloss` (per-chain prose).

    A note naming more than one chain must use the mapping form — otherwise its
    chain pages would carry a survey of other chains, which is what the axis page
    is for."""
    fs = yaml.safe_load((ROOT / "findings.yaml").read_text()) or []
    for f in fs:
        if f.get("axis") not in AXIS_TITLE:
            sys.exit(f"findings.yaml: {f['id']}: axis: {f.get('axis')!r} has no page. "
                     f"Every note renders on an axis page; methodology goes in METHOD.md.")
        ch = f.get("chains")
        if isinstance(ch, dict):
            f["slugs"], f["gloss"] = list(ch), dict(ch)
        else:
            f["slugs"], f["gloss"] = list(ch or []), {}
        if chains is not None:
            bad = [s for s in f["slugs"] if s not in chains]
            if bad:
                sys.exit(f"findings.yaml: {f['id']}: no such chain: {', '.join(bad)}")
        if len(f["slugs"]) > 1 and not f["gloss"]:
            sys.exit(f"findings.yaml: {f['id']}: names {len(f['slugs'])} chains, so "
                     f"`chains:` must map each slug to that chain's slice of the note")
    return sorted(fs, key=lambda f: (f.get("rank", 999), f["id"]))


def axis_href(f, depth):
    return f'{rel(depth)}axes/{esc(f["axis"])}.html#f-{esc(f["id"])}'


def note_html(f, chains, depth, show_axis=True):
    """The full cross-chain reading. Home index and axis pages only."""
    r = rel(depth)
    tags = []
    if show_axis:
        tags.append(f'<a href="{r}axes/{esc(f["axis"])}.html">{esc(AXIS_TITLE[f["axis"]])}</a>')
    for s in f["slugs"]:
        if s in chains:
            tags.append(f'<a href="{r}chains/{esc(s)}.html">{esc(short(s))}</a>')
    tag = f'<p class="tags">{" · ".join(tags)}</p>' if tags else ""
    return (f'<div class="finding">'
            f'{h3(inline_md(f["title"]), "f-" + f["id"])}'
            f'{relink(markdown(flat(f["body"])), depth)}{tag}</div>')


def note_scoped_html(f, chains, slug, depth=1):
    """One chain's slice of a note: the shared premise, then what THIS chain does.
    The cross-chain body stays on the axis page, one link away. Same `f-<id>`
    anchor as the axis page, so published note URLs keep working."""
    r = rel(depth)
    B = [h3(inline_md(f["title"]), "f-" + f["id"])]
    if f.get("lede"):
        B.append(f'<p class="lede">{relink(inline_md(flat(f["lede"])), depth)}</p>')
    if f["gloss"].get(slug):
        B.append(relink(markdown(flat(f["gloss"][slug])), depth))
    elif not f["gloss"]:
        B.append(relink(markdown(flat(f["body"])), depth))   # single-chain note
    axis = AXIS_TITLE[f["axis"]]
    tags = [f'<a href="{axis_href(f, depth)}">Full note · {esc(axis)}</a>']
    others = [s for s in f["slugs"] if s != slug and s in chains]
    if others:
        tags.append("also on " + " · ".join(
            f'<a href="{r}chains/{esc(s)}.html#f-{esc(f["id"])}">{esc(short(s))}</a>'
            for s in others))
    B.append(f'<p class="tags">{" · ".join(tags)}</p>')
    return f'<div class="finding">{"".join(B)}</div>'


def axis_notes(chains, key, depth=1):
    fs = [f for f in load_notes(chains) if f.get("axis") == key]
    if not fs:
        return ""
    return (h2(f'Notes <span class="pill">{len(fs)}</span>', "notes")
            + "".join(note_html(f, chains, depth, show_axis=False) for f in fs))


# --------------------------------------------------------------------------
# per-entry rendering
# --------------------------------------------------------------------------

def provenance(e, on_chain=False):
    """Where this specific fact came from — `src` / `src_live` / `src_doc`, or the
    base_map it was synthesized from.

    HARD RULE: provenance appears ONLY on chain-specific pages. Every caller outside
    `chains/<slug>.html` gets an empty string, so aggregate grids and axis pages
    never show a citation, and two chains that agree on a fact compare as identical
    there regardless of how each one is evidenced."""
    if not on_chain or not isinstance(e, dict):
        return ""
    bits = []
    if e.get("_synth"):
        # synthesized from the chain's precompiles.base_map, whose block carries the
        # full citation — don't repeat that string on every one of 17 rows
        return '<p class="src"><b>from base_map</b></p>'
    if e.get("src"):
        bits.append(f'<b>src</b> {esc(e["src"])}')
    if e.get("src_live"):
        bits.append(f'<b>live</b> {esc(e["src_live"])}')
    if e.get("src_doc"):
        u = esc(e["src_doc"])
        bits.append(f'<b>doc</b> <a href="{u}">{u}</a>'
                    if str(e["src_doc"]).startswith("http") else f"<b>doc</b> {u}")
    return f'<p class="src">{" · ".join(bits)}</p>' if bits else ""


def entry_meta(e):
    # axis-page helper only — no provenance (`inherited_from` is deliberately omitted;
    # it belongs on the chain page)
    bits = []
    st = e.get("status")
    if st: bits.append(f'<span class="pill s-{esc(st)}">{esc(st)}</span>')
    if e.get("divergence"): bits.append(f'<span class="pill">divergence: {esc(e["divergence"])}</span>')
    for k in ("spec", "fork", "availability", "mechanism", "activation_condition"):
        if e.get(k): bits.append(f'<span class="pill">{esc(k)}: {esc(e[k])}</span>')
    if e.get("tombstoned_at"): bits.append(f'<span class="pill">tombstoned_at: {esc(e["tombstoned_at"])}</span>')
    if e.get("severity") == "high": bits.append('<span class="pill s-removed">silent divergence</span>')
    return " ".join(bits)


def addr_section(chains, slug, section, heading, anchor):
    """One chain's complete effective set for an address-keyed section."""
    eff = model.effective(chains, slug, section)
    sec = chains[slug].get(section) or {}
    dyn = sec.get("dynamic_range")
    sec_note = sec.get("note")
    bmap = sec.get("base_map") if section == "precompiles" else \
           sec.get("envelope") if section == "tx_types" else None
    if not eff and not dyn and not sec_note and not bmap:
        return ""
    rows, ids = [], []
    for a in sorted(eff, key=sortkey):
        e, org = eff[a]
        if not isinstance(e, dict): continue
        inh = "" if org == slug else f' <span class="pill">via {esc(org)}</span>'
        rows.append([
            f'<code>{esc(a)}</code>{inh}',
            mark(e, slug, org),
            esc(e.get("name", "")),
            f'<div>{esc(flat(e.get("note")))}</div>{provenance(e, on_chain=True)}',
        ])
        ids.append(f' id="{esc(anchor_id(section, a))}"')
    out = [h2(heading + f' <span class="pill">{len(rows)}</span>', anchor)]
    if sec_note:
        out.append(note(markdown(flat(sec_note))))
    if isinstance(bmap, dict):
        pres = esc(bmap.get("present") or "none")
        if section == "precompiles":
            p256 = bmap.get("p256verify", False)
            p256s = {True: "present", False: "absent", "pending": "pending"}.get(p256, "absent")
            body = (f'<p><b>Base map</b> — <code>0x01</code>–<code>0x11</code>: '
                    f'<code>{pres}</code> {esc(bmap.get("status", "inherited"))}; '
                    f'P256VERIFY at <code>0x0100</code>: {p256s}.</p>')
            lbl = "base map"
        else:
            body = (f'<p><b>Transaction envelope</b> — EIP-2718 types '
                    f'<code>0x00</code>–<code>0x04</code> accepted in mainnet shape: '
                    f'<code>{pres}</code>.</p>')
            lbl = "envelope"
        if bmap.get("note"):
            body += f'<p>{esc(flat(bmap["note"]))}</p>'
        out.append(note(body + provenance(bmap, on_chain=True), "note", lbl))
    if rows:
        out.append(table(["Address", "", "Name", "Note & provenance"],
                         [[r[0], r[1], r[2], f'<div class="wrap">{r[3]}</div>'] for r in rows],
                         row_attrs=ids))
    if isinstance(dyn, dict):
        out.append(note(
            f'<p><b>{esc(dyn.get("name", "dynamic range"))}</b> — '
            f'<code>{esc(dyn.get("pattern", ""))}</code></p>'
            f'<p>{esc(flat(dyn.get("note")))}</p>{provenance(dyn, on_chain=True)}',
            "note", "not enumerable"))
    return "\n".join(out)


def list_section(chains, slug, section, heading, anchor, keyfield):
    """opcodes / header_fields — {added|removed|modified: [ {…} ]}."""
    d = chains[slug].get(section) or {}
    rows, ids = [], []
    for kind in ("added", "removed", "modified", "pending", "tombstoned"):
        for e in d.get(kind) or []:
            if not isinstance(e, dict): continue
            ids.append(f' id="{esc(anchor_id(section, e.get(keyfield, "?")))}"')
            rows.append([
                f'<code>{esc(e.get(keyfield, "—"))}</code>',
                f'<span class="s-{kind}" title="{kind}">{model.MARK[kind]}</span>',
                esc(e.get("name", "")),
                f'<div class="wrap">{esc(flat(e.get("note")))}'
                f'{" <span class=\"pill s-removed\">silent</span>" if e.get("severity") == "high" else ""}'
                f'{provenance(e, on_chain=True)}</div>',
            ])
    if not rows and not d.get("note"):
        return ""
    out = [h2(heading + f' <span class="pill">{len(rows)}</span>', anchor)]
    if d.get("note"):
        out.append(note(markdown(flat(d["note"]))))
    if rows:
        out.append(table([keyfield.title(), "", "Name", "Note & provenance"], rows,
                         row_attrs=ids))
    return "\n".join(out)


# --------------------------------------------------------------------------
# chain pages
# --------------------------------------------------------------------------

def operator_line(slug):
    """The operator's CURRENT affiliations that touch this row, as one sentence. Chain
    pages only, never an aggregate page; former affiliations live in CONTRIBUTING.md."""
    aff = model.current_affiliations(slug)
    if not aff:
        return None
    who = " and ".join(f'{esc(a["org"])} {esc(a["role"])}' for a in aff)
    return (f'The operator of this directory is a current {who}; see '
            f'<a href="{REPO}/blob/main/CONTRIBUTING.md#the-operator">Contributing</a>.')


def contributions_line(c):
    """Credit for merged corrections from contributors affiliated with THIS chain, each
    citing its public issue. Competitors and unaffiliated filers are not recorded."""
    cs = c.get("affiliated_contributions") or []
    if not cs:
        return None
    refs = ", ".join(f'<a href="{REPO}/issues/{int(e["issue"])}">#{int(e["issue"])}</a>'
                     for e in cs)
    return (f'This row includes corrections and information provided by contributors '
            f'affiliated with {esc(name(c))}, vetted by AI against publicly available '
            f'data: {refs}.')


def page_chain(chains, slug):
    c = chains[slug]
    B = []
    doc = documented(c)
    ln, ch = c["lineage"], c["chain"]

    banner = liveness_banner(c)
    if banner: B.append(banner)

    # --- identity -------------------------------------------------------
    up = ln.get("upstream")
    up_html = f'<a href="{esc(up)}.html">{esc(short(up))}</a>' if up in chains else esc(up or "—")
    second = ln.get("second_heritage")
    if second in chains:
        up_html += f' <span class="pill">+ second heritage: <a href="{esc(second)}.html">{esc(short(second))}</a></span>'
    B.append(kv([
        ("Chain ID", f'<code>{esc(ch["chain_id"])}</code>' if ch.get("chain_id") else
                     '<span class="s-inherited">—  not a chain</span>'),
        ("Role", f'<span class="pill">{esc(ch["role"])}</span>' +
                 (f' <span class="pill">equivalence: {esc(ch["equivalence"])}</span>' if ch.get("equivalence") else "")),
        ("Baseline fork", f'<code>{esc(c.get("baseline_fork", "—"))}</code>'),
        ("Upstream", up_html),
        ("Ancestry", " → ".join(esc(x) for x in ln.get("ancestry") or []) or "—"),
        ("Forked from", esc(ln.get("fork_of")) if ln.get("fork_of") else None),
        ("Sync point", esc(ln.get("sync_point")) if ln.get("sync_point") else None),
        ("Consensus", esc(flat((c.get("consensus") or {}).get("engine"))) +
                      (f' · block time {esc((c.get("consensus") or {}).get("block_time"))}'
                       if (c.get("consensus") or {}).get("block_time") else "")),
        ("Note", markdown(flat(ch.get("note"))) if ch.get("note") else None),
        ("Lineage note", markdown(flat(ln.get("note"))) if ln.get("note") else None),
    ]))

    # --- evidence -------------------------------------------------------
    tally = model.evidence_tally(chains, slug)
    B.append(h2("Evidence", "evidence"))
    if doc:
        B.append(note(
            "<p><b>No public client exists</b>, so nothing can be cloned or diffed. Every fact on "
            "this page rests on documentation or on a live probe of the running network, pinned to "
            "a block height. Such a row states what the network <em>did</em>, not what a client "
            "<em>would</em> do.</p>", "note", "documented row"))
    lp = c.get("live_probe") or {}
    B.append(kv([
        ("Client", (f'<a href="{esc(client(c, "repo"))}">{esc(client(c, "name"))}</a> '
                    f'<code>{esc(client(c, "version"))}</code>') if not doc and client(c, "repo") != "—"
                   else ("<em>none public</em>" if doc else esc(client(c, "name")))),
        ("Pinned commit", f'<code>{esc(client(c, "commit"))}</code>' if not doc and client(c, "commit", None) else None),
        ("Language", esc(client(c, "language", None))),
        ("Built on", esc(client(c, "built_on", None))),
        ("Shares evidence with", (lambda x: f'<a href="{esc(x)}.html">{esc(short(x))}</a>' if x in chains else esc(x))(client(c, "shared_with", None)) if client(c, "shared_with", None) else None),
        ("Companion repos", "<br>".join(
            esc(x if isinstance(x, str) else f'{x.get("repo","")} {x.get("version","")}')
            for x in (client(c, "companion_repos", None) or [])) or None),
        ("Client note", markdown(flat(client(c, "note", None))) if client(c, "note", None) else None),
        ("Live probe", (f'<code>{esc(lp.get("endpoint"))}</code> · chain_id {esc(lp.get("chain_id"))} '
                        f'· observed at block <code>{esc(lp.get("observed_at_block"))}</code>') if lp else None),
        ("Fact provenance", f'<code>src:</code> {tally["src"]} · '
                            f'<code>src_live:</code> {tally["src_live"]} · '
                            f'<code>src_doc:</code> {tally["src_doc"]}'),
        ("Operator", operator_line(slug)),
        ("Contributions", contributions_line(c)),
    ]))

    # --- findings + silent divergences -----------------------------------
    fs = [f for f in load_notes(chains) if slug in f["slugs"]]
    if fs:
        B.append(h2(f'Notes <span class="pill">{len(fs)}</span>', "notes"))
        B += [note_scoped_html(f, chains, slug, 1) for f in fs]

    sil = [s for s in model.silent(chains) if s["slug"] == slug]
    if sil:
        B.append(h2(f'Silent divergences <span class="pill">{len(sil)}</span>', "silent"))
        B.append('<p class="lede">Wrong results with no revert, no error and no signal to '
                 'the caller.</p>')
        B.append(table(["Section", "Entry", "What fails silently"],
                       [[f'<span class="pill">{esc(x["where"])}</span>',
                         markdown(x["label"])[3:-4],
                         f'<div class="wrap">{esc(x["note"])}</div>'] for x in sil]))

    # --- forks ----------------------------------------------------------
    fk = c.get("forks") or {}
    tl = fk.get("timeline") or []
    if tl or fk.get("note"):
        B.append(h2("Forks", "forks"))
        if fk.get("note"):
            B.append(note(markdown(flat(fk["note"]))))
        if tl:
            rows = []
            for e in tl:
                t = e.get("activation_time")
                when = (time.strftime("%Y-%m-%d", time.gmtime(t)) if isinstance(t, int) else
                        esc(e.get("activation_condition", "—")))
                rows.append([
                    f'<code>{esc(e.get("name", "?"))}</code>',
                    f'<span class="pill">{esc(e.get("status", "active"))}</span>',
                    esc(when),
                    esc(e.get("mainnet_equivalent") or "—"),
                    f'<div class="wrap">{esc(flat(e.get("note")))}</div>',
                ])
            B.append(table(["Fork", "Status", "Activated", "Mainnet equivalent", "Note"], rows))
        B.append(provenance(fk, on_chain=True))

    # --- EIPs -----------------------------------------------------------
    eips = {k: v for k, v in (c.get("eips") or {}).items() if isinstance(v, dict)}
    if eips:
        B.append(h2(f'EIP deltas <span class="pill">{len(eips)}</span>', "eips"))
        B.append('<p class="lede">An EIP absent from this table is inherited unchanged.</p>')
        rows, eids = [], []
        for k in sorted(eips, key=lambda x: (isinstance(x, str), x)):
            e = eips[k]
            lbl = f'EIP-{k}' if isinstance(k, int) else str(k)
            link = (f'<a href="https://eips.ethereum.org/EIPS/eip-{k}">{esc(lbl)}</a>'
                    if isinstance(k, int) else esc(lbl))
            rows.append([link, mark(e), esc(e.get("name", "")),
                         f'<div class="wrap">{esc(flat(e.get("note")))}{provenance(e, on_chain=True)}</div>'])
            eids.append(f' id="{esc(anchor_id("eips", k))}"')
        B.append(table(["EIP", "", "Name", "Note & provenance"], rows, row_attrs=eids))
        if (c.get("eips") or {}).get("note"):
            B.append(note(markdown(flat(c["eips"]["note"]))))

    # --- address-keyed sections ------------------------------------------
    B.append(addr_section(chains, slug, "tx_types", "Transaction types", "tx-types"))

    nev = c.get("non_evm_transactions")
    if nev:
        B.append(h2("Transactions outside EIP-2718", "non-evm-transactions"))
        B.append(note(markdown(flat(nev.get("note")))))
        if nev.get("entries"):
            B.append(table(["ID", "Name"],
                           [[f'<code>{esc(e.get("id", ""))}</code>', esc(e.get("name", ""))]
                            for e in nev["entries"]]))

    ta_fields, ta_schemes, ta_org = model.tx_auth(chains, slug)
    if ta_schemes or ta_fields.get("note"):
        B.append(h2("Transaction authorization", "tx-authorization"))

        B.append(kv([("Key binding", f'<code>{esc(ta_fields.get("key_binding", "—"))}</code>'
                                      + (f' <span class="pill">via {esc(ta_org.get("key_binding"))}</span>'
                                         if ta_org.get("key_binding") not in (None, slug) else "")),
                     ("Signers per tx", esc(ta_fields.get("signers_per_tx", "—"))),
                     ("Note", markdown(flat(ta_fields.get("note"))) if ta_fields.get("note") else None),
                     ("Inherited note", markdown(flat(ta_fields.get("inherited_note")))
                                        if ta_fields.get("inherited_note") else None)]))
        rows = []
        for n, v in ta_schemes.items():
            pc = v.get("precompile")
            o = ta_org.get(n)
            unp = v.get("authorizes") == "protocol" and pc in (None, "none") and n != "unsigned"
            rows.append([
                f'<code>{esc(n)}</code>'
                + (f' <span class="pill">via {esc(o)}</span>' if o and o != slug else ""),
                f'<span class="pill">{esc(v.get("authorizes", "—"))}</span>',
                (f'<code>{esc(pc)}</code>' if pc not in (None, "none")
                 else ('<span class="s-removed" title="no precompile can verify what the '
                       'protocol accepts">none ⚠️</span>' if unp else '<span class="s-inherited">none</span>')),
                f'<div class="wrap">{esc(flat(v.get("note")))}{provenance(v, on_chain=True)}</div>',
            ])
        B.append(table(["Scheme", "Authorizes", "Paired verifier", "Note & provenance"], rows))

    gas = [(a, e) for a, (e, o) in sorted(model.effective(chains, slug, "precompiles").items(),
                                          key=lambda kv: sortkey(kv[0]))
           if isinstance(e, dict) and e.get("divergence") == "gas"]
    if gas:
        B.append(h2(f'Repriced precompiles <span class="pill">{len(gas)}</span>', "gas"))
        B.append('<p class="lede">Same inputs, same result, different cost. These are not '
                 'flagged in the aggregate grids, because a repriced precompile returns the '
                 'right answer — unlike a semantically modified one. Current live pricing is '
                 'the reference, not the pricing at any historical fork.</p>')
        B.append(table(["Address", "Name", "Pricing"],
                       [[f'<code>{esc(a)}</code>', esc(e.get("name", "")),
                         f'<div class="wrap">{esc(flat(e.get("note")))}{provenance(e, on_chain=True)}</div>']
                        for a, e in gas]))

    B.append(addr_section(chains, slug, "precompiles", "Precompiles", "precompiles"))
    B.append(addr_section(chains, slug, "system_contracts", "System contracts", "system-contracts"))

    st = c.get("system_transactions")
    if st:
        B.append(h2("System transactions", "system-transactions"))
        if isinstance(st, dict) and st.get("note"):
            B.append(note(markdown(flat(st["note"]))))
        ents = st.get("entries") if isinstance(st, dict) else st
        if isinstance(ents, list):
            B.append(table(["Name", "Note"],
                           [[esc((e or {}).get("name", "")),
                             f'<div class="wrap">{esc(flat((e or {}).get("note")))}{provenance(e, on_chain=True)}</div>']
                            for e in ents]))

    B.append(list_section(chains, slug, "opcodes", "Opcodes", "opcodes", "op"))

    # --- transaction lifecycle -------------------------------------------
    tl = lifecycle(chains, slug)
    if tl:
        B.append(h2(f'Ordering &amp; execution <span class="pill">{len(tl)}</span>',
                    "tx-lifecycle"))
        B.append(table(["Question", "Verdict", "What happens"],
                       [[esc(LIFECYCLE_TITLE.get(k, k)),
                         (f'<span class="pill">{esc(d["verdict"])}</span>'
                          + ("" if o == slug else
                             f' <span class="s-inherited" title="inherited">from '
                             f'<a href="{esc(o)}.html">{esc(short(o))}</a></span>')),
                         f'<div class="wrap">{markdown(flat(d.get("answer") or d.get("note")))}'
                         f'{provenance(d, on_chain=True)}</div>']
                        for k, _, _ in LIFECYCLE if (do := tl.get(k)) for d, o in [do]
                        if isinstance(d, dict) and d.get("verdict")]))

    # --- p2p & wire limits -----------------------------------------------
    pp = lifecycle(chains, slug, "p2p")
    if pp:
        B.append(h2(f'P2P &amp; limits <span class="pill">{len(pp)}</span>', "p2p"))
        prows = []
        for k, _, _ in P2P:
            do = pp.get(k)
            if not do: continue
            d, o = do
            if not (isinstance(d, dict) and d.get("verdict") is not None): continue
            tier = d.get("tier")
            val = (f'<span class="pill">{esc(fmt_bytes(d["verdict"]))}</span>'
                   + ("" if o == slug else
                      f' <span class="s-inherited" title="inherited">from '
                      f'<a href="{esc(o)}.html">{esc(short(o))}</a></span>'))
            enf = (f'<span title="{esc(TIER_TITLE.get(tier, tier))}"><code>{esc(tier)}</code>'
                   f'</span>' if tier else '<span class="s-inherited">—</span>')
            body = markdown(flat(d.get("note")))
            # `transports.stack` is the one entry with structure worth showing: which
            # protocol sits at which layer. The grid can only carry the scalar verdict.
            st = d.get("stack")
            if isinstance(st, list) and st:
                body += "<ul>" + "".join(
                    f'<li><code>{esc(e.get("protocol"))}</code> at the '
                    f'{esc(e.get("layer"))} layer — {esc(e.get("purpose"))}</li>'
                    for e in st if isinstance(e, dict)) + "</ul>"
            prows.append([esc(P2P_TITLE.get(k, k)), val, enf,
                          f'<div class="wrap">{body}{provenance(d, on_chain=True)}</div>'])
        if prows:
            B.append(table(["Limit", "Value", "Enforced by", "Why"], prows))

    # --- fee model & header fields ---------------------------------------
    fm = c.get("fee_model") or {}
    if fm:
        B.append(h2("Fee model", "fee-model"))
        B.append(kv([("Metering", f'<code>{esc(fm.get("metering", "—"))}</code>'),
                     ("Fee market", esc(fm.get("fee_market"))),
                     ("Blob fee market", esc(fm.get("blob_fee_market", None))),
                     ("Extra components", esc(fee_components(fm["extra_components"])[1])
                      if fm.get("extra_components") else None),
                     ("Gas limit", esc(fm.get("gas_limit", None))),
                     ("Note", markdown(flat(fm.get("note"))) if fm.get("note") else None)]))
        B.append(provenance(fm, on_chain=True))

    B.append(list_section(chains, slug, "header_fields", "Header fields", "header-fields", "name"))

    nes = c.get("non_eip_specs") or []
    if nes:
        B.append(h2(f'Own spec series <span class="pill">{len(nes)}</span>', "non-eip-specs"))
        B.append(table(["ID", "Name", "Adoption", "Note"],
                       [[f'<code>{esc(e.get("id", ""))}</code>', esc(e.get("name", "")),
                         f'<span class="pill">{esc(e.get("adoption", "—"))}</span>',
                         f'<div class="wrap">{esc(flat(e.get("note")))}{provenance(e, on_chain=True)}</div>']
                        for e in nes if isinstance(e, dict)]))

    # --- gotchas + summary ------------------------------------------------
    g = c.get("gotchas") or []
    if g:
        B.append(h2(f'Gotchas <span class="pill">{len(g)}</span>', "gotchas"))

        B.append("<ul class=\"tight\">" + "".join(f"<li>{esc(flat(x))}</li>" for x in g) + "</ul>")

    sm = ROOT / "chains" / slug / "SUMMARY.md"
    if sm.exists():
        txt = sm.read_text()
        # the H1 is the page title already
        txt = re.sub(r"\A#\s+[^\n]*\n", "", txt)
        B.append(h2("Full write-up", "summary"))
        B.append(render_md(txt, 1))

    # --- reproduce --------------------------------------------------------
    B.append(h2("Reproduce this row", "reproduce"))
    if doc:
        B.append("<p>There is no client to clone. Re-verify by replaying each "
                 "<code>src_live:</code> call against an archive node at the block it names.</p>")
        B.append(f"<pre><code>tools/verify.py {esc(slug)}   # reports SKIP (documented)</code></pre>")
    else:
        B.append(f"<pre><code>tools/clone.sh {esc(slug)}    # fetch the pinned evidence\n"
                 f"tools/verify.py {esc(slug)}   # re-extract from source, diff against chain.yaml</code></pre>")
    B.append(f'<p class="src">Source of record: '
             f'<code>chains/{esc(slug)}/chain.yaml</code>'
             + (f' · <code>chains/{esc(slug)}/SUMMARY.md</code>' if sm.exists() else "") + "</p>")

    lede = inline_md(teaser(ln.get("note") or ch.get("note") or "", 260))
    return layout(f"chains/{slug}.html", name(c), lede,
                  "\n".join(x for x in B if x), chains=chains)




# --------------------------------------------------------------------------
# grids — the lead element of every axis page
# --------------------------------------------------------------------------

def variant_rows(chains, section):
    """One row per distinct feature at an address — not one per address, and not one
    per spelling.

    Splitting on the name string alone over-splits: `BN256_SCALAR_MUL` and `BN256_MUL`
    are one precompile written two ways. The schema's own vocabulary is the better
    signal. At an address mainnet occupies, `inherited` and `modified` both mean "this
    is mainnet's feature, possibly diverging" and stay on one row, marked. A separate
    row is warranted only where the address genuinely carries unrelated features:
    entries `added` at an address mainnet does not use, or an entry flagged
    `conflict`, which is how the dataset records a contested allocation."""
    tab, org = model.addr_rows(chains, section)
    mainnet = {canon(a): e.get("name")
               for a, e in (chains.get("ethereum", {}).get(section) or {}).items()
               if isinstance(e, dict) and str(a).startswith("0x")}
    out, seen = [], set()

    def norm(n):
        return re.sub(r"[^a-z0-9]+", "", str(n or "").lower())

    def emit(a, label, per):
        rid = slugify(f"{a}-{label}") if label else slugify(a)
        if rid in seen:
            i = 2
            while f"{rid}-{i}" in seen: i += 1
            rid = f"{rid}-{i}"
        seen.add(rid)
        out.append((a, label, per, rid))

    for a in sorted(tab, key=sortkey):
        per = tab[a]
        on_mainnet = a in mainnet
        core, variants = {}, {}
        for s, e in per.items():
            if not isinstance(e, dict):
                core[s] = e; continue
            st = e.get("status", "inherited")
            if on_mainnet and st in ("inherited", "modified", "tombstoned", "removed",
                                     "pending", "unrecorded") and not e.get("conflict"):
                core[s] = e                      # mainnet's feature at mainnet's address
            else:
                variants.setdefault(norm(e.get("name")) or "_", {})[s] = e
        if core:
            emit(a, mainnet.get(a) or model.entry_label(core.values()), core)
        for key in sorted(variants, key=lambda k: (-len(variants[k]), k)):
            grp = variants[key]
            emit(a, model.entry_label(grp.values()), grp)
        if not core and not variants:
            emit(a, "", per)
    return out, tab, org


def addr_grid(chains, section, tid, heading, anchor):
    """chain x address, collision-split. Every non-empty cell links to that chain."""
    slugs = order(chains)
    rows_in, tab, org = variant_rows(chains, section)
    rows, attrs = [], []
    for a, label, per, rid in rows_in:
        cells, plain = [], []
        for s in slugs:
            e = per.get(s)
            m = mark(e, s, org.get((a, s)), aggregate=True)
            plain.append(m)
            cells.append(cell_link(s, section, a, m) if e is not None else "")
        rows.append([f'<a href="#e-{esc(rid)}"><code>{esc(a)}</code></a> {esc(label)}'] + cells)
        attrs.append(uniform_attr(plain))
    head = ["Address"] + [f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>' for s in slugs]
    cols = [None] + slugs
    return (h2(f'{heading} <span class="pill">{len(rows)} rows</span>', anchor)
            + filter_box(tid, uniform=True)
            + table(head, rows, tid=tid, pin=True, row_attrs=attrs, col_chains=cols)
            + LEGEND), rows_in, tab, org


def entries_detail(chains, rows_in, org, section):
    """One expandable block per row: which chains carry it, and what each says.

    HARD RULE: this is an axis page, so it carries NO provenance — no `src`/`live`
    citation, no `via <origin>` pill, no `†`. Those live only on the chain pages
    each row links to."""
    out = []
    for a, label, per, rid in rows_in:
        rows = []
        for s in order({k: chains[k] for k in per}):
            e = per[s]
            if not isinstance(e, dict): continue
            rows.append([
                f'<a href="../chains/{esc(s)}.html#{esc(anchor_id(section, a))}">'
                f'{esc(short(s))}</a>',
                mark(e, s, org.get((a, s)), aggregate=True),
                f'<div class="wrap">{entry_meta(e)}<div>{esc(flat(e.get("note")))}</div></div>',
            ])
        out.append(f'<details class="entry" id="e-{esc(rid)}"><summary>'
                   f'<code>{esc(a)}</code><span class="nm">{esc(label)}</span>'
                   f'<span class="cnt">{len(rows)} chains</span></summary>'
                   f'<div class="body">'
                   + table(["Chain", "", "Detail & provenance"], rows) + "</div></details>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# axis pages
# --------------------------------------------------------------------------

def page_precompiles(chains):
    g, rows_in, tab, org = addr_grid(chains, "precompiles", "precompiles-grid",
                                     "Precompiles", "precompiles")
    B = [g]
    B.append(note(
        '<p>The mainnet base range <code>0x01</code>–<code>0x11</code> plus P256VERIFY '
        'at <code>0x0100</code> is shown for <b>every</b> chain, from a <code>base_map</code> '
        'each row declares and <code>verify.py</code> cross-checks against the pinned '
        'clone: <span class="s-inherited">=</span> identical, '
        '<span class="s-removed">➖</span> absent, <span class="s-modified">⚠️</span> '
        'divergent. Turn on <i>hide rows where every chain agrees</i> to collapse the '
        'addresses no chain touches. Every other row lists only the chains that diverge '
        'at that address.</p>', "note", "base range"))
    B.append(axis_notes(chains, "precompiles"))

    dyn = [(s, (chains[s].get("precompiles") or {}).get("dynamic_range")) for s in order(chains)]
    dyn = [(s, d) for s, d in dyn if isinstance(d, dict)]
    if dyn:
        B.append(h2("Addresses that cannot be enumerated", "dynamic"))
        for s, d in dyn:
            B.append(note(
                f'<p><b><a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a> — '
                f'{esc(d.get("name", ""))}</b></p>'
                f'<pre><code>{esc(d.get("pattern", ""))}</code></pre>'
                f'<p>{esc(flat(d.get("note")))}</p>{provenance(d)}', "note", "not enumerable"))

    B.append(h2("Per address", "entries"))
    B.append(entries_detail(chains, rows_in, org, "precompiles"))
    return layout("axes/precompiles.html", "Precompiles",
                  "Every precompile address in the dataset, per chain and per address.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_tx_types(chains):
    g, rows_in, tab, org = addr_grid(chains, "tx_types", "txtypes-grid",
                                     "Transaction types", "tx-types")
    B = [g]
    B.append(note(
        '<p>The EIP-2718 envelope <code>0x00</code>–<code>0x04</code> (Legacy, 2930, '
        '1559, 4844, 7702) is shown for <b>every</b> chain, from an <code>envelope</code> '
        'each row declares: <span class="s-inherited">=</span> accepted in mainnet shape, '
        '<span class="s-removed">➖</span> not accepted. Turn on <i>hide rows where every '
        'chain agrees</i> to collapse the types no chain diverges on. Rows above '
        '<code>0x04</code> list only the chains that define a byte there.</p>',
        "note", "the envelope"))
    B.append(axis_notes(chains, "tx-types"))

    # ---- byte-range occupancy -------------------------------------------
    state, who = {}, {}
    for a in tab:
        try: n = int(a, 16)
        except Exception: continue
        if not 0 <= n <= 0x7f: continue
        sts = {e.get("status", "inherited") for e in tab[a].values() if isinstance(e, dict)}
        who[n] = sorted({short(s) for s in tab[a]})
        if sts & {"added", "modified", "inherited", "pending"}: state[n] = "live"
        elif sts <= {"unrecorded"}: state[n] = "unverified"
        else: state[n] = "vacated"
    free = [n for n in range(0x80) if n not in state]
    counts = {k: sum(1 for v in state.values() if v == k)
              for k in ("live", "unverified", "vacated")}
    B.append(h2("Byte-range occupancy", "frontier"))
    B.append(f'<p class="lede">EIP-2718 allows <code>0x00</code>–<code>0x7f</code>. Mainnet '
             f'allocates upward from <code>0x00</code>, other chains downward from the ceiling. '
             f'Of the 128 legal bytes, <b>{counts["live"]}</b> carry a live type, '
             f'<b>{counts["unverified"]}</b> {"is" if counts["unverified"] == 1 else "are"} '
             f'implemented in a client without anyone establishing reachability, and '
             f'<b>{counts["vacated"]}</b> {"has" if counts["vacated"] == 1 else "have"} been '
             f'deprecated — vacated, but not reusable, because old transactions still carry '
             f'{"it" if counts["vacated"] == 1 else "them"}. <b>{len(free)}</b> are untouched.</p>')
    B.append(table(["Byte", "State", "Claimed by", "As"],
                   [[f'<code>0x{n:02x}</code>',
                     (f'<span class="s-added">live</span>' if state.get(n) == "live" else
                      f'<span class="s-modified">unverified</span>' if state.get(n) == "unverified" else
                      f'<span class="s-removed">vacated</span>' if state.get(n) == "vacated" else
                      '<span class="s-inherited">free</span>'),
                     esc(", ".join(who.get(n, []))) or "—",
                     esc(model.entry_label(tab.get(f"0x{n:02x}", {}).values())) or "—"]
                    for n in range(0x70, 0x80)]))

    # ---- transactions with no type byte ---------------------------------
    B.append(h2("Transactions outside EIP-2718", "non-evm"))
    any_nev = False
    for s in order(chains):
        nev = chains[s].get("non_evm_transactions")
        if not nev or not nev.get("entries"): continue
        any_nev = True
        B.append(h3(f'<a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a>', f"nev-{s}"))
        B.append(f"<p>{esc(flat(nev.get('note')))}</p>")
        B.append(table(["ID", "Name"],
                       [[f'<code>{esc(e.get("id", ""))}</code>', esc(e.get("name", ""))]
                        for e in nev["entries"]]))
    checked = [s for s in order(chains)
               if (chains[s].get("non_evm_transactions") or {}).get("note")
               and not (chains[s].get("non_evm_transactions") or {}).get("entries")]
    if checked:
        B.append(h3("Checked, and there are none", "nev-none"))
        for s in checked:
            B.append(note(f'<p><b><a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a></b> — '
                          f'{esc(flat(chains[s]["non_evm_transactions"].get("note")))}</p>'))
    if not any_nev and not checked:
        B.append("<p><em>none recorded</em></p>")

    B.append(h2("Per type byte", "entries"))
    B.append(entries_detail(chains, rows_in, org, "tx_types"))
    return layout("axes/tx-types.html", "Transaction types",
                  "EIP-2718 type bytes per chain, and transactions carrying no type byte.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_system_contracts(chains):
    g, rows_in, tab, org = addr_grid(chains, "system_contracts", "syscontracts-grid",
                                     "System contracts", "system-contracts")
    B = [g]
    B.append(axis_notes(chains, "system-contracts"))

    mut = [(s, (chains[s].get("system_contracts") or {}).get("mutable_bytecode"))
           for s in order(chains)]
    mut = [(s, m) for s, m in mut if isinstance(m, dict)]
    if mut:
        B.append(h2("Bytecode that changes with no transaction", "mutable"))
        for s, m in mut:
            B.append(note(f'<p><b><a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a></b> — '
                          f'{esc(flat(m.get("note")))}</p>{provenance(m)}',
                          "hot" if m.get("severity") == "high" else "note", "mutable bytecode"))

    B.append(h2("Per address", "entries"))
    B.append(entries_detail(chains, rows_in, org, "system_contracts"))
    return layout("axes/system-contracts.html", "System contracts",
                  "Real bytecode at fixed addresses: predeploys, genesis allocs and "
                  "client-installed code.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_eips(chains):
    slugs, nums = order(chains), model.all_eips(chains)
    GLYPH = {"inherited": "=", "added": "➕", "removed": "➖", "modified": "⚠️",
             "pending": "◌", "unrecorded": "?", "tombstoned": "⊘"}
    rows, attrs = [], []
    for n in nums:
        lbl = f"EIP-{n}" if isinstance(n, int) else str(n)
        link = (f'<a href="https://eips.ethereum.org/EIPS/eip-{n}">{esc(lbl)}</a>'
                if isinstance(n, int) else esc(lbl))
        nm = ""
        for s in slugs:
            e, _ = model.eip_entry(chains, s, n)
            if isinstance(e, dict) and e.get("name"): nm = e["name"]; break
        cells, plain = [], []
        for s in slugs:
            st, o = model.eip_status(chains, s, n)
            g = GLYPH.get(st, st)          # no `†`: inheritance origin is provenance,
            plain.append(g)                # and provenance lives only on chain pages
            inner = f'<span class="s-{esc(st)}" title="{esc(st)}">{g}</span>'
            e, decl = model.eip_entry(chains, s, n)
            cells.append(cell_link(decl, "eips", n, inner) if e is not None else inner)
        rows.append([f'<a href="#eip-{esc(str(n))}">{link}</a> {esc(nm)}'] + cells)
        attrs.append(uniform_attr(plain))
    head = ["EIP"] + [f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>' for s in slugs]

    B = [h2(f'EIP activation set <span class="pill">{len(nums)} EIPs</span>', "eips"),
         filter_box("eips-grid", uniform=True),
         table(head, rows, tid="eips-grid", pin=True, row_attrs=attrs, col_chains=[None] + slugs),
         LEGEND]
    B.append(axis_notes(chains, "eips"))

    B.append(h2("Baseline fork claimed", "baselines"))
    B.append('<p class="lede">Grouped by the mainnet fork each chain claims equivalence to, '
             'most recent fork first. Within a group, the chain with the most recent dated '
             'activation comes first; chains whose forks are gated on something other than a '
             'timestamp — an ArbOS version, a block number — have no date and follow.</p>')
    for fork, rows_ in model.by_baseline(chains):
        B.append(h3(f'{esc(fork)} <span class="pill">{len(rows_)} chains</span>',
                    f"baseline-{slugify(fork)}"))
        B.append(table(["Chain", "Most recent dated fork", "Client", "Role"],
                       [[f'<a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a>',
                         (time.strftime("%Y-%m-%d", time.gmtime(model.last_fork_time(chains, s)))
                          if model.last_fork_time(chains, s) else
                          '<span class="s-inherited">not timestamp-gated</span>'),
                         ("<em>none public</em>" if documented(chains[s])
                          else f'{esc(client(chains[s], "name"))} '
                               f'<code>{esc(client(chains[s], "version"))}</code>'),
                         f'<span class="pill">{esc(chains[s]["chain"]["role"])}</span>']
                        for s in rows_]))

    B.append(h2("Per EIP", "entries"))
    for n in nums:
        per = {}
        for s in slugs:
            e, o = model.eip_entry(chains, s, n)
            if isinstance(e, dict): per[s] = (e, o)
        if not per: continue
        lbl = f"EIP-{n}" if isinstance(n, int) else str(n)
        nm = next((e.get("name", "") for e, _ in per.values() if e.get("name")), "")
        # an inheriting chain has no row of its own for this EIP; still link it to
        # its own page (no `via` pill — that origin is provenance, chain-pages only)
        tr = [[f'<a href="../chains/{esc(s)}.html#{esc(anchor_id("eips", n))}">'
               f'{esc(short(s))}</a>',
               mark(e, s, o, aggregate=True),
               f'<div class="wrap">{entry_meta(e)}<div>{esc(flat(e.get("note")))}</div></div>']
              for s, (e, o) in per.items()]
        B.append(f'<details class="entry" id="eip-{esc(str(n))}"><summary>'
                 f'<code>{esc(lbl)}</code><span class="nm">{esc(nm)}</span>'
                 f'<span class="cnt">{len(tr)} chains</span></summary><div class="body">'
                 + table(["Chain", "", "Detail & provenance"], tr) + "</div></details>")
    return layout("axes/eips.html", "EIP activation set",
                  "Which EIPs are live on each chain, stated against mainnet at that "
                  "chain's baseline fork.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_cryptography(chains):
    """Principal axis is the algorithm. Each algorithm gets two rows, because the two
    questions come apart in both directions: whether the protocol will accept a
    signature in that scheme, and whether contract code can verify one."""
    slugs = order(chains)
    fams = [f for f in model.FAMILIES if f != "other"]
    rows, attrs = [], []
    for fam in fams:
        members = model.FAMILIES[fam]
        for kind, label in (("authorize", "authorizes a transaction"),
                            ("verify", "verifiable by a precompile")):
            cells, plain = [], []
            for s in slugs:
                _, sch, org = model.tx_auth(chains, s)
                hit, pc, ac = False, None, False
                for m in members:
                    v = sch.get(m)
                    if not v: continue
                    if kind == "authorize" and v.get("authorizes") in ("protocol", "account_code"):
                        hit = True
                        ac = ac or v.get("authorizes") == "account_code"
                    if kind == "verify" and v.get("precompile") not in (None, "none"):
                        hit, pc = True, v.get("precompile")
                if hit:
                    g = "✓" + ("ᴬᶜ" if ac else "")
                    tip = f"{fam} {label}" + (f" at {pc}" if pc else "")
                    inner = f'<span class="s-added" title="{esc(tip)}">{g}</span>'
                    cells.append(f'<a class="cl" href="../chains/{esc(s)}.html#tx-authorization">'
                                 f'{inner}</a>')
                else:
                    g = "–"
                    cells.append(f'<span class="s-inherited" title="not {label}">{g}</span>')
                plain.append(g)
            rows.append([f'<code>{esc(fam)}</code> <span class="sub">{esc(label)}</span>'] + cells)
            attrs.append(uniform_attr(plain))
    head = ["Algorithm"] + [f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>' for s in slugs]

    B = [h2(f'Cryptography <span class="pill">{len(fams)} algorithms</span>', "cryptography"),
         filter_box("crypto-grid", uniform=True),
         table(head, rows, tid="crypto-grid", pin=True, row_attrs=attrs, col_chains=[None] + slugs),
         '<p class="legend"><span class="s-added">✓</span> yes · '
         '<span class="s-inherited">–</span> no · '
         '<code>ᴬᶜ</code> only through account-abstraction code: the protocol runs the '
         'account\'s own validator, which decides.</p>']
    B.append(axis_notes(chains, "cryptography"))

    unp = [(s, n, v) for s, n, v in model.unpaired(chains) if n != "unsigned"]
    if unp:
        B.append(h2("Authorizes with no precompile to verify it", "unpaired"))
        for s, n, v in unp:
            B.append(note(f'<p><b><a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a> — '
                          f'<code>{esc(n)}</code></b></p><p>{esc(flat(v.get("note")))}</p>'
                          f'{provenance(v)}', "note", "unpaired"))

    B.append(h2("Per scheme", "entries"))
    schemes = model.schemes(chains)
    for fam in model.FAMILIES:
        present = [m for m in model.FAMILIES[fam] if m in schemes]
        if not present: continue
        for m in present:
            tr = [[f'<a href="../chains/{esc(s)}.html#tx-authorization">{esc(short(s))}</a>',
                   f'<span class="pill">{esc(v.get("authorizes", "—"))}</span>',
                   (f'<code>{esc(v.get("precompile"))}</code>'
                    if v.get("precompile") not in (None, "none")
                    else '<span class="s-inherited">none</span>'),
                   f'<div class="wrap">{entry_meta(v)}<div>{esc(flat(v.get("note")))}</div>'
                   f'{provenance(v)}</div>']
                  for s, v, o in schemes[m]]
            B.append(f'<details class="entry" id="s-{esc(m)}"><summary><code>{esc(m)}</code>'
                     f'<span class="nm">{esc(fam)}</span>'
                     f'<span class="cnt">{len(tr)} chains</span></summary><div class="body">'
                     + table(["Chain", "Authorizes", "Verifier", "Detail & provenance"], tr)
                     + "</div></details>")
    return layout("axes/cryptography.html", "Cryptography",
                  "Which algorithms can authorize a transaction, and which have a "
                  "precompile that verifies them.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_opcodes(chains):
    slugs = order(chains)
    per = {}
    for s in slugs:
        d = chains[s].get("opcodes") or {}
        for kind in ("added", "removed", "modified", "pending", "tombstoned"):
            for e in d.get(kind) or []:
                if isinstance(e, dict):
                    per.setdefault(str(e.get("op", "n/a")), []).append((s, kind, e))
    base = model.baseline_opcodes(chains)
    fork_intro = model.baseline_opcode_forks(chains)
    all_ops = sorted(set(base) | set(per), key=sortkey)

    rows, attrs = [], []
    for op in all_ops:
        entries = {s: (kind, e) for s, kind, e in per.get(op, [])}
        on_mainnet = (op in base) or any(k in ("removed", "modified")
                                         for k, _ in entries.values())
        intro = fork_intro.get(op)
        cells, plain = [], []
        for s in slugs:
            if s in entries:
                kind, e = entries[s]
                g, cls = {"removed": ("–", "s-removed"),
                          "pending": (model.MARK["pending"], "s-pending"),
                          "tombstoned": (model.MARK["tombstoned"], "s-tombstoned")}.get(
                              kind, ("★", "s-added"))
                tip = f'{kind}: {e.get("name", "")}'.strip(": ")
                plain.append(g)
                cells.append(cell_link(s, "opcodes", op,
                             f'<span class="{cls}" title="{esc(tip)}">{g}</span>'))
            elif intro and model.fork_rank(
                    str(chains[s].get("baseline_fork", "")).lower()) < model.fork_rank(intro):
                # opcode postdates this chain's baseline fork — nothing there.
                # a distinct `plain` token keeps the row visible under the
                # "hide rows where every chain agrees" filter.
                plain.append("∅")
                cells.append("")
            else:
                g = "✓" if on_mainnet else "–"
                plain.append(g)
                cells.append(f'<span class="s-inherited" title="'
                             + ("mainnet semantics" if on_mainnet else "not present")
                             + f'">{g}</span>')
        nm = base.get(op) or next(
            (e.get("name", "") for _, e in entries.values() if e.get("name")), "")
        rows.append([f'<code>{esc(op)}</code> {esc(nm)}'] + cells)
        attrs.append(uniform_attr(plain))
    head = ["Opcode"] + [f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>' for s in slugs]

    B = [h2(f'Opcodes <span class="pill">{len(all_ops)} opcodes</span>', "opcodes"),
         filter_box("opcodes-grid", uniform=True),
         table(head, rows, tid="opcodes-grid", pin=True, row_attrs=attrs, col_chains=[None] + slugs),
         '<p class="legend"><span class="s-inherited">✓</span> present with mainnet '
         'semantics · <span class="s-added">★</span> present and divergent · '
         f'<span class="s-pending">{model.MARK["pending"]}</span> pending (merged '
         'upstream, not yet live) · <span class="s-removed">–</span> not present. A '
         'blank cell means the opcode postdates the chain\'s baseline fork. Cells '
         'are as shipped for each row\'s pinned client.</p>']
    B.append(axis_notes(chains, "opcodes"))

    other = []
    for s in slugs:
        for e in chains[s].get("non_eip_specs") or []:
            if isinstance(e, dict) and re.search(r"wasm|webassembly|vm\b", str(e.get("name", "")), re.I):
                other.append((s, e.get("id", ""), e.get("name", ""), flat(e.get("note"))))
        for e in (chains[s].get("opcodes") or {}).get("added") or []:
            if isinstance(e, dict) and str(e.get("op")) == "n/a":
                other.append((s, "—", e.get("name", ""), flat(e.get("note"))))
    if other:
        B.append(h2("Execution environments beside the EVM", "other-vms"))
        B.append(table(["Chain", "ID", "Name", "Note"],
                       [[f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>',
                         f'<code>{esc(i)}</code>', esc(n), f'<div class="wrap">{esc(nt)}</div>']
                        for s, i, n, nt in other]))

    B.append(h2("Per entry", "entries"))
    rows = [[f'<code>{esc(op)}</code>',
             f'<a href="../chains/{esc(s)}.html#{esc(anchor_id("opcodes", op))}">{esc(short(s))}</a>',
             f'<span class="s-{kind}" title="{kind}">{model.MARK[kind]}</span>',
             esc(e.get("name", "")),
             f'<div class="wrap">{esc(flat(e.get("note")))}{provenance(e)}</div>']
            for op in sorted(per, key=sortkey) for s, kind, e in per[op]]
    B.append(table(["Opcode", "Chain", "", "Name", "Detail"], rows, tid="opcode-entries"))
    return layout("axes/opcodes.html", "Opcodes",
                  "The full instruction set per chain, and execution environments that "
                  "are not the EVM.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


FEE_PROPS = [
    ("metering",         "Metering",         "What the chain counts: gas, or something else."),
    ("fee_market",       "Fee market",       "How the price per unit is set."),
    ("blob_fee_market",  "Blob fee market",  "The independent market for blob data, where one exists."),
    ("extra_components", "Extra components", "Charges beyond the base fee and priority tip."),
]


def page_fees(chains):
    """Two grids in two orientations, deliberately. The fee properties carry VALUES, so
    chains are rows; the header fields carry single-character MARKS, so chains stay
    columns. The rule is the cell content, not the page."""
    slugs = order(chains)

    def cell(s, key):
        raw = (chains[s].get("fee_model") or {}).get(key)
        if key == "extra_components":
            short_, full = fee_components(raw)
            return ('<span class="s-inherited">—</span>' if not short_ else
                    f'<a class="cl" href="../chains/{esc(s)}.html#fee-model" '
                    f'title="{esc(full)}">{esc(teaser(short_, 40))}</a>')
        v = teaser(raw, 40) or "—"
        if v == "—":
            return '<span class="s-inherited">—</span>'
        return (f'<a class="cl" href="../chains/{esc(s)}.html#fee-model" '
                f'title="{esc(flat(raw))}">{esc(v)}</a>')

    grid = chain_grid(chains, slugs, FEE_PROPS, cell, "fees-grid")

    # header fields, grouped by field name — marks, so the orientation stays put
    per = {}
    for s in slugs:
        hf = chains[s].get("header_fields") or {}
        for kind in ("added", "removed", "modified"):
            for e in hf.get(kind) or []:
                if isinstance(e, dict):
                    per.setdefault(str(e.get("name", "?")), []).append((s, kind, e))
    hrows, hattrs = [], []
    for f in sorted(per):
        entries = {s: (k, e) for s, k, e in per[f]}
        cells, plain = [], []
        for s in slugs:
            if s in entries:
                k, e = entries[s]
                g = model.MARK[k]
                plain.append(g)
                cells.append(cell_link(s, "header_fields", f,
                             f'<span class="s-{k}" title="{esc(k)}">{g}</span>'))
            else:
                plain.append("=")
                cells.append('<span class="s-inherited" title="as mainnet">=</span>')
        hrows.append([f'<code>{esc(f)}</code>'] + cells)
        hattrs.append(uniform_attr(plain))

    B = [h2(f'Fees & envelope <span class="pill">{len(FEE_PROPS)} properties</span>', "fees"),
         filter_box("fees-grid", uniform="hide chains that match mainnet exactly"), grid,
         '<p class="legend">Values are truncated; hover for the full text, or follow a cell '
         'to that chain\'s fee model.</p>']
    B.append(h2(f'Header fields <span class="pill">{len(per)} fields</span>', "header-fields"))
    B.append(filter_box("hdr", uniform=True))
    B.append(table(["Field"] + [f'<a href="../chains/{esc(s)}.html">{esc(short(s))}</a>'
                                for s in slugs],
                   hrows, tid="hdr", pin=True, row_attrs=hattrs, col_chains=[None] + slugs))
    B.append('<p class="legend">This second grid keeps chains as <em>columns</em>: its cells '
             'are single marks, which stay scannable across many columns where a column of '
             'prose would not. Orientation follows the cell content, not the page.</p>')
    B.append(LEGEND)
    B.append(axis_notes(chains, "fees-envelope"))
    return layout("axes/fees-envelope.html", "Fees & envelope",
                  "Metering and fee markets per chain, and header fields that differ "
                  "from mainnet.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_ordering(chains):
    """Mainnet answers every question here by construction: validation runs before
    ordering, so a transaction that is ordered and then invalid is not a state it can
    reach. Every row is a chain that separated the two and had to invent an answer."""
    slugs = order(chains)
    data = {s: lifecycle(chains, s) for s in slugs}
    cols = [c for c in LIFECYCLE
            if any((d or {}).get("verdict") for s in slugs
                   for d, _ in [data[s].get(c[0], (None, s))])]

    def cell(s, key):
        # See page_p2p: no inheritance mark when chains are rows.
        d, _ = data[s].get(key, (None, s))
        v = d.get("verdict") if isinstance(d, dict) else None
        if not v:
            return '<span class="s-inherited" title="not established">—</span>'
        return cell_link(s, "tx-lifecycle", key,
                         f'<span class="pill" title="'
                         f'{esc(flat(d.get("answer") or d.get("note")))[:400]}">'
                         f'{esc(v)}</span>')

    B = [h2(f'Lifecycle <span class="pill">{len(cols)} questions</span>', "lifecycle"),
         filter_box("lifecycle-grid", uniform="hide chains that match mainnet exactly"),
         chain_grid(chains, slugs, cols, cell, "lifecycle-grid"),
         '<p class="legend">Mainnet reaches none of these states: nonce, balance and gas '
         'price are checked <em>before</em> a transaction can be ordered, so the '
         '<code>ethereum</code> row is the baseline and reads <code>unreachable</code> / '
         '<code>preserved</code>. A <code>—</code> means the question is not established for '
         'that chain, not that it behaves like mainnet. Hover a verdict for the finding; '
         'follow it for the cited source.</p>']
    B.append(axis_notes(chains, "ordering"))
    return layout("axes/ordering.html", "Ordering & execution",
                  "What happens to a transaction between being ordered and being executed.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_p2p(chains):
    """The axis exists because "max transaction size" reads like one number and is not
    one. Mainnet's 128 KiB is a client DoS policy every other EL copied; the first
    consensus size limit arrived only with EIP-7934. So the grid renders the tier beside
    every size, and a row whose sizes differ from mainnet's is often answering a
    different question rather than the same one differently — Arbitrum's smaller cap is
    an L1 batch budget, not a gossip bound."""
    slugs = order(chains)
    data = {s: lifecycle(chains, s, "p2p") for s in slugs}
    cols = [c for c in P2P
            if any((d or {}).get("verdict") is not None
                   for s in slugs for d, _ in [data[s].get(c[0], (None, s))])]

    def cell(s, key):
        # No inheritance mark in this orientation. With chains as rows a `=` sits inside
        # every cell of nine op-stack descendants, which reads as a value rather than a
        # provenance note; the chain page states where an entry came from.
        d, _ = data[s].get(key, (None, s))
        v = d.get("verdict") if isinstance(d, dict) else None
        if v is None:
            return '<span class="s-inherited" title="not established">—</span>'
        tier = d.get("tier")
        tag = (f'<span class="tier" title="{esc(TIER_TITLE.get(tier, tier))}">'
               f'{esc(tier)}</span>') if tier else ""
        return cell_link(s, "p2p", key,
                         f'<span class="pill" title="{esc(flat(d.get("note")))[:400]}">'
                         f'{esc(fmt_bytes(v))}</span>') + tag

    B = [h2(f'Wire limits <span class="pill">{len(cols)} questions</span>', "limits"),
         filter_box("p2p-grid", uniform="hide chains that match mainnet exactly"),
         chain_grid(chains, slugs, cols, cell, "p2p-grid"),
         '<p class="legend">Every size carries the tier that enforces it. '
         '<code>consensus</code> means a block breaking it is invalid; <code>policy</code> '
         'means only the mempool objects, so an oversized transaction is still perfectly '
         'valid in a block and merely cannot get there by gossip; <code>transport</code> '
         'means the wire will not move it. Mainnet\'s 128 KiB is <code>policy</code> — it '
         'is not a rule, and the gap between it and the ~1.6 MB that EIP-7825 and EIP-7623 '
         'jointly permit is the space private orderflow occupies. A <code>—</code> means '
         'the question is not established for that chain, not that it matches mainnet. '
         'Hover a value for the finding; follow it for the cited source.</p>']
    B.append(axis_notes(chains, "p2p"))
    return layout("axes/p2p.html", "P2P & limits",
                  "How big a transaction, block or message may be, who enforces each "
                  "bound, and which transports carry them.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


def page_lineage(chains):
    """Two independent ancestries. A chain's code can descend from one project while
    its consensus rules track a different fork line, and conflating them makes both
    unreadable — Linea's client is Besu, and neither fact predicts the other."""
    slugs = order(chains)

    # ---- (a) code lineage -------------------------------------------------
    kids = {}
    for s in slugs:
        p, kind = model.code_parent(chains, s)
        kids.setdefault((p, kind), []).append(s)
    lines = []
    ROOTS = [("go-ethereum", "go-ethereum"), ("hyperledger-besu", "hyperledger-besu"),
             ("reth", "reth"), ("independent", "no shared client lineage")]
    lines.append("ethereum — go-ethereum (the reference implementation)")
    for root, label in ROOTS:
        rows_ = kids.get((root, "codebase"), [])
        if not rows_ and root != "go-ethereum": continue
        lines.append("")
        lines.append(f"{label}")
        for s in rows_:
            if s == "ethereum": continue
            lines.append(f'  └── <a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a> '
                         f'({esc(client(chains[s], "name"))}, {esc(client(chains[s], "language"))})')
            for k in kids.get((s, "row"), []):
                lines.append(f'      └── <a href="../chains/{esc(k)}.html">{esc(name(chains[k]))}</a> '
                             f'({esc(client(chains[k], "name"))})')
    orphan = [s for s in slugs if model.code_parent(chains, s) == (None, None) and s != "ethereum"]
    for s in orphan:
        lines.append("")
        lines.append(f'<a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a> — '
                     f'no public client')

    B = [h2("Code lineage", "code"),
         '<p class="lede">Which codebase each client is a fork of. Says nothing about '
         'which consensus rules the chain follows.</p>',
         "<pre><code>" + "\n".join(lines) + "</code></pre>"]

    # ---- (b) fork lineage -------------------------------------------------
    B.append(h2("Fork lineage", "forks"))
    B.append('<p class="lede">Each chain placed under the most recent mainnet fork it has '
             'merged, most recent first. Says nothing about whose code it runs.</p>')
    flines = []
    for fork, rows_ in model.by_baseline(chains):
        flines.append(f"{fork}")
        for s in rows_:
            t = model.last_fork_time(chains, s)
            when = time.strftime("%Y-%m-%d", time.gmtime(t)) if t else "not timestamp-gated"
            flines.append(f'  └── <a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a> '
                          f'({esc(when)})')
        flines.append("")
    B.append("<pre><code>" + "\n".join(flines).rstrip() + "</code></pre>")

    B.append(axis_notes(chains, "lineage"))

    odd = [(s, chains[s]["lineage"]) for s in slugs
           if chains[s]["lineage"].get("second_heritage") or chains[s]["lineage"].get("sync_point")]
    if odd:
        B.append(h2("Where lineage is not a tree", "not-a-tree"))
        B.append(table(["Chain", "Second heritage", "Sync point"],
                       [[f'<a href="../chains/{esc(s)}.html">{esc(name(chains[s]))}</a>',
                         (f'<a href="../chains/{esc(l["second_heritage"])}.html">'
                          f'{esc(short(l["second_heritage"]))}</a>'
                          if l.get("second_heritage") in chains else esc(l.get("second_heritage", "—"))),
                         f'<div class="wrap">{esc(flat(l.get("sync_point")) or "—")}</div>']
                        for s, l in odd]))
    return layout("axes/lineage.html", "Lineage",
                  "Code ancestry and fork ancestry, tracked separately.",
                  "\n".join(x for x in B if x), wide=True, chains=chains)


# --------------------------------------------------------------------------
# top-level pages
# --------------------------------------------------------------------------

def page_index(chains):
    slugs = order(chains)
    sil = model.silent(chains)
    B = [h2("Axes", "axes")]
    B.append('<div class="grid">' + "".join(
        f'<div class="card"><h3><a href="axes/{esc(k)}.html">{esc(t)}</a></h3><p>{esc(d)}</p></div>'
        for k, t, d in AXES) +
        '<div class="card"><h3><a href="silent-divergences.html">Silent divergences</a></h3>'
        '<p>Entries that produce a wrong result with no revert, no error and no signal.</p></div>'
        + "</div>")

    B.append(h2("Chains", "chains"))
    B.append(filter_box("rowlist"))
    rows = []
    for s in slugs:
        c = chains[s]
        rows.append([
            f'<a href="chains/{esc(s)}.html">{esc(name(c))}</a>',
            f'<code>{esc(c["chain"].get("chain_id") or "—")}</code>',
            f'<span class="pill">{esc(c["chain"]["role"])}</span>',
            f'<code>{esc(c.get("baseline_fork", "—"))}</code>',
            str(len([x for x in sil if x["slug"] == s]) or ""),
            ("<em>none public</em>" if documented(c)
             else f'{esc(client(c, "name"))} <code>{esc(client(c, "version"))}</code>'),
        ])
    B.append(table(["Chain", "Chain ID", "Role", "Baseline", "Divergences", "Client"],
                   rows, tid="rowlist"))
    B.append('<p class="legend"><code>op-stack</code> and <code>avalanche-subnet</code> are '
             'not chains: one is a shared codebase holding its descendants\' common deltas, '
             'the other a template instantiated per deployment.</p>')

    B.append(h2("Notes", "notes"))
    B.append(table(["Subject", "Axis", "Chains"], [
        [f'<a href="axes/{esc(f["axis"])}.html#f-{esc(f["id"])}">{inline_md(f["title"])}</a>',
         f'<a href="axes/{esc(f["axis"])}.html">{esc(AXIS_TITLE[f["axis"]])}</a>',
         f'<div class="wrap">' + (", ".join(
             f'<a href="chains/{esc(s)}.html">{esc(short(s))}</a>'
             for s in f["slugs"] if s in chains) or "—") + "</div>"]
        for f in load_notes(chains)]))
    return layout("index.html", "EVM Directory",
                  "EVM differences across major EVM chains, stated as deltas against "
                  "Ethereum Mainnet.", "\n".join(B))


def page_chains_index(chains):
    slugs = order(chains)
    sil = model.silent(chains)
    _base_ops = set(model.baseline_opcodes(chains))
    B = [h2("Chains", "chains"), filter_box("chainlist")]
    rows = []
    for s in slugs:
        c = chains[s]
        counts = {sec: len(model.effective(chains, s, sec)) for sec in model.ADDR_SECTIONS}
        rows.append([
            f'<a href="{esc(s)}.html">{esc(name(c))}</a>',
            f'<span class="pill">{esc(c["chain"]["role"])}</span>',
            ((lambda lv: "—" if lv is None else
              f'<span class="pill">{esc(lv)}</span>' if lv == "live" else
              f'<b class="s-removed">{esc(lv)}</b>')(model.liveness(c))),
            (f'<a href="{esc(c["lineage"]["upstream"])}.html">'
             f'{esc(short(c["lineage"]["upstream"]))}</a>'
             if c["lineage"].get("upstream") in chains else "—"),
            f'<code>{esc(c.get("baseline_fork", "—"))}</code>',
            str(counts["precompiles"]), str(counts["tx_types"]), str(counts["system_contracts"]),
            str(sum(1 for e in (c.get("opcodes") or {}).get("added") or []
                    if isinstance(e, dict) and str(e.get("op")) not in _base_ops)),
            str(len([x for x in sil if x["slug"] == s]) or ""),
        ])
    B.append(table(["Chain", "Role", "Liveness", "Upstream", "Baseline", "Precompiles",
                    "Tx types", "System contracts", "Opcodes", "Divergences"],
                   rows, tid="chainlist"))
    B.append('<p class="legend">Counts are the <em>effective</em> set — entries inherited '
             'from a stack ancestor are included. Liveness: <code>live</code> runs · '
             '<code>prelaunch</code> has never produced a mainnet block · '
             '<code>halted</code> stopped · <code>unreachable</code> answers nowhere · '
             '<code>dead: shutdown</code> was switched off deliberately and announced · '
             '<code>dead: abandoned</code> went dark with no announcement and no way out. '
             'A dead row\u2019s facts are final and still worth citing; it is simply not a '
             'chain to build against.</p>')
    return layout("chains/index.html", "Chains",
                  "Every row in the dataset, with its effective feature counts.",
                  "\n".join(B), wide=True)


def page_silent(chains):
    sil = model.silent(chains)
    by_chain, by_sec = {}, {}
    for x in sil:
        by_chain.setdefault(x["slug"], []).append(x)
        by_sec.setdefault(x["where"], []).append(x)

    B = ['<p class="lede">Entries the dataset marks <code>severity: high</code>: a divergence '
         'that produces a wrong result with <b>no revert, no error and no signal to the '
         'caller</b>.</p>']
    B.append(h2("By section", "by-section"))
    B.append(table(["Section", "Entries", "Chains"],
                   [[f'<code>{esc(k)}</code>', str(len(v)),
                     f'<div class="wrap">' + ", ".join(
                         f'<a href="chains/{esc(s)}.html#silent">{esc(short(s))}</a>'
                         for s in sorted({y["slug"] for y in v}, key=lambda z: order(chains).index(z)))
                     + "</div>"]
                    for k, v in sorted(by_sec.items(), key=lambda kv: -len(kv[1]))]))
    B.append(h2("By chain", "by-chain"))
    B.append(table(["Chain", "Entries", "Sections"],
                   [[f'<a href="chains/{esc(s)}.html#silent">{esc(name(chains[s]))}</a>',
                     str(len(v)),
                     f'<div class="wrap">' + ", ".join(
                         f'<code>{esc(k)}</code>' for k in sorted({y["where"] for y in v}))
                     + "</div>"]
                    for s, v in sorted(by_chain.items(), key=lambda kv: -len(kv[1]))]))
    B.append(h2("Every entry", "all"))
    B.append(filter_box("silent"))
    B.append(table(["Chain", "Section", "Entry"],
                   [[f'<a href="chains/{esc(x["slug"])}.html#silent">{esc(short(x["slug"]))}</a>',
                     f'<span class="pill">{esc(x["where"])}</span>',
                     inline_md(x["label"])] for x in sil], tid="silent"))
    B.append('<p class="legend">Detail for each entry is on that chain\'s page.</p>')
    return layout("silent-divergences.html", "Silent divergences",
                  "Entries marked severity: high, collected across the dataset.",
                  "\n".join(B), wide=True)


# --------------------------------------------------------------------------
# page registry + incremental build
# --------------------------------------------------------------------------

class Page:
    def __init__(self, path, inputs, fn):
        self.path, self.inputs, self.fn = path, [pathlib.Path(i) for i in inputs], fn


def registry(chains):
    """Every output page, with the input files it actually reads.

    The input list is what makes the build incremental and what `--list` prints,
    so it has to be honest: an axis page reads every chain.yaml, a chain page
    reads its own two files plus any ancestor it inherits from."""
    findings = ROOT / "findings.yaml"
    all_yaml = [ROOT / "chains" / s / "chain.yaml" for s in sorted(chains)]
    pages = [
        Page("index.html", all_yaml + [findings], page_index),
        Page("chains/index.html", all_yaml, page_chains_index),
        Page("silent-divergences.html", all_yaml, page_silent),
    ]
    axis_fn = {"eips": page_eips, "precompiles": page_precompiles, "tx-types": page_tx_types,
               "ordering": page_ordering, "p2p": page_p2p,
               "cryptography": page_cryptography, "opcodes": page_opcodes,
               "system-contracts": page_system_contracts, "fees-envelope": page_fees,
               "lineage": page_lineage}
    for k, _, _ in AXES:
        pages.append(Page(f"axes/{k}.html", all_yaml + [findings],
                          (lambda f: lambda ch: f(ch))(axis_fn[k])))
    for s in sorted(chains):
        # operators.yaml feeds every chain page, not only the rows it names today: an
        # affiliation gaining a row must rebuild that row's page. Same rule as findings.
        ins = model.sources(s) + [findings, model.OPERATORS]
        up = chains[s]["lineage"].get("upstream")
        # a chain inheriting from a stack node renders that node's entries too
        if up in chains and is_stack(chains[up]):
            ins.append(ROOT / "chains" / up / "chain.yaml")
        sh = client(chains[s], "shared_with", None)
        if sh in chains:
            ins.append(ROOT / "chains" / sh / "chain.yaml")
        pages.append(Page(f"chains/{s}.html", ins,
                          (lambda slug: lambda ch: page_chain(ch, slug))(s)))
    return pages


def sha(path):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return "missing"


def renderer_version():
    """Changing the renderer invalidates every page, which is the correct
    semantics: the HTML is a function of the data AND the code that shapes it."""
    h = hashlib.sha256()
    for f in sorted([pathlib.Path(__file__), pathlib.Path(__file__).parent / "model.py",
                     ASSETS / "site.css", ASSETS / "site.js"]):
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def build(targets=None, force_all=False, check=False, quiet=False):
    chains = model.load()
    pages = registry(chains)
    ver = renderer_version()
    old = {}
    if MANIFEST.exists() and not force_all:
        try:
            old = json.loads(MANIFEST.read_text())
        except json.JSONDecodeError:
            old = {}
    if old.get("renderer") != ver:
        if old and not quiet:
            print("renderer changed — rebuilding every page")
        old = {"renderer": ver, "pages": {}}
    old.setdefault("pages", {})

    def stale(p):
        if force_all: return True
        rec = old["pages"].get(p.path)
        if not rec: return True
        if not (OUT / p.path).exists(): return True
        return rec.get("inputs") != {str(i.relative_to(ROOT)): sha(i) for i in p.inputs}

    if targets:
        want = set()
        for t in targets:
            hits = [p for p in pages if p.path == t or p.path == f"chains/{t}.html"
                    or p.path == f"axes/{t}.html" or p.path.startswith(t)]
            if not hits:
                sys.exit(f"error: no page matches {t!r} (try --list)")
            want |= {p.path for p in hits}
        todo = [p for p in pages if p.path in want]
    else:
        todo = [p for p in pages if stale(p)]

    if check:
        if todo:
            print(f"website/ is STALE — {len(todo)} page(s) would change:")
            for p in todo: print(f"  {p.path}")
            return 1
        print(f"website/ is up to date ({len(pages)} pages)")
        return 0

    OUT.mkdir(exist_ok=True)
    (OUT / "assets").mkdir(exist_ok=True)
    for a in ASSETS.iterdir():
        if a.is_file(): shutil.copy2(a, OUT / "assets" / a.name)
    (OUT / ".nojekyll").write_text("")   # GitHub Pages: serve paths beginning with _

    for p in todo:
        dst = OUT / p.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(p.fn(chains))
        old["pages"][p.path] = {"inputs": {str(i.relative_to(ROOT)): sha(i) for i in p.inputs}}
        if not quiet: print(f"  {p.path}")

    # drop manifest entries for pages that no longer exist
    live = {p.path for p in pages}
    for gone in [k for k in old["pages"] if k not in live]:
        del old["pages"][gone]
        f = OUT / gone
        if f.exists(): f.unlink()
        if not quiet: print(f"  removed {gone}")

    old["renderer"] = ver
    MANIFEST.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n")
    if not quiet:
        skipped = len(pages) - len(todo)
        print(f"{len(todo)} page(s) written, {skipped} unchanged  →  website/")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Render website/ from chains/*/chain.yaml and findings.yaml.",
        epilog="With no arguments, rebuilds only the pages whose inputs changed. See SITE.md.")
    ap.add_argument("target", nargs="*",
                    help="page path, chain slug, axis name, or directory prefix "
                         "(e.g. base, axes/precompiles.html, chains/). Rebuilds those "
                         "regardless of whether their inputs changed.")
    ap.add_argument("--all", action="store_true", help="rebuild every page from scratch")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any page is out of date; write nothing")
    ap.add_argument("--list", action="store_true",
                    help="list every page with the inputs it reads, and exit")
    ap.add_argument("--clean", action="store_true", help="delete website/ before building")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()

    if a.list:
        chains = model.load()
        for p in registry(chains):
            print(p.path)
            for i in p.inputs:
                print(f"    {i.relative_to(ROOT)}")
        return 0
    if a.clean and OUT.exists():
        shutil.rmtree(OUT)
    return build(targets=a.target or None, force_all=a.all or a.clean,
                 check=a.check, quiet=a.quiet)


if __name__ == "__main__":
    sys.exit(main())
