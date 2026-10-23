#!/usr/bin/env python3
"""
Fetches basic and advanced NBA player season totals from Basketball-Reference.

By default only the current season is fetched, and only its rows are replaced
in basic_stats/advanced_stats. Use --all to rebuild every season from 2000-01
on, or --season END_YEAR to refresh specific seasons.

Results are stored in two dicts keyed by season_end_year:
    basic_dfs[2024]    -> DataFrame for the 2023-24 season, indexed by slug
    advanced_dfs[2024] -> DataFrame for the 2023-24 season, indexed by slug
"""

import sqlite3
import sys
import time
import pandas as pd
from basketball_reference_web_scraper import client
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from pipeline.common import all_seasons, parse_season_args, replace_season_rows, season_label  # noqa: E402

REQUEST_DELAY_SECONDS = 3
DB_PATH = str(PROJECT_ROOT / "data" / "nba_stats.db")

BASIC_NUMERIC_COLS = [
    "games_played", "games_started", "minutes_played",
    "made_field_goals", "attempted_field_goals",
    "made_three_point_field_goals", "attempted_three_point_field_goals",
    "made_free_throws", "attempted_free_throws",
    "offensive_rebounds", "defensive_rebounds",
    "assists", "steals", "blocks", "turnovers", "personal_fouls", "points",
]


def _aggregate_basic(df: pd.DataFrame) -> pd.DataFrame:
    """
    For traded players, basic stats have one row per team with no combined row.
    Sum the numeric columns, take first value for metadata, and build a 'teams'
    column listing every team played for that season (e.g. "DALLAS MAVERICKS/MIAMI HEAT").
    """
    meta = df.groupby("slug")[["name", "positions", "age"]].first()
    teams = df.groupby("slug")["team"].apply(lambda x: "/".join(t.value for t in x))
    numeric = df.groupby("slug")[BASIC_NUMERIC_COLS].sum()
    return meta.join(teams).join(numeric)


def _dedupe_advanced(df: pd.DataFrame) -> pd.DataFrame:
    """
    For traded players, advanced stats include a combined row (is_combined_totals=True)
    alongside per-team rows. Keep only the combined row for traded players so each
    slug appears exactly once.
    """
    counts = df.groupby("slug")["slug"].transform("count")
    traded_mask = counts > 1
    keep = (~traded_mask) | (df["is_combined_totals"] == True)
    return df[keep].drop(columns=["is_combined_totals"]).set_index("slug")


def fetch_all_seasons(seasons=None):
    """
    Returns (basic_dfs, advanced_dfs): two dicts of DataFrames, each keyed
    by season_end_year and indexed by player slug. Seasons with no games
    played yet are skipped.
    """
    seasons = seasons or all_seasons()
    basic_dfs = {}
    advanced_dfs = {}

    for year in seasons:
        print(f"Fetching {season_label(year)}...", end=" ", flush=True)

        basic_rows = client.players_season_totals(season_end_year=year)
        time.sleep(REQUEST_DELAY_SECONDS)
        if not basic_rows:
            print("no games played yet, skipping")
            continue
        basic_dfs[year] = _aggregate_basic(pd.DataFrame(basic_rows))

        adv_rows = client.players_advanced_season_totals(
            season_end_year=year, include_combined_values=True
        )
        time.sleep(REQUEST_DELAY_SECONDS)
        if not adv_rows:
            raise RuntimeError(f"{season_label(year)}: basic stats returned rows but advanced stats did not")
        advanced_dfs[year] = _dedupe_advanced(pd.DataFrame(adv_rows))

        print(
            f"basic={len(basic_dfs[year])} players, "
            f"advanced={len(advanced_dfs[year])} players"
        )

    return basic_dfs, advanced_dfs


def _prepare_for_db(dfs_dict: dict, serialize_team: bool = False) -> pd.DataFrame:
    """
    Concatenates a {season_end_year: DataFrame} dict into one flat DataFrame
    ready for SQLite. Serializes enum columns to strings.
    """
    frames = []
    for year, df in dfs_dict.items():
        df = df.reset_index()  # slug back to column
        df.insert(1, "season_end_year", year)
        df["positions"] = df["positions"].apply(
            lambda p: "/".join(x.value for x in p)
        )
        if serialize_team and "team" in df.columns:
            df["team"] = df["team"].apply(
                lambda t: t.value if t is not None else None
            )
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def save_to_sqlite(basic_dfs: dict, advanced_dfs: dict, db_path: str = DB_PATH, full_rebuild: bool = False):
    """
    full_rebuild=True replaces both tables entirely. Otherwise only the seasons
    in basic_dfs are replaced and every other season is left as is.
    """
    basic_master = _prepare_for_db(basic_dfs, serialize_team=False)
    advanced_master = _prepare_for_db(advanced_dfs, serialize_team=True)
    seasons = sorted(basic_dfs)

    with sqlite3.connect(db_path) as con:
        if full_rebuild:
            basic_master.to_sql("basic_stats", con, if_exists="replace", index=False)
        else:
            replace_season_rows(con, "basic_stats", basic_master, seasons)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_basic_slug_season "
            "ON basic_stats (slug, season_end_year)"
        )

        if full_rebuild:
            advanced_master.to_sql("advanced_stats", con, if_exists="replace", index=False)
        else:
            replace_season_rows(con, "advanced_stats", advanced_master, seasons)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_advanced_slug_season "
            "ON advanced_stats (slug, season_end_year)"
        )

    print(
        f"\nSaved to {db_path}: "
        f"basic_stats={len(basic_master)} rows, "
        f"advanced_stats={len(advanced_master)} rows"
    )


if __name__ == "__main__":
    seasons = parse_season_args("Fetch player season totals from Basketball-Reference.")
    full_rebuild = seasons is None
    basic_dfs, advanced_dfs = fetch_all_seasons(seasons)
    if not basic_dfs:
        print("\nNo season data to save. Database left unchanged.")
        sys.exit(0)
    save_to_sqlite(basic_dfs, advanced_dfs, full_rebuild=full_rebuild)
    print(f"\nDone. {len(basic_dfs)} season(s) saved to {DB_PATH}.")
