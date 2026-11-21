#!/usr/bin/env bash
# APEX publish helper — commit + (first time) create the GitHub repo + push.
#
# Usage:
#   export GH_TOKEN="ghp_…"            # classic PAT, scope: repo
#   tools/publish.sh "commit message"  # default message: "update"
#
# First run  : creates the public repo <your-login>/APEX and pushes everything.
# Later runs : plain commit + push (still needs GH_TOKEN exported, since we
#              deliberately store no credentials outside the environment).
#
# `--check` verifies prerequisites without touching anything.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

REPO_NAME="APEX"
MSG="${1:-update}"

fail() { echo "✗ $*" >&2; exit 1; }

# --- prerequisites ------------------------------------------------------
command -v gh >/dev/null || fail "gh CLI not installed (sudo pacman -S github-cli)"
[ -n "${GH_TOKEN:-}" ] || fail "GH_TOKEN is not set.  export GH_TOKEN='ghp_…' (scope: repo)"

LOGIN="$(gh api user -q .login 2>/dev/null)" || fail "GH_TOKEN invalid or gh api failed"
UID_="$(gh api user -q .id)"
echo "✓ authenticated as $LOGIN"

# --- one-time repo-local setup ------------------------------------------
if [ -z "$(git config user.name 2>/dev/null || true)" ]; then
  git config user.name "$LOGIN"
  git config user.email "${UID_}+${LOGIN}@users.noreply.github.com"
  echo "✓ git identity set to $LOGIN <${UID_}+${LOGIN}@users.noreply.github.com> (repo-local)"
fi
# route git's https pushes through gh (uses GH_TOKEN from the env, stores nothing)
git config credential.https://github.com.helper '!gh auth git-credential' || true

if [ "${1:-}" = "--check" ]; then
  echo "✓ everything ready: $LOGIN can publish to github.com/$LOGIN/$REPO_NAME"
  exit 0
fi

# --- commit -------------------------------------------------------------
if ! git diff --quiet HEAD 2>/dev/null || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  git add -A
  git commit -m "$MSG"
  echo "✓ committed: $MSG"
else
  echo "• nothing new to commit"
fi

# --- create-once, push-always -------------------------------------------
if git remote get-url origin >/dev/null 2>&1; then
  git push
  echo "✓ pushed to $(git remote get-url origin)"
else
  gh repo create "$REPO_NAME" --public --source=. --push \
    --description "APEX — Adaptive Peripheral Effect Xecutor · Apex Pro Mini Wireless lighting suite for Linux"
  echo "✓ created and pushed: https://github.com/$LOGIN/$REPO_NAME"
fi
