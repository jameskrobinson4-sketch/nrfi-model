"""
Scoring engine: combines module scores → final P(NRFI) and tier assignment.

P(NRFI) = P(away scoreless in top 1st) × P(home scoreless in bottom 1st)

end_date parameter enables backtest mode — all stat fetches restricted to
stats available before that date (prevents look-ahead bias).
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import config
from data import fetcher
from models.pitcher_score import PitcherResult, score_pitcher
from models.matchup_score import MatchupResult, score_matchup
from models.environment_score import EnvironmentResult, score_environment
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class HalfInningScore:
    pitcher: PitcherResult
    matchup: MatchupResult
    p_scoreless: float


@dataclass
class GameScore:
    game_pk: int
    home_team: str
    away_team: str
    game_time: str
    top_half: HalfInningScore
    bottom_half: HalfInningScore
    environment: EnvironmentResult
    raw_score: float
    p_nrfi: float
    confidence_band: float
    tier: str
    data_quality: str = "full"
    flags: list[str] = field(default_factory=list)
    first_pitch_utc: Optional[str] = None


def score_game(game: dict, game_date: date,
               all_odds: Optional[list[dict]] = None,
               end_date: Optional[date] = None,
               historical: bool = False) -> Optional[GameScore]:
    """
    Score a single game for NRFI probability.
    end_date: restrict stats to this date (backtest mode).
    historical: use archive weather API (backtest mode).
    """
    game_pk   = game.get("gamePk", 0)
    teams     = game.get("teams", {})
    home      = teams.get("home", {})
    away      = teams.get("away", {})
    home_abbr = home.get("team", {}).get("abbreviation", "???")
    away_abbr = away.get("team", {}).get("abbreviation", "???")

    home_team_id      = home.get("team", {}).get("id")
    away_team_id      = away.get("team", {}).get("id")
    home_pitcher_data = home.get("probablePitcher", {})
    away_pitcher_data = away.get("probablePitcher", {})
    home_pitcher_id   = home_pitcher_data.get("id")
    away_pitcher_id   = away_pitcher_data.get("id")
    home_pitcher_name = home_pitcher_data.get("fullName", "Unknown")
    away_pitcher_name = away_pitcher_data.get("fullName", "Unknown")

    if not home_pitcher_id and not away_pitcher_id:
        log.warning("No probable pitchers for %s @ %s — skipping", away_abbr, home_abbr)
        return None

    game_dt_str    = game.get("gameDate", "")
    first_pitch_dt: Optional[datetime] = None
    try:
        first_pitch_dt = datetime.fromisoformat(game_dt_str.replace("Z", "+00:00"))
    except ValueError:
        pass

    game_time_str = _format_game_time(first_pitch_dt, home_abbr) if first_pitch_dt else "TBD"
    log.info("Scoring %s @ %s (pk=%d)", away_abbr, home_abbr, game_pk)

    # ── Shared environment ────────────────────────────────────────────────────
    game_odds_dict = _find_odds(all_odds, home_abbr, away_abbr) if all_odds else None
    env_result = score_environment(
        game_pk=game_pk,
        home_team=home_abbr,
        game_date=game_date,
        first_pitch_dt=first_pitch_dt,
        game_odds=game_odds_dict,
        historical=historical,
    )

    # ── TOP 1st: away bats vs home pitcher ────────────────────────────────────
    if home_pitcher_id:
        home_pitcher_result = score_pitcher(
            home_pitcher_id, home_pitcher_name, game_date, end_date
        )
    else:
        home_pitcher_result = PitcherResult(
            pitcher_id=0, pitcher_name="TBA", score=50.0,
            data_quality="minimal", flags=["pitcher_not_announced"],
        )

    top_matchup = score_matchup(
        game_pk=game_pk,
        batting_team_side="away",
        pitcher_hand=home_pitcher_result.handedness,
        game_date=game_date,
        team_id=away_team_id,
        end_date=end_date,
    )

    top_half = HalfInningScore(
        pitcher=home_pitcher_result,
        matchup=top_matchup,
        p_scoreless=_half_inning_prob(
            home_pitcher_result.score, top_matchup.score, env_result.score
        ),
    )

    # ── BOTTOM 1st: home bats vs away pitcher ─────────────────────────────────
    if away_pitcher_id:
        away_pitcher_result = score_pitcher(
            away_pitcher_id, away_pitcher_name, game_date, end_date
        )
    else:
        away_pitcher_result = PitcherResult(
            pitcher_id=0, pitcher_name="TBA", score=50.0,
            data_quality="minimal", flags=["pitcher_not_announced"],
        )

    bottom_matchup = score_matchup(
        game_pk=game_pk,
        batting_team_side="home",
        pitcher_hand=away_pitcher_result.handedness,
        game_date=game_date,
        team_id=home_team_id,
        end_date=end_date,
    )

    bottom_half = HalfInningScore(
        pitcher=away_pitcher_result,
        matchup=bottom_matchup,
        p_scoreless=_half_inning_prob(
            away_pitcher_result.score, bottom_matchup.score, env_result.score
        ),
    )

    # ── Combined NRFI probability ─────────────────────────────────────────────
    p_nrfi    = top_half.p_scoreless * bottom_half.p_scoreless
    top_raw   = _raw_score(top_half.pitcher.score, top_matchup.score, env_result.score)
    bot_raw   = _raw_score(bottom_half.pitcher.score, bottom_matchup.score, env_result.score)
    raw_score = (top_raw + bot_raw) / 2.0

    band = _confidence_band(top_half, bottom_half, env_result)
    tier = _assign_tier(p_nrfi)

    all_flags = (
        top_half.pitcher.flags + top_half.matchup.flags +
        bottom_half.pitcher.flags + bottom_half.matchup.flags +
        env_result.flags
    )
    qualities    = {
        top_half.pitcher.data_quality, top_half.matchup.data_quality,
        bottom_half.pitcher.data_quality, bottom_half.matchup.data_quality,
        env_result.data_quality,
    }
    overall_dq = (
        "full"    if qualities == {"full"} else
        "minimal" if "minimal" in qualities else "partial"
    )

    log.info(
        "%s @ %s: top=%.1f%% bottom=%.1f%% → P(NRFI)=%.1f%% ±%.1f%% [%s]",
        away_abbr, home_abbr,
        top_half.p_scoreless * 100,
        bottom_half.p_scoreless * 100,
        p_nrfi * 100, band, tier,
    )

    return GameScore(
        game_pk=game_pk, home_team=home_abbr, away_team=away_abbr,
        game_time=game_time_str, top_half=top_half, bottom_half=bottom_half,
        environment=env_result, raw_score=round(raw_score, 1),
        p_nrfi=p_nrfi, confidence_band=band, tier=tier,
        data_quality=overall_dq, flags=all_flags,
        first_pitch_utc=game_dt_str,
    )


def score_slate(game_date: date) -> list[GameScore]:
    games    = fetcher.fetch_schedule(game_date)
    all_odds = fetcher.fetch_nrfi_odds(game_date)
    results  = []
    for g in games:
        try:
            gs = score_game(g, game_date, all_odds)
            if gs:
                results.append(gs)
        except Exception as exc:
            log.error("Error scoring game %s: %s", g.get("gamePk"), exc, exc_info=True)
    results.sort(key=lambda x: x.p_nrfi, reverse=True)
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raw_score(pitcher: float, matchup: float, env: float) -> float:
    return (pitcher * config.WEIGHT_PITCHER +
            matchup * config.WEIGHT_MATCHUP +
            env     * config.WEIGHT_ENVIRONMENT)


def _half_inning_prob(pitcher: float, matchup: float, env: float) -> float:
    raw = float(max(0, min(100, _raw_score(pitcher, matchup, env))))
    return _logistic(raw)


def _logistic(raw: float) -> float:
    return 1.0 / (1.0 + math.exp(-config.LOGISTIC_SCALE * (raw - config.LOGISTIC_MIDPOINT)))


def _confidence_band(top: HalfInningScore, bot: HalfInningScore,
                     env: EnvironmentResult) -> float:
    band = config.CONFIDENCE_BASE_PCT
    if not top.matchup.lineup_confirmed:
        band += config.CONFIDENCE_NO_LINEUP_PENALTY
    if not bot.matchup.lineup_confirmed:
        band += config.CONFIDENCE_NO_LINEUP_PENALTY
    if top.pitcher.data_quality == "minimal":
        band += 1.0
    if bot.pitcher.data_quality == "minimal":
        band += 1.0
    if env.data_quality == "partial":
        band += 0.5
    return round(band, 1)


def _assign_tier(prob: float) -> str:
    if prob >= config.TIER_A_THRESHOLD: return "A"
    if prob >= config.TIER_B_THRESHOLD: return "B"
    return "Skip"


def _find_odds(all_odds: list[dict], home: str, away: str) -> Optional[dict]:
    for o in all_odds:
        ht = (o.get("home_team") or "").upper()
        at = (o.get("away_team") or "").upper()
        if home in ht or ht in home or away in at or at in away:
            return o
    return None


_PARK_UTC_OFFSET: dict[str, int] = {
    "BOS": -4, "NYY": -4, "NYM": -4, "PHI": -4, "ATL": -4, "MIA": -4,
    "TOR": -4, "BAL": -4, "WSH": -4, "TB":  -4, "CLE": -4, "DET": -4,
    "PIT": -4, "CIN": -4, "CHC": -5, "MIL": -5, "STL": -5, "MIN": -5,
    "CWS": -5, "KC":  -5, "HOU": -5, "TEX": -5, "COL": -6, "ARI": -7,
    "LAD": -7, "LAA": -7, "SD":  -7, "SF":  -7, "SEA": -7, "OAK": -7,
    "ATH": -7,
}
_TZ_LABEL = {-4: "ET", -5: "CT", -6: "MT", -7: "PT"}


def _format_game_time(utc_dt: datetime, home_team: str) -> str:
    offset = _PARK_UTC_OFFSET.get(home_team, -4)
    label  = _TZ_LABEL.get(offset, "ET")
    local  = utc_dt + timedelta(hours=offset)
    try:
        return local.strftime("%-I:%M %p ") + label
    except ValueError:
        return local.strftime("%I:%M %p ").lstrip("0") + label
