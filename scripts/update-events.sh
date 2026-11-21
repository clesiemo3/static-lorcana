#!/bin/bash
# Weekly: research Lorcana events with Claude Code, update the calendar's
# events.json, check the site still builds, then commit and push so GitHub
# Pages deploys it. Set NO_PUSH=1 to commit without pushing.
set -euo pipefail

# launchd starts jobs with a bare PATH; add where uv and claude usually live.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

cd "$(dirname "$0")/.."
echo "=== $(date '+%Y-%m-%d %H:%M:%S') events calendar update ==="

git pull --rebase --autostash --quiet

SUMMARY="$(mktemp)"
trap 'rm -f "$SUMMARY"' EXIT
uv run python3 events_calendar/update.py | tee "$SUMMARY"

# Make sure the whole site (not just the calendar) still builds before publishing.
uv run python3 scripts/build.py >/dev/null

git add events_calendar/events.json
if git diff --cached --quiet; then
  echo "Nothing changed."
  exit 0
fi
{
  echo "Update events calendar for $(date +%F)"
  echo
  grep '^- ' "$SUMMARY" || echo "- Refreshed the last-checked date."
} | git commit --quiet -F -
if [ "${NO_PUSH:-}" = "1" ]; then
  echo "Committed locally; NO_PUSH=1 so not pushing."
else
  git push --quiet
  echo "Pushed. GitHub Pages will deploy the updated calendar."
fi
