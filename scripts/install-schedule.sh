#!/bin/bash
# Install (or reinstall) the weekly events calendar update. Run with --uninstall to remove it.
set -euo pipefail

LABEL=com.static-lorcana.events.weekly
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$DEST"
  echo "Removed $LABEL."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$REPO/scripts/$LABEL.plist" > "$DEST"
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Installed $LABEL: Mondays at 9:30. Log: ~/Library/Logs/static-lorcana-events.log"
echo "Run it now with: launchctl kickstart gui/$(id -u)/$LABEL"
