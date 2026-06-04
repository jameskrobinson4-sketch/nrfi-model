"""
NRFI Model CLI entry point.

Usage:
    python main.py                          # Today's card
    python main.py --date 2025-06-20        # Specific date
    python main.py --date 2025-06-20 --json # JSON output only
    python main.py --min-tier B             # Tier A and B only
    python main.py --game "NYY@BOS"         # Single game deep dive
    python main.py --verbose                # Enable DEBUG logging
"""

import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import click

from models.scoring_engine import score_slate, score_game, GameScore
from output.formatter import print_card, export_json
from data import fetcher
from utils.logger import get_logger, set_global_level

log = get_logger(__name__)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--date", "game_date_str",
    default=None,
    metavar="YYYY-MM-DD",
    help="Date to score (default: today).",
)
@click.option(
    "--json", "json_only",
    is_flag=True,
    default=False,
    help="Write JSON export only; suppress terminal card.",
)
@click.option(
    "--min-tier",
    type=click.Choice(["A", "B", "Skip"], case_sensitive=False),
    default="Skip",
    show_default=True,
    help="Minimum tier to display in terminal output.",
)
@click.option(
    "--game",
    "game_filter",
    default=None,
    metavar="AWAY@HOME",
    help="Score and deep-dive a single matchup (e.g. NYY@BOS).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable DEBUG-level logging.",
)
def main(game_date_str: Optional[str], json_only: bool, min_tier: str,
         game_filter: Optional[str], verbose: bool) -> None:
    """NRFI daily pick-card generator."""
    if verbose:
        set_global_level(logging.DEBUG)

    # Resolve date
    if game_date_str:
        try:
            game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
        except ValueError:
            click.echo(f"Invalid date format: {game_date_str}. Use YYYY-MM-DD.",
                       err=True)
            sys.exit(1)
    else:
        game_date = date.today()

    log.info("Running NRFI model for %s", game_date)

    # Fetch and score
    if game_filter:
        scores = _single_game_dive(game_filter, game_date)
    else:
        scores = score_slate(game_date)

    if not scores:
        click.echo(f"No scorable games found for {game_date}.")
        sys.exit(0)

    # Output
    if not json_only:
        print_card(scores, game_date, min_tier=min_tier.upper())

    json_path = export_json(scores, game_date)
    if json_only:
        click.echo(str(json_path))


def _single_game_dive(game_filter: str, game_date: date) -> list[GameScore]:
    """
    Find and score a single game matching the AWAY@HOME filter string.

    Args:
        game_filter: Matchup string like ``"NYY@BOS"`` (case-insensitive).
        game_date:   Date to search.

    Returns:
        List containing one :class:`GameScore`, or empty list if not found.
    """
    parts = game_filter.upper().replace(" ", "").split("@")
    if len(parts) != 2:
        click.echo(f"Invalid game filter '{game_filter}'. Use format AWAY@HOME.",
                   err=True)
        return []

    away_filter, home_filter = parts
    games = fetcher.fetch_schedule(game_date)
    all_odds = fetcher.fetch_nrfi_odds(game_date)

    for g in games:
        teams = g.get("teams", {})
        home_abbr = teams.get("home", {}).get("team", {}).get("abbreviation", "")
        away_abbr = teams.get("away", {}).get("team", {}).get("abbreviation", "")

        if away_filter in away_abbr and home_filter in home_abbr:
            gs = score_game(g, game_date, all_odds)
            return [gs] if gs else []

    click.echo(f"Game '{game_filter}' not found on {game_date}.", err=True)
    return []


if __name__ == "__main__":
    main()
