#!/bin/bash
# Daily data update, run on a Mac by launchd (see scripts/setup_mac_daily_job.sh).
#
# NBA.com blocks requests from cloud servers like GitHub Actions, so this runs
# from a home network instead. It works in its own clone of the repo:
#   1. pull the latest code
#   2. download the full database from the data-latest GitHub Release
#   3. run the pipeline for the current season
#   4. upload the updated database back to the release
#   5. commit and push data/app.db, which makes Streamlit Cloud redeploy
#
# Run it by hand with:  FORCE=1 ~/baseline-pipeline/scripts/daily_update_mac.sh
# (FORCE=1 also runs it in the offseason.)

set -euo pipefail

JOB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$JOB_DIR"
PY="$JOB_DIR/.venv/bin/python"
GH="$JOB_DIR/.venv/bin/gh"
RELEASE_TAG="data-latest"

mkdir -p logs
LOG="logs/$(date +%Y-%m-%d).log"
exec > >(tee -a "$LOG") 2>&1
find logs -name "*.log" -mtime +30 -delete 2>/dev/null || true

notify() {
  osascript -e "display notification \"$1\" with title \"Baseline data update\"" 2>/dev/null || true
}
trap 'notify "Failed. See $JOB_DIR/$LOG"; echo "FAILED at line $LINENO"' ERR

echo "=== $(date) ==="

# Regular season runs October through April. Skip the offseason unless forced.
month=$(date +%-m)
if [[ "${FORCE:-0}" != "1" && $month -ge 5 && $month -le 9 ]]; then
  echo "Offseason, nothing to update."
  exit 0
fi

git pull --rebase --quiet

# Reinstall dependencies only when requirements.txt changed.
req_hash=$(shasum requirements.txt | cut -d' ' -f1)
if [[ "$(cat .venv/.requirements-hash 2>/dev/null)" != "$req_hash" ]]; then
  echo "requirements.txt changed, reinstalling..."
  "$PY" -m pip install --quiet -r requirements.txt
  echo "$req_hash" > .venv/.requirements-hash
fi

"$GH" release download "$RELEASE_TAG" --pattern nba_stats.db --dir data --clobber

"$PY" run_pipeline.py

# Everything below runs only if the pipeline succeeded.
"$GH" release upload "$RELEASE_TAG" data/nba_stats.db --clobber

git add data/app.db
if git diff --cached --quiet; then
  echo "No new data today."
else
  git commit --quiet -m "Daily data update ($(date +%Y-%m-%d))"
  git push --quiet
  echo "Pushed updated app.db."
fi

echo "=== finished $(date) ==="
