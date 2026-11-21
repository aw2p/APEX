#!/usr/bin/env bash
# Push ONLY the README + preview GIF + repo description (no code release flow).
#
#   export GH_TOKEN="ghp_…"        # classic PAT, scope: repo (or use gh auth login)
#   tools/push-readme.sh
#
# Does:
#   1. commits README.md / docs/assets if they changed, pushes to origin
#   2. updates the GitHub repo description
#   3. reminds you to upload the social preview (web-only feature)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."

REPO_NAME="APEX"
DESCRIPTION="APEX — Adaptive Peripheral Effect Xecutor · Apex Pro Mini Wireless lighting suite for Linux"

fail() { echo "✗ $*" >&2; exit 1; }

command -v gh >/dev/null || fail "gh CLI not installed (sudo pacman -S github-cli)"
[ -n "${GH_TOKEN:-}" ] || gh auth status >/dev/null 2>&1 || \
  fail "no credentials: export GH_TOKEN='ghp_…' or run 'gh auth login'"

LOGIN="$(gh api user -q .login 2>/dev/null)" || fail "token invalid / gh not authenticated"
echo "✓ authenticated as $LOGIN"

# repo: use the configured origin, else aw2p/APEX
if git remote get-url origin >/dev/null 2>&1; then
  ORIGIN="$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')"
else
  ORIGIN="$LOGIN/$REPO_NAME"
fi
echo "✓ target repo: $ORIGIN"

# 1. commit + push readme/gif if changed
if ! git diff --quiet HEAD -- README.md docs/ 2>/dev/null || \
   [ -n "$(git ls-files --others --exclude-standard README.md docs/)" ]; then
  git add README.md docs/
  git commit -m "docs: README + preview assets"
  echo "✓ committed docs"
fi
if git remote get-url origin >/dev/null 2>&1; then
  git push
  echo "✓ pushed"
fi

# 2. repo description
gh repo edit "$ORIGIN" --description "$DESCRIPTION" && \
  echo "✓ description updated"

# 3. social preview (no API for this — one manual step)
echo
echo "last step (manual, 10 seconds):"
echo "  https://github.com/$ORIGIN/settings#social-preview → upload docs/assets/logo.png"
