#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Search the pinned clones for code that changes balances without a transaction.

A fork can carry a list of addresses and amounts and write them straight into state at
the transition block (findings.yaml, `client-applied-balance-moves`). Nothing on chain
records it: no transaction, log or trace frame. Release notes need not mention it either;
Core's Fermi moved 68M CORE in a release whose changelog is empty. This search is how
those were found, and it is meant to be rerun on every fork pass.

It reports two kinds of hit, in every client language here (Go, Rust, Java/Kotlin, C#,
C++, TypeScript):

  WRITE      a balance mutation within WINDOW lines of a hard-coded address
  IRREGULAR  a DAO-style irregular-state hook, by name

Addresses are matched the way each client spells them: 20-byte hex, plus base58 `T…`
and `41`-prefixed hex for Tron. Substrate runtimes get a third kind, UPGRADE: a balance
call inside an `OnRuntimeUpgrade` file.

Most hits are ordinary: fee and reward paths, inherited DAO refunds gated on a block a
chain never sets, test helpers. tools/balancescan-known.yaml records each reviewed one
with a reason, and only hits no rule covers are printed. Exit 1 if any are. A clean run
is not proof of absence: a list held in config, or an address built at runtime, passes.

Reads the clones only and makes no network calls. Run after `tools/clone.sh`.
"""
import argparse, fnmatch, pathlib, re, subprocess, sys, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
KNOWN = ROOT / "tools" / "balancescan-known.yaml"
WINDOW = 20

EXT = {".go": "go", ".rs": "rust", ".java": "java", ".kt": "java", ".cs": "cs",
       ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".h": "cpp", ".ts": "ts"}
MUT = {
    "go":   r"\b(AddBalance|SubBalance|SetBalance)\s*\(",
    "rust": r"\b(increment_balance|decrement_balance|set_balance|add_balance|sub_balance|"
            r"balance_increments?|transfer_balance|increment_balances|drain_balances)\b"
            r"|\.info\.balance\s*[-+]?=|\.balance\s*=\s",
    "java": r"\b(setBalance|incrementBalance|decrementBalance|addBalance|subBalance|"
            r"adjustBalance|addToBalance|subtractFromBalance|transferBalance)\s*\(",
    "cs":   r"\b(AddToBalance|SubtractFromBalance|SetBalance|IncrementBalance|"
            r"AddToBalanceAndCreateIfNotExists)\s*\(",
    "cpp":  r"\b(add_to_balance|subtract_from_balance|set_balance|add_balance|sub_balance|"
            r"setBalance|addBalance|subBalance|AddBalance|SubBalance|SetBalance)\s*\(",
    "ts":   r"\b(setBalance|addBalance)\s*\(",
}
ADDR = re.compile(r"0x[0-9a-fA-F]{40}\b|\"[0-9a-fA-F]{40}\"|\b[0-9a-fA-F]{40}L?\b"
                  r"|\"T[1-9A-HJ-NP-Za-km-z]{33}\"|\"41[0-9a-fA-F]{40}\"")
# The functions that APPLY an irregular change, not the config fields that schedule one:
# every geth fork carries DAOForkBlock, and naming it is not running it.
IRREG = re.compile(r"\bApply\w*(HardFork|Adjustment|Fix)\w*\s*\(|\bdrain_balances\b|"
                   r"\bIrregularStateChange::new\b|\bnew DaoBlockProcessor\b|"
                   r"\bApplyDaoTransition\s*\(")
UPGRADE_FILE = re.compile(r"impl.*OnRuntimeUpgrade|fn on_runtime_upgrade")
UPGRADE_OP = re.compile(r"deposit_creating|deposit_into_existing|mint_into|burn_from|"
                        r"make_free_balance_be|transfer_all|Currency::transfer|\bslash\(")
SKIP = re.compile(r"(?i)(^|/)(tests?|testing|test_utils|testutil|mocks?|benches?|bench|"
                  r"fixtures?|examples?|testdata|e2e|integration[-_]?tests?|jmh|fuzz)(/|$)"
                  r"|_test\.(go|cpp|cc|h|hpp)$|(^|/)tests?\.rs$|Tests?[A-Za-z]*\.(java|kt|cs)$|\.Tests?(/|\.)"
                  r"|(spec|test)\.ts$")
COMMENT = ("//", "*", "#", "/*", "///")


def scan_repo(slug, repo):
    files = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True,
                           text=True).stdout.split("\n")
    for rel in filter(None, files):
        lang = EXT.get(pathlib.PurePath(rel).suffix)
        if not lang or SKIP.search(rel): continue
        try: text = (repo / rel).read_text(errors="replace")
        except OSError: continue
        lines = text.splitlines()
        if len(lines) > 30000: continue
        if lang == "rust":                  # an in-file test module ends the production code
            for i, l in enumerate(lines):
                if l.strip() == "#[cfg(test)]": lines = lines[:i]; break
        mut, addrs = re.compile(MUT[lang]), [i for i, l in enumerate(lines) if ADDR.search(l)]
        upgrade = lang == "rust" and UPGRADE_FILE.search(text)
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith(COMMENT): continue
            kind = None
            if IRREG.search(l): kind = "IRREGULAR"
            elif upgrade and UPGRADE_OP.search(l): kind = "UPGRADE"
            elif mut.search(l) and any(abs(a - i) <= WINDOW for a in addrs): kind = "WRITE"
            if kind:
                yield {"row": slug, "repo": repo.name, "file": rel, "line": i + 1,
                       "kind": kind, "text": s[:160]}


def covered(hit, rules):
    for r in rules:
        if not fnmatch.fnmatch(hit["row"], r.get("row", "*")): continue
        if not fnmatch.fnmatch(hit["repo"], r.get("repo", "*")): continue
        if not fnmatch.fnmatch(hit["file"], r.get("file", "*")): continue
        if "kind" in r and r["kind"] != hit["kind"]: continue
        if "text" in r and not re.search(r["text"], hit["text"]): continue
        return r
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Search the pinned clones for client code that moves balances "
                    "without a transaction.",
        epilog="Only hits that no rule in tools/balancescan-known.yaml covers are printed. "
               "See findings.yaml, client-applied-balance-moves.")
    ap.add_argument("slugs", nargs="*", help="rows to scan (default: every cloned row)")
    ap.add_argument("--all", action="store_true", help="also print hits a known rule covers")
    a = ap.parse_args()

    rules = (yaml.safe_load(KNOWN.read_text()) or {}).get("rules", [])
    for r in rules:
        if not r.get("reason"): sys.exit(f"{KNOWN.name}: every rule needs a reason: {r}")
    slugs = a.slugs or sorted(p.name for p in (ROOT / "chains").iterdir() if (p / "repos").is_dir())
    new, known, used, scanned = [], 0, set(), 0
    for slug in slugs:
        repos = sorted(p for p in (ROOT / "chains" / slug / "repos").glob("*") if (p / ".git").exists())
        if not repos and a.slugs: print(f"{slug}: no clones; run tools/clone.sh {slug}")
        for repo in repos:
            scanned += 1
            for h in scan_repo(slug, repo):
                r = covered(h, rules)
                if r is None: new.append(h)
                else:
                    known += 1; used.add(id(r))
                    if a.all: print(f"  known  {h['row']}/{h['repo']}/{h['file']}:{h['line']}  ({r['reason'][:60]})")
    for h in new:
        print(f"  {h['kind']:9s} {h['row']}/{h['repo']}/{h['file']}:{h['line']}\n            {h['text']}")
    if not a.slugs:
        for r in rules:
            if id(r) not in used: print(f"  stale rule (matches nothing now): {r}")
    print(f"{scanned} clone(s), {known} known hit(s), {len(new)} unreviewed")
    if new:
        print("Read each one. A real balance move belongs in findings.yaml and the row; "
              "an ordinary one gets a rule with a reason in tools/balancescan-known.yaml.")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
