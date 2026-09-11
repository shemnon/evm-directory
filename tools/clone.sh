#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Re-fetch the evidence. Clones are gitignored; chain.yaml holds the pins.
# Usage: tools/clone.sh [slug ...]   (default: all)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=tools/.venv/bin/python
[ -x "$PY" ] || PY=python3

plan=$(mktemp)
trap 'rm -f "$plan"' EXIT

# The plan is derived from chain.yaml, so a new row needs no edit here: adding the
# file adds the clone. Tab-separated: slug, name, repo, ref, commit, label.
#
# `ref` is the sentinel "-" rather than an empty field, and the prose `label` is
# LAST, because tab is IFS *whitespace*: bash collapses a run of it, so an empty
# middle field silently shifts every column after it. That shift is what deleted
# three clones the first time this ran.
#
# `ref` is empty when there is no cloneable tag. That is not an edge case: several
# companions pin a BRANCH or a submodule and say so in prose — "main (UNTAGGED)",
# "moonbeam-polkadot-stable2512 (branch)", "submodule @ v1.14.1 (git describe: ...)".
# Handing any of those to `git clone --branch` either fails or, worse, succeeds and
# lands on the branch HEAD instead of the pinned commit. Anything that is not a
# single bare token is therefore fetched BY COMMIT, and `label` keeps the prose for
# the human-readable output.
SLUGS="$*" $PY - >"$plan" <<'EOF'
import os, pathlib, yaml

only = set(os.environ.get("SLUGS", "").split())

def strip(url):
    return url.replace("https://github.com/", "").rstrip("/")


def emit(slug, name, repo, version, commit):
    label = version or "(commit pin)"
    ref = version if version and " " not in version.strip() else "-"
    print("\t".join([slug, name, repo, ref, commit, label]))

for f in sorted(pathlib.Path("chains").glob("*/chain.yaml")):
    slug = f.parent.name
    if only and slug not in only:
        continue
    y = yaml.safe_load(f.read_text())
    # `evidence: documented` rows have no client and nothing to clone
    c = y.get("client")
    if not c or y["chain"].get("evidence") == "documented":
        continue
    # `client.shared_with` says outright that this row has no clone of its own: its
    # evidence is another row's, and verify.py already follows the pointer. Cloning
    # a second copy of the same tree costs hundreds of megabytes and proves nothing.
    if not c.get("shared_with"):
        repo = strip(c["repo"])
        emit(slug, repo.split("/")[-1], repo, c.get("version"), c["commit"])
    # Companions supply facts the main client does not contain. They were NOT cloned
    # by this script before, so they had to be fetched by hand — which is exactly the
    # unpinned, unreproducible evidence the method exists to prevent.
    for k in c.get("companion_repos") or []:
        emit(slug, k["name"], strip(k["repo"]), k.get("version"), k["commit"])
EOF

status=0
while IFS=$'\t' read -r slug name repo ref commit label; do
  [ -n "$slug" ] || continue
  dest="chains/$slug/repos/$name"
  name_label="$slug/$name"
  if [ -d "$dest/.git" ]; then
    have=$(git -C "$dest" rev-parse HEAD)
    if [ "$have" = "$commit" ]; then printf '  ok    %-28s %s\n' "$name_label" "$label"; continue; fi
    printf '  STALE %-28s have %s want %s — re-cloning\n' "$name_label" "${have:0:8}" "${commit:0:8}"
    rm -rf "$dest"
  fi
  mkdir -p "$(dirname "$dest")"
  if [ "$ref" = "-" ]; then
    # Pinned by commit with no tag (superchain-registry; the ethermint go.mod
    # replace target is a pseudo-version). There is no ref to shallow-clone, so
    # fetch the objects and check the commit out directly.
    if git clone --quiet --filter=blob:none --no-checkout "https://github.com/$repo" "$dest" 2>/dev/null &&
       git -C "$dest" checkout --quiet "$commit" 2>/dev/null; then
      printf '  cloned %-27s %s\n' "$name_label" "$label"
    else
      printf '  FAIL  %-28s could not fetch %s@%s\n' "$name_label" "$repo" "${commit:0:8}"
      status=1
    fi
    continue
  fi
  if git clone --quiet --depth 1 --branch "$ref" --single-branch "https://github.com/$repo" "$dest" 2>/dev/null; then
    have=$(git -C "$dest" rev-parse HEAD)
    if [ "$have" = "$commit" ]; then
      printf '  cloned %-27s %s\n' "$name_label" "$label"
    else
      # a moved tag is exactly the failure mode that makes commit pins necessary
      printf '  WARN  %-28s tag %s now points at %s, pinned %s\n' "$name_label" "$ref" "${have:0:8}" "${commit:0:8}"
      status=1
    fi
  else
    printf '  FAIL  %-28s could not clone %s@%s\n' "$name_label" "$repo" "$ref"
    status=1
  fi
done <"$plan"
exit $status
