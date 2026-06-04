"""Matchup scoring — evaluates opposing team's top-3 hitters vs starting pitcher."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from utils.logger import get_logger
from data import fetcher

log = get_logger(__name__)


@dataclass
class MatchupResult:
    score: float
    lineup_confirmed: bool = False
    data_quality: str = "full"
    flags: list[str] = field(default_factory=list)
    hitters: list[dict] = field(default_factory=list)


def score_matchup(game_pk: int, batting_team_side: str,
                  pitcher_hand: str, game_date: date,
                  end_date: Optional[date] = None) -> MatchupResult:
    """
    Score the top-3 hitters in the batting lineup against the starter.
    end_date: if provided, restricts stats to that date (backtest mode).
    Higher score = lineup less likely to score in the first inning.
    """
    import config
    season   = game_date.year
    boxscore = fetcher.fetch_lineup(game_pk, game_date)
    batters, confirmed = _get_top3(boxscore, batting_team_side)

    flags = []
    if not confirmed:
        flags.append("lineup_not_confirmed")

    if not batters:
        return MatchupResult(
            score=50.0, lineup_confirmed=False,
            data_quality="minimal", flags=["no_lineup_data"],
        )

    scores  = []
    hitter_details = []

    for i, (batter_id, batter_name) in enumerate(batters):
        season_data  = fetcher.fetch_batter_stats(batter_id, season, game_date, end_date)
        platoon_data = fetcher.fetch_batter_platoon_splits(
            batter_id, season, pitcher_hand, game_date, end_date
        )

        season_stats  = _extract_stats(season_data)
        platoon_stats = _extract_platoon_stats(platoon_data)

        # Use platoon OBP if available and has sufficient sample
        platoon_pa  = _sf(platoon_stats.get("plateAppearances"), 0)
        use_platoon = platoon_pa >= 30

        obp = _sf(
            (platoon_stats if use_platoon else season_stats).get("obp"),
            0.320
        )
        ops = _sf(
            (platoon_stats if use_platoon else season_stats).get("ops"),
            0.740
        )

        if not use_platoon and platoon_pa > 0:
            flags.append(f"platoon_small_sample_{batter_name.split()[0]}({platoon_pa:.0f}pa)")
        elif use_platoon:
            flags.append(f"platoon_obp_used_{batter_name.split()[0]}")

        # K% from raw counts
        so  = _sf(season_stats.get("strikeOuts"), None)
        ab  = _sf(season_stats.get("atBats"), None)
        bb  = _sf(season_stats.get("baseOnBalls"), 0.0)
        hbp = _sf(season_stats.get("hitByPitch"), 0.0)
        sf  = _sf(season_stats.get("sacFlies"), 0.0)

        k_rate = None
        if so is not None and ab is not None:
            pa = ab + bb + hbp + sf
            k_rate = round((so / pa) * 100, 1) if pa > 0 else 22.0
        if k_rate is None:
            k_rate = 22.0

        # Higher OBP = more dangerous = worse for NRFI → invert
        obp_score = min(100, max(0, (0.340 - obp)  / 0.130 * 50 + 50))
        ops_score = min(100, max(0, (0.760 - ops)  / 0.300 * 50 + 50))
        k_score   = min(100, max(0, (k_rate - 20.0) / 18.0  * 20 + 50))

        batter_score = obp_score * 0.50 + ops_score * 0.30 + k_score * 0.20
        scores.append(batter_score)
        hitter_details.append({
            "id":      batter_id,
            "name":    batter_name,
            "obp":     round(obp, 3),
            "ops":     round(ops, 3),
            "k_pct":   round(k_rate, 1),
            "platoon": use_platoon,
            "score":   round(batter_score, 1),
        })

        log.debug("  Hitter %d %s: obp=%.3f ops=%.3f k%%=%.1f platoon=%s → %.1f",
                  i+1, batter_name, obp, ops, k_rate, use_platoon, batter_score)

    weights = [config.MATCHUP_W_BATTER1, config.MATCHUP_W_BATTER2,
               config.MATCHUP_W_BATTER3][:len(scores)]
    total_w = sum(weights)
    final   = sum(s * w for s, w in zip(scores, weights)) / total_w if total_w else 50.0

    return MatchupResult(
        score=round(min(100, max(0, final)), 1),
        lineup_confirmed=confirmed,
        data_quality="full" if confirmed else "partial",
        flags=flags,
        hitters=hitter_details,
    )


def _get_top3(boxscore: dict, side: str) -> tuple[list, bool]:
    try:
        team    = boxscore.get("teams", {}).get(side, {})
        order   = team.get("battingOrder", [])
        players = team.get("players", {})
        if not order:
            return [], False
        result = []
        for pid in order[:3]:
            p = players.get(f"ID{pid}", {})
            person = p.get("person", {})
            result.append((
                person.get("id", pid),
                person.get("fullName", f"Player {pid}"),
            ))
        return result, True
    except Exception as e:
        log.warning("Lineup parse error: %s", e)
        return [], False


def _extract_stats(data: dict) -> dict:
    for group in data.get("stats", []):
        splits = group.get("splits", [])
        if splits:
            return splits[0].get("stat", {})
    return {}


def _extract_platoon_stats(data: dict) -> dict:
    """Extract stats from statSplits response."""
    for group in data.get("stats", []):
        splits = group.get("splits", [])
        if splits:
            stat = splits[0].get("stat", {})
            pa   = splits[0].get("stat", {}).get("plateAppearances", 0)
            return {**stat, "plateAppearances": pa}
    return {}


def _sf(val, default):
    if val is None:
        return default
    if isinstance(val, str) and val.strip() in ("", "-.--", "-"):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
