#!/usr/bin/env bash
set -euo pipefail

tag=$1
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
gh release view "$tag" --json isDraft,isPrerelease --jq '(.isDraft|not) and .isPrerelease' | grep -qx true
gh release download "$tag" --pattern '*.zip' --dir "$tmp"
for name in vector-prime vector-prime-guidance; do
  cmp "dist/$name.zip" "$tmp/$name.zip"
done

previous=$(git ls-remote origin refs/tags/alpha | cut -f1)
git merge-base --is-ancestor "$previous" "$tag"
git push --force-with-lease="refs/tags/alpha:$previous" origin "$tag:refs/tags/alpha"
test "$(git ls-remote origin refs/tags/alpha | cut -f1)" = "$(git rev-parse "$tag^{commit}")"
