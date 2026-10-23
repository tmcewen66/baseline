#!/usr/bin/env python3
"""
Copies the tables the Streamlit app reads from the full nba_stats.db into a
small data/app.db. The app (and the deployed site) only ever opens app.db, so
the full database with every raw scraped table doesn't need to live in git.
"""

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from pipeline.common import APP_DB_PATH, DB_PATH  # noqa: E402

APP_TABLES = ["player_profile", "team_profile", "career_averages", "team_colors"]


# (raw table the season comes from, app table it must reach)
_SEASON_CHECKS = [("basic_stats", "player_profile"), ("team_advanced_stats", "team_profile")]


def check_seasons(src: str = DB_PATH) -> None:
    """
    Every season in the raw scraped tables should make it into the app tables.
    A season can silently drop out if a join input is missing (for example the
    league-average row for a brand-new season), so stop here instead of
    publishing data with a season missing.
    """
    with sqlite3.connect(src) as con:
        for raw, app in _SEASON_CHECKS:
            raw_seasons = {r[0] for r in con.execute(f"SELECT DISTINCT season_end_year FROM {raw}")}
            app_seasons = {r[0] for r in con.execute(f"SELECT DISTINCT season_end_year FROM {app}")}
            missing = sorted(raw_seasons - app_seasons)
            if missing:
                raise RuntimeError(
                    f"Seasons {missing} are in {raw} but missing from {app}. "
                    "Check that every input table (e.g. league_averages) has rows for them."
                )


def export(src: str = DB_PATH, dest: str = APP_DB_PATH) -> None:
    check_seasons(src)
    tmp = dest + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)

    with sqlite3.connect(tmp) as out:
        out.execute("ATTACH DATABASE ? AS src", (src,))
        for table in APP_TABLES:
            out.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{table}")
            rows = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {rows} rows")
        out.commit()
        out.execute("DETACH DATABASE src")
    os.replace(tmp, dest)  # swap in only once the export fully succeeded
    print(f"Wrote {dest} ({os.path.getsize(dest) / 1e6:.1f} MB)")


if __name__ == "__main__":
    export()
