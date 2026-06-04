"""Pitcher scoring module — evaluates starting pitcher for NRFI probability."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from utils.logger import get_logger
from data import fetcher

log = get_logger(__name__)


@dataclass
class PitcherResult:
    pitcher_id: int
    pitcher_name: str
    score: float
    handedness: str = "R"
    data_quality: str = "full"
    flags: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)


def score_pitcher(pitcher_id: int, pitcher_name: str, game_date: date,
                  end_date: Optional[date] = None) -> PitcherResult:
    """
    Score a starting pitcher for NRFI likelihood.
    end_date: if provided, restricts stats to that date (backtest mode).
    Higher score = better chance of no run in the first inning.
    """
    import config
    season     = game_date.year
    handedness = fetcher.fetch_pitcher_hand(pitcher_id, game_date)
    data       = fetcher.fetch_pitcher_stats(pitcher_id, season, game_date, end_date)
    fi_era     = fetcher.fetch_pitcher_fi_era(pitcher_id, season, game_date)

    season_stats = _extract_season_stats(data)
    if not season_stats:
        log.warning("No stats for %s — neutral score", pitcher_name)
        return PitcherResult(
            pitcher_id, pitcher_name, 50.0,
            handedness=handedness,
            data_quality="minimal", flags=["no_season_stats"],
        )

    era  = _sf(season_stats.get("era"), 4.50)
    k9   = _sf(season_stats.get("strikeoutsPer9Inn"), None)
    bb9  = _sf(season_stats.get("walksPer9Inn"), 3.2)
    hr9  = _sf(season_stats.get("homeRunsPer9"), 1.2)
    whip = _sf(season_stats.get("whip"), 1.30)
    ip   = _sf(season_stats.get("inningsPitched"), 0.0)

    flags = []

    # K9 fallback — compute from raw strikeouts/IP if per-9 unavailable
    if k9 is None:
        so = _sf(season_stats.get("strikeOuts"), None)
        if so is not None and ip > 0:
            k9 = round((so / ip) * 9, 2)
            flags.append(f"k9_computed({so:.0f}so/{ip:.1f}ip)")
        else:
            k9 = 7.5
            flags.append("k9_defaulted_insufficient_data")

    # First-inning ERA — use if available, otherwise fall back to overall ERA
    if fi_era is not None:
        era_used = max(1.0, min(9.0, fi_era))
        flags.append(f"using_fi_era_{fi_era:.2f}")
    else:
        era_used = max(1.0, min(9.0, era))

    # Normalize vs 2025 MLB averages → 0-100 where higher = better for NRFI
    k9_score   = min(100, max(0, (k9   - 7.5) / 4.5  * 50 + 50))
    bb9_score  = min(100, max(0, (3.5  - bb9)  / 2.0  * 50 + 50))
    hr9_score  = min(100, max(0, (1.3  - hr9)  / 0.9  * 50 + 50))
    era_score  = min(100, max(0, (4.50 - era_used) / 3.0 * 50 + 50))
    whip_score = min(100, max(0, (1.35 - whip) / 0.55 * 50 + 50))

    sample_penalty = max(0.0, (20.0 - ip) / 20.0 * 8.0) if ip < 20 else 0.0
    if sample_penalty > 0:
        flags.append(f"small_sample_{ip:.1f}ip")

    rest_score, rest_days, rest_flag = _rest_score(data, game_date)
    if rest_flag:
        flags.append(rest_flag)

    raw = (
        k9_score   * config.PITCHER_W_KRATE  +
        bb9_score  * config.PITCHER_W_BBRATE +
        hr9_score  * config.PITCHER_W_HRRATE +
        era_score  * config.PITCHER_W_FI_ERA +
        whip_score * config.PITCHER_W_FPS    +
        rest_score * config.PITCHER_W_REST
    )
    raw = max(0, raw - sample_penalty)

    # Recent form penalty
    recent_era = _recent_era(data)
    if recent_era is not None and ip >= 10 and (recent_era - era) > config.PITCHER_RECENT_FORM_THRESHOLD:
        raw *= (1 - config.PITCHER_RECENT_FORM_PENALTY)
        flags.append(f"recent_form_penalty(L3_ERA={recent_era:.2f} season={era:.2f})")

    log.debug(
        "Pitcher %s [%s]: K9=%.1f(→%.0f) BB9=%.1f(→%.0f) ERA=%.2f(→%.0f) "
        "WHIP=%.2f(→%.0f) rest=%dd(→%.0f) ip=%.1f raw=%.1f",
        pitcher_name, handedness, k9, k9_score, bb9, bb9_score,
        era_used, era_score, whip, whip_score, rest_days, rest_score, ip, raw,
    )

    return PitcherResult(
        pitcher_id=pitcher_id,
        pitcher_name=pitcher_name,
        score=round(min(100, max(5, raw)), 1),
        handedness=handedness,
        data_quality="full" if ip >= 10 else "partial",
        flags=flags,
        components={
            "k9":       round(k9_score, 1),
            "bb9":      round(bb9_score, 1),
            "hr9":      round(hr9_score, 1),
            "era":      round(era_score, 1),
            "whip":     round(whip_score, 1),
            "rest":     round(rest_score, 1),
            "rest_days": rest_days,
            "ip":        ip,
            "fi_era":    fi_era,
        },
    )


def _extract_season_stats(data: dict) -> dict:
    for group in data.get("stats", []):
        if group.get("type", {}).get("displayName") == "season":
            splits = group.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    return {}


def _rest_score(data: dict, game_date: date) -> tuple[float, int, str]:
    for group in data.get("stats", []):
        if group.get("type", {}).get("displayName") == "gameLog":
            splits = group.get("splits", [])
            if not splits:
                return 50.0, 0, "rest_no_gamelog_entries"
            last_date_str = ""
            for sp in reversed(splits):
                d = sp.get("date", "")[:10]
                try:
                    if datetime.strptime(d, "%Y-%m-%d").date() < game_date:
                        last_date_str = d
                        break
                except ValueError:
                    continue
            if not last_date_str:
                return 50.0, 0, "rest_no_prior_start"
            try:
                last_start = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                rest_days  = (game_date - last_start).days
            except ValueError:
                return 50.0, 0, "rest_date_parse_error"
            if rest_days < 4:
                return 25.0, rest_days, f"short_rest_{rest_days}d"
            elif rest_days <= 5:
                return 65.0, rest_days, ""
            elif rest_days <= 8:
                return 52.0, rest_days, ""
            else:
                return 35.0, rest_days, f"long_layoff_{rest_days}d"
    return 50.0, 0, "rest_no_gamelog"


def _recent_era(data: dict) -> Optional[float]:
    for group in data.get("stats", []):
        if group.get("type", {}).get("displayName") == "gameLog":
            splits = group.get("splits", [])
            last3  = splits[-3:] if len(splits) >= 3 else splits
            if not last3:
                return None
            er  = sum(_sf(s.get("stat", {}).get("earnedRuns"), 0) for s in last3)
            ip  = sum(_sf(s.get("stat", {}).get("inningsPitched"), 0) for s in last3)
            return round((er / ip) * 9, 2) if ip > 0 else None
    return None


def _sf(val, default):
    if val is None:
        return default
    if isinstance(val, str) and val.strip() in ("", "-.--", "-"):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
