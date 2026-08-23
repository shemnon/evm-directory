# 08 — Acceptance

Mechanical. No judgement. A change to the site is not finished until all of these pass.

## 1. Structural integrity

```bash
tools/.venv/bin/python - <<'PY'
import pathlib, re, collections, html.parser
OUT = pathlib.Path("website"); files = sorted(OUT.rglob("*.html"))
VOID = {"area","base","br","col","embed","hr","img","input","link","meta","source","track","wbr"}
class P(html.parser.HTMLParser):
    def __init__(s): super().__init__(convert_charrefs=True); s.stack=[]; s.err=[]
    def handle_starttag(s,t,a):
        if t not in VOID: s.stack.append(t)
    def handle_endtag(s,t):
        if t in VOID: return
        if not s.stack: s.err.append(f"stray </{t}>"); return
        if s.stack[-1]!=t:
            if t in s.stack:
                while s.stack and s.stack[-1]!=t: s.err.append(f"unclosed <{s.stack.pop()}>")
                s.stack.pop()
            else: s.err.append(f"stray </{t}>")
        else: s.stack.pop()
ids={f.resolve(): set(re.findall(r'\sid="([^"]+)"', f.read_text())) for f in files}
bad=links=anchors=dups=0
for f in files:
    txt=f.read_text()
    p=P(); p.feed(txt); p.close()
    if p.err or p.stack: bad+=1; print("MALFORMED", f.relative_to(OUT), (p.err+[f"unclosed <{x}>" for x in p.stack])[:3])
    for href in re.findall(r'(?:href|src)="([^"]+)"', txt):
        if href.startswith(("http","mailto:","data:")): continue
        path,_,frag = href.partition("#")
        tgt=(f.parent/path).resolve() if path else f.resolve()
        if path and not tgt.exists(): links+=1; print("LINK", f.relative_to(OUT), href)
        elif frag and tgt in ids and frag not in ids[tgt]: anchors+=1; print("ANCHOR", f.relative_to(OUT), href)
    d=[k for k,v in collections.Counter(re.findall(r'\sid="([^"]+)"', txt)).items() if v>1]
    if d: dups+=1; print("DUP", f.relative_to(OUT), d[:4])
print(f"\n{len(files)} pages · malformed={bad} broken_links={links} "
      f"dangling_anchors={anchors} dup_id_pages={dups}")
PY
```

**All four counters must be zero.** Dangling anchors are the one that recurs: a grid cell
linking to a chain that *inherits* an entry rather than declaring it. See
[03-grids.md](03-grids.md#cell-links).

## 2. The build is honest

```bash
tools/.venv/bin/python tools/site.py --check     # must report up to date
tools/.venv/bin/python tools/verify.py           # must report clean
```

After a change to `model.py` or `generate.py`, confirm the Markdown tables did not move
unintentionally — snapshot them, regenerate, diff. A column-order change is acceptable
and visible; a changed *cell* is a bug.

## 3. Structure

- Every page's first `<h2>` is its grid, named for the axis
  ([00-brief.md](00-brief.md), [02-pages.md](02-pages.md)).
- No summary tiles above any grid.
- Chains are columns on every axis grid.

```bash
for f in website/axes/*.html website/index.html; do
  echo "$(basename $f): $(grep -o '<h2 id="[^"]*"' $f | head -1)"
done
```

## 4. Behaviour

With a browser on `python3 -m http.server -d website`:

- Chain picker narrows every grid on the page and the selection survives navigating to
  another axis.
- **Hide rows where every chain agrees** respects the current selection — with only
  Ethereum and Tron visible the opcode grid shows 19 rows; with all chains, 28.
- A grid cell lands on the right anchor on the right chain page, not under the sticky
  header.
- The page renders correctly in both colour schemes and does not scroll sideways at
  430px.

## 5. Register

```bash
grep -ril "principal findings\|collision course\|the interesting cell\|not an anecdote" website/
```

Hits inside rendered `SUMMARY.md` or `chain.yaml` notes are the author's own prose and are
fine ([07-voice.md](07-voice.md)). Hits in the site's own framing are not.

## 6. Portability

Open `website/index.html` over `file://`. Navigation, assets and grids must work with no
server and no network.
