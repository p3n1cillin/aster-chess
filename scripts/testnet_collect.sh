#!/bin/bash
# Fetch every testnet/<label>-* worker branch and copy its result logs into
# testnet/collected/<label>/ (usage: testnet_collect.sh LABEL).
set -eu
cd "$(dirname "$0")/.."
label=$1
out=testnet/collected/$label
mkdir -p "$out"
for ref in $(git ls-remote origin "refs/heads/testnet/$label-*" | awk '{print $2}'); do
  branch=${ref#refs/heads/}
  git fetch -q origin "$branch" || continue
  for f in $(git ls-tree -r --name-only FETCH_HEAD "testnet/results/$label/" 2>/dev/null | grep '\.log$'); do
    git show "FETCH_HEAD:$f" > "$out/$(basename "$f")"
  done
done
ls "$out"
