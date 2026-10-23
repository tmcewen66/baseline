#!/bin/bash
# One-time setup for the daily data update on this Mac. Safe to re-run.
#
#   bash scripts/setup_mac_daily_job.sh
#
# Creates a separate clone of the repo at ~/baseline-pipeline that only the
# daily job uses, so it never touches your working copy. It lives outside
# Desktop because macOS blocks background jobs from reading Desktop, and
# Desktop is synced with iCloud.

set -euo pipefail

REPO_URL="https://github.com/tmcewen66/baseline.git"
REPO="tmcewen66/baseline"
JOB_DIR="$HOME/baseline-pipeline"
CONDA="/opt/anaconda3/bin/conda"
LABEL="com.tmcewen66.baseline-daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUN_HOUR=7   # local time, after the previous night's games are final

step() { printf "\n==> %s\n" "$1"; }

step "Cloning the repo to $JOB_DIR"
if [[ -d "$JOB_DIR/.git" ]]; then
  git -C "$JOB_DIR" pull --rebase --quiet
  echo "Already cloned, pulled latest."
else
  git clone --quiet "$REPO_URL" "$JOB_DIR"
fi

step "Creating the job's Python 3.14 environment (with the GitHub CLI)"
if [[ ! -x "$JOB_DIR/.venv/bin/python" ]]; then
  rm -rf "$JOB_DIR/.venv"  # clear out any half-created env from a failed attempt
  # --solver classic: works even when Anaconda's libmamba solver plugin is broken
  "$CONDA" create --yes --quiet --solver classic --prefix "$JOB_DIR/.venv" -c conda-forge python=3.14 gh
fi
"$JOB_DIR/.venv/bin/python" -m pip install --quiet -r "$JOB_DIR/requirements.txt"
shasum "$JOB_DIR/requirements.txt" | cut -d' ' -f1 > "$JOB_DIR/.venv/.requirements-hash"
GH="$JOB_DIR/.venv/bin/gh"

step "Signing in to GitHub (needed to push app.db and update the release)"
if "$GH" auth status --hostname github.com > /dev/null 2>&1; then
  echo "Already signed in."
else
  "$GH" auth login --hostname github.com --git-protocol https --web
fi
# Use gh for this clone's git credentials so pushes work from the background job.
git -C "$JOB_DIR" config --local --replace-all credential.helper ""
git -C "$JOB_DIR" config --local --add credential.helper "!'$GH' auth git-credential"
(cd "$JOB_DIR" && "$GH" repo set-default "$REPO" > /dev/null)

step "Installing the daily schedule ($RUN_HOUR:00 every day)"
mkdir -p "$HOME/Library/LaunchAgents" "$JOB_DIR/logs"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$JOB_DIR/scripts/daily_update_mac.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$RUN_HOUR</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StandardOutPath</key>
  <string>$JOB_DIR/logs/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$JOB_DIR/logs/launchd.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2> /dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

step "Done"
cat <<MSG
The update will run every day at $RUN_HOUR:00. If the Mac is asleep then, it runs
as soon as it wakes. It does nothing from May through September.

Test it now with:
  FORCE=1 $JOB_DIR/scripts/daily_update_mac.sh

Logs:      $JOB_DIR/logs/
Turn off:  launchctl bootout gui/\$(id -u)/$LABEL
MSG
