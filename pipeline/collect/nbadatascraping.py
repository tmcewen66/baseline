#!/usr/bin/env python3
"""
Fetches per-100-possessions, scoring splits, and advanced stats for NBA
players and teams using the nba_api package and saves them to SQLite tables
'per_100_stats', 'scoring_splits', 'team_per_100_stats', 'team_per_game_stats',
and 'team_advanced_stats' in nba_stats.db.

By default only the current season is fetched, and only its rows are replaced.
Use --all to rebuild every season from 2000-01 on, or --season END_YEAR to
refresh specific seasons. Any failed request stops the script with an error so
a season is never silently dropped.

Rebuilds the BR-to-NBA slug mapping (br_to_nba_mapping.py) afterward, since
saving per_100_stats/scoring_splits replaces those tables and drops their
slug column. Requires basic_stats (from brdatascraping.py) to already be
populated.
"""

import sqlite3
import sys
import time
import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from pipeline.collect import br_to_nba_mapping  # noqa: E402
from pipeline.common import all_seasons, parse_season_args, replace_season_rows, season_label  # noqa: E402

DB_PATH = str(PROJECT_ROOT / "data" / "nba_stats.db")
TABLE_NAME = "per_100_stats"
SCORING_TABLE_NAME = "scoring_splits"
TEAM_TABLE_NAME = "team_per_100_stats"
TEAM_PER_GAME_TABLE_NAME = "team_per_game_stats"
TEAM_ADVANCED_TABLE_NAME = "team_advanced_stats"
REQUEST_DELAY_SECONDS = 3

# Stat columns that get the per_100_ prefix; everything else is just lowercased
_PER_100_STAT_COLS = {
    "MIN", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT",
    "FTM", "FTA", "FT_PCT", "OREB", "DREB", "REB", "AST", "TOV",
    "STL", "BLK", "BLKA", "PF", "PFD", "PTS", "PLUS_MINUS",
    "NBA_FANTASY_PTS", "WNBA_FANTASY_PTS",
}


def _rename_columns(df: pd.DataFrame, prefix: str = "per_100") -> pd.DataFrame:
    return df.rename(columns={
        col: f"{prefix}_{col.lower()}" if col.upper() in _PER_100_STAT_COLS else col.lower()
        for col in df.columns
    })


def _season_str(end_year: int) -> str:
    return season_label(end_year)


def _fetch_seasons(fetch_fn, seasons: list | None, what: str, unit: str) -> pd.DataFrame:
    """
    Calls fetch_fn(end_year) for each season and concatenates the results.
    Seasons with no rows (not started yet) are skipped. Any request error
    stops everything, so a failed season can't quietly go missing.
    """
    seasons = seasons or all_seasons()
    frames = []
    for year in seasons:
        print(f"Fetching {_season_str(year)} {what}...", end=" ", flush=True)
        try:
            df = fetch_fn(year)
        except Exception as e:
            print("ERROR")
            raise RuntimeError(f"Failed to fetch {what} for {_season_str(year)}: {e}") from e
        finally:
            time.sleep(REQUEST_DELAY_SECONDS)
        if df.empty:
            print("no games played yet, skipping")
            continue
        print(f"{len(df)} {unit}")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _write(con, table: str, df: pd.DataFrame, full_rebuild: bool) -> None:
    if full_rebuild:
        df.to_sql(table, con, if_exists="replace", index=False)
    else:
        replace_season_rows(con, table, df, sorted(df["season_end_year"].unique().tolist()))


def fetch_season(end_year: int) -> pd.DataFrame:
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=_season_str(end_year),
        per_mode_detailed="Per100Possessions",
        timeout=60,
    ).get_data_frames()[0]
    df.insert(0, "season_end_year", end_year)
    return df


def fetch_all_seasons(seasons: list | None = None) -> pd.DataFrame:
    return _fetch_seasons(fetch_season, seasons, "player per-100 stats", "players")


def save_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH, full_rebuild: bool = True):
    df = _rename_columns(df)
    with sqlite3.connect(db_path) as con:
        _write(con, TABLE_NAME, df, full_rebuild)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_per100_player_season "
            f"ON {TABLE_NAME} (player_id, season_end_year)"
        )
    print(f"Saved {len(df)} rows to {db_path} table '{TABLE_NAME}'.")


def fetch_scoring_season(end_year: int) -> pd.DataFrame:
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=_season_str(end_year),
        measure_type_detailed_defense="Scoring",
        timeout=60,
    ).get_data_frames()[0]
    df.insert(0, "season_end_year", end_year)
    return df


def fetch_all_scoring_seasons(seasons: list | None = None) -> pd.DataFrame:
    return _fetch_seasons(fetch_scoring_season, seasons, "scoring splits", "players")


def save_scoring_splits_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH, full_rebuild: bool = True):
    # Scoring-measure-type columns are shot-location/assist percentages, not
    # counting stats, so just lowercase column names rather than the
    # per_100_ prefix used for per_100_stats.
    df = df.rename(columns={col: col.lower() for col in df.columns})
    with sqlite3.connect(db_path) as con:
        _write(con, SCORING_TABLE_NAME, df, full_rebuild)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_scoring_splits_player_season "
            f"ON {SCORING_TABLE_NAME} (player_id, season_end_year)"
        )
    print(f"Saved {len(df)} rows to {db_path} table '{SCORING_TABLE_NAME}'.")


def fetch_team_season(end_year: int) -> pd.DataFrame:
    df = leaguedashteamstats.LeagueDashTeamStats(
        season=_season_str(end_year),
        per_mode_detailed="Per100Possessions",
        timeout=60,
    ).get_data_frames()[0]
    df.insert(0, "season_end_year", end_year)
    return df


def fetch_all_team_seasons(seasons: list | None = None) -> pd.DataFrame:
    return _fetch_seasons(fetch_team_season, seasons, "teams", "teams")


def save_team_stats_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH, full_rebuild: bool = True):
    df = _rename_columns(df)
    with sqlite3.connect(db_path) as con:
        _write(con, TEAM_TABLE_NAME, df, full_rebuild)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_team_per100_team_season "
            f"ON {TEAM_TABLE_NAME} (team_id, season_end_year)"
        )
    print(f"Saved {len(df)} rows to {db_path} table '{TEAM_TABLE_NAME}'.")


def fetch_team_per_game_season(end_year: int) -> pd.DataFrame:
    df = leaguedashteamstats.LeagueDashTeamStats(
        season=_season_str(end_year),
        per_mode_detailed="PerGame",
        timeout=60,
    ).get_data_frames()[0]
    df.insert(0, "season_end_year", end_year)
    return df


def fetch_all_team_per_game_seasons(seasons: list | None = None) -> pd.DataFrame:
    return _fetch_seasons(fetch_team_per_game_season, seasons, "team per-game stats", "teams")


def save_team_per_game_stats_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH, full_rebuild: bool = True):
    df = _rename_columns(df, prefix="per_game")
    with sqlite3.connect(db_path) as con:
        _write(con, TEAM_PER_GAME_TABLE_NAME, df, full_rebuild)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_team_per_game_team_season "
            f"ON {TEAM_PER_GAME_TABLE_NAME} (team_id, season_end_year)"
        )
    print(f"Saved {len(df)} rows to {db_path} table '{TEAM_PER_GAME_TABLE_NAME}'.")


def fetch_team_advanced_season(end_year: int) -> pd.DataFrame:
    df = leaguedashteamstats.LeagueDashTeamStats(
        season=_season_str(end_year),
        measure_type_detailed_defense="Advanced",
        timeout=60,
    ).get_data_frames()[0]
    df.insert(0, "season_end_year", end_year)
    return df


def fetch_all_team_advanced_seasons(seasons: list | None = None) -> pd.DataFrame:
    return _fetch_seasons(fetch_team_advanced_season, seasons, "team advanced stats", "teams")


def save_team_advanced_stats_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH, full_rebuild: bool = True):
    # Advanced stats are already rates/ratings (no per-100 counting stats), so
    # just lowercase column names rather than applying the per_100_ prefix.
    df = df.rename(columns={col: col.lower() for col in df.columns})
    with sqlite3.connect(db_path) as con:
        _write(con, TEAM_ADVANCED_TABLE_NAME, df, full_rebuild)
        con.execute(
            f"CREATE INDEX IF NOT EXISTS idx_team_advanced_team_season "
            f"ON {TEAM_ADVANCED_TABLE_NAME} (team_id, season_end_year)"
        )
    print(f"Saved {len(df)} rows to {db_path} table '{TEAM_ADVANCED_TABLE_NAME}'.")


if __name__ == "__main__":
    seasons = parse_season_args("Fetch player and team stats from NBA.com via nba_api.")
    full_rebuild = seasons is None

    steps = [
        ("player per-100 stats", fetch_all_seasons, save_to_sqlite),
        ("scoring splits", fetch_all_scoring_seasons, save_scoring_splits_to_sqlite),
        ("team per-100 stats", fetch_all_team_seasons, save_team_stats_to_sqlite),
        ("team per-game stats", fetch_all_team_per_game_seasons, save_team_per_game_stats_to_sqlite),
        ("team advanced stats", fetch_all_team_advanced_seasons, save_team_advanced_stats_to_sqlite),
    ]

    # Fetch everything before writing anything, so a failure partway through
    # never leaves the database with some tables updated and others not.
    results = [(what, fetch(seasons), save) for what, fetch, save in steps]
    if all(df.empty for _, df, _ in results):
        print("\nNo season data to save. Database left unchanged.")
        sys.exit(0)
    missing = [what for what, df, _ in results if df.empty]
    if missing:
        raise RuntimeError(f"Some endpoints returned no data: {missing}")

    for _, df, save in results:
        save(df, full_rebuild=full_rebuild)

    # New per_100_stats/scoring_splits rows come in without a slug, so rebuild
    # the BR-to-NBA mapping to fill it in.
    print("\nRebuilding BR-to-NBA slug mapping...")
    br_to_nba_mapping.main()
