#!/usr/bin/env bash
# Re-fetch the evidence. Clones are gitignored; chain.yaml holds the pins.
# Usage: tools/clone.sh [slug ...]   (default: all)
set -uo pipefail
cd "$(dirname "$0")/.."
PY=tools/.venv/bin/python
[ -x "$PY" ] || PY=python3

status=0
while read -r slug repo version commit; do
  dest="chains/$slug/repos/$(basename "$repo")"
  if [ -d "$dest/.git" ]; then
    have=$(git -C "$dest" rev-parse HEAD)
    if [ "$have" = "$commit" ]; then printf '  ok    %-18s %s\n' "$slug" "$version"; continue; fi
    printf '  STALE %-18s have %s want %s — re-cloning\n' "$slug" "${have:0:8}" "${commit:0:8}"
    rm -rf "$dest"
  fi
  mkdir -p "$(dirname "$dest")"
  if git clone --quiet --depth 1 --branch "$version" --single-branch "https://github.com/$repo" "$dest" 2>/dev/null; then
    have=$(git -C "$dest" rev-parse HEAD)
    if [ "$have" = "$commit" ]; then
      printf '  cloned %-17s %s\n' "$slug" "$version"
    else
      # a moved tag is exactly the failure mode that makes commit pins necessary
      printf '  WARN  %-18s tag %s now points at %s, pinned %s\n' "$slug" "$version" "${have:0:8}" "${commit:0:8}"
      status=1
    fi
  else
    printf '  FAIL  %-18s could not clone %s@%s\n' "$slug" "$repo" "$version"; status=1
  fi
done < <($PY - <<'EOF'
import pathlib, yaml
for f in sorted(pathlib.Path("chains").glob("*/chain.yaml")):
    y = yaml.safe_load(f.read_text())
    # `evidence: documented` rows have no client and nothing to clone
    c = y.get("client")
    if not c or y["chain"].get("evidence") == "documented":
        continue
    print(f.parent.name, c["repo"].replace("https://github.com/", ""), c["version"], c["commit"])
EOF
)
exit $status
