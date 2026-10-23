#!/usr/bin/env python3
"""
Runs the whole data pipeline in order: scrape the latest data, rebuild the
derived tables and metrics, then export the tables the app reads to
data/app.db. Stops at the first step that fails.

Usage:
    python run_pipeline.py                  # update the current season (what the daily job runs)
    python run_pipeline.py --season 2026    # refresh a specific season (end year)
    python run_pipeline.py --all            # rebuild every season from scratch (slow)
    python run_pipeline.py --skip-collect   # no scraping, just recompute from the existing database
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Steps that download data. (script, accepts --all/--season)
COLLECT_STEPS = [
    ("pipeline/collect/brdatascraping.py", True),
    ("pipeline/collect/nbadatascraping.py", True),  # also rebuilds the BR-to-NBA ID mapping
    ("pipeline/transform/league_averages.py", False),  # one Basketball-Reference page, all seasons
]
# Steps that recompute tables from what's already in the database.
BUILD_STEPS = [
    "pipeline/transform/league_average_nba.py",
    "pipeline/transform/derived_stats.py",
    "pipeline/transform/scoring_profile.py",
    "pipeline/transform/team_colors.py",
    "pipeline/metrics/scoring_plus.py",
    "pipeline/metrics/team_scoring_plus.py",
    "pipeline/transform/player_profile.py",
    "pipeline/transform/team_profile.py",
    "pipeline/transform/career_averages.py",
    "pipeline/export_app_db.py",
]


def run(script: str, extra_args: list[str]) -> None:
    print(f"\n=== {script} {' '.join(extra_args)}".rstrip(), flush=True)
    start = time.time()
    result = subprocess.run([sys.executable, script, *extra_args], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        sys.exit(f"\nPipeline stopped: {script} failed (exit code {result.returncode}).")
    print(f"--- done in {time.time() - start:.0f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Rebuild every season from scratch.")
    group.add_argument("--season", type=int, action="append", metavar="END_YEAR",
                       help="Refresh a specific season, e.g. 2027 for 2026-27. Repeatable.")
    group.add_argument("--skip-collect", action="store_true",
                       help="Skip scraping and recompute everything from the existing database.")
    args = parser.parse_args()

    scraper_args = ["--all"] if args.all else [a for y in (args.season or []) for a in ("--season", str(y))]

    if not args.skip_collect:
        for script, takes_season_args in COLLECT_STEPS:
            run(script, scraper_args if takes_season_args else [])
    for script in BUILD_STEPS:
        run(script, [])
    print("\nPipeline finished.")


if __name__ == "__main__":
    main()
