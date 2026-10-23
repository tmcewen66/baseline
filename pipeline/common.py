"""
Shared helpers for the data pipeline: project paths, which NBA season is
current, and replacing one season's rows in a table without touching the rest.

Seasons are identified by season_end_year (2027 = the 2026-27 season).
"""

import argparse
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(PROJECT_ROOT / "data" / "nba_stats.db")
APP_DB_PATH = str(PROJECT_ROOT / "data" / "app.db")

FIRST_SEASON_END_YEAR = 2001  # 2000-01 season

# Minimum games played to qualify for leaderboards, for players and teams.
# Full-season thresholds already imply far more games than this, so it only
# matters early in a season, when the prorated thresholds are tiny.
MIN_GAMES_QUALIFIED = 20

# Regular season runs from October through mid-April. Playoff games are not
# part of the regular-season stats, so May through September counts as offseason.
_IN_SEASON_MONTHS = {10, 11, 12, 1, 2, 3, 4}


def current_season_end_year(today: date | None = None) -> int:
    """The season that is in progress, or the one that most recently ended."""
    today = today or date.today()
    return today.year + 1 if today.month >= 10 else today.year


def in_progress_season(today: date | None = None) -> int | None:
    """season_end_year of the regular season currently being played, else None."""
    today = today or date.today()
    return current_season_end_year(today) if today.month in _IN_SEASON_MONTHS else None


def all_seasons(today: date | None = None) -> list[int]:
    return list(range(FIRST_SEASON_END_YEAR, current_season_end_year(today) + 1))


def season_label(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def parse_season_args(description: str) -> list[int] | None:
    """
    Command-line options shared by the scrapers.

    Returns a list of season_end_years to update, or None for a full rebuild
    (every season from 2000-01 on, replacing the tables entirely).
    """
    parser = argparse.ArgumentParser(description=description)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true",
        help="Rebuild every season from 2000-01 on (slow, replaces the tables).",
    )
    group.add_argument(
        "--season", type=int, action="append", metavar="END_YEAR",
        help="Update a specific season by end year, e.g. --season 2027 for 2026-27. Repeatable.",
    )
    args = parser.parse_args()
    if args.all:
        return None
    return sorted(set(args.season)) if args.season else [current_season_end_year()]


def replace_season_rows(con: sqlite3.Connection, table: str, df: pd.DataFrame, seasons: list[int]) -> None:
    """
    Delete the given seasons from `table` and insert `df` in their place,
    leaving every other season untouched. Columns in `df` that the table
    doesn't have yet are added; table columns missing from `df` are left NULL.
    """
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not exists:
        df.to_sql(table, con, index=False)
        return

    existing_cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    for col in df.columns:
        if col not in existing_cols:
            con.execute(f'ALTER TABLE {table} ADD COLUMN "{col}"')

    placeholders = ", ".join("?" for _ in seasons)
    con.execute(f"DELETE FROM {table} WHERE season_end_year IN ({placeholders})", seasons)
    df.to_sql(table, con, if_exists="append", index=False)
