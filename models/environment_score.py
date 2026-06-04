"""Environment scoring — park factors, weather, and umpire tendencies."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from utils.logger import get_logger
from data import fetcher

log = get_logger(__name__)

PARK_TZ_OFFSET: dict[str, int] = {
    "BOS": -4, "NYY": -4, "NYM": -4, "PHI": -4, "ATL": -4, "MIA": -4,
    "TOR": -4, "BAL": -4, "WSH": -4, "TB":  -4, "CLE": -4, "DET": -4,
    "PIT": -4, "CIN": -4, "CHC": -5, "MIL": -5, "STL": -5, "MIN": -5,
    "CWS": -5, "KC":  -5, "HOU": -5, "TEX": -5, "COL": -6, "ARI": -7,
    "LAD": -7, "LAA": -7, "SD":  -7, "SF":  -7, "SEA": -7, "OAK": -7,
    "ATH": -7,
}
TZ_LABEL: dict[int, str] = {-4: "ET", -5: "CT", -6: "MT", -7: "PT"}


@dataclass
class EnvironmentResult:
    score: float
    line_adjustment: float = 0.0
    data_quality: str = "full"
    flags: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)


def score_environment(game_pk: int, home_team: str, game_date: date,
                      first_pitch_dt: Optional[datetime] = None,
                      game_odds: Optional[dict] = None,
                      historical: bool = False) -> EnvironmentResult:
    """
    Score the game environment: park + weather + umpire.
    historical=True uses archive weather API (for backtest).
    """
    import config
    from utils.park_factors import PARK_FACTORS

    flags      = []
    components = {}

    # ── Park ─────────────────────────────────────────────────────────────────
    pf        = PARK_FACTORS.get(home_team, {"run_factor": 100, "hr_factor": 100,
                                              "foul_territory": "medium", "name": home_team})
    run_factor = pf["run_factor"]
    hr_factor  = pf["hr_factor"]
    foul       = pf["foul_territory"]

    park_score = min(100, max(0, (100 - run_factor) * 1.5 + 50))
    park_score += (100 - hr_factor) * 0.3
    if foul == "large":
        park_score = min(100, park_score + 6)
    elif foul == "small":
        park_score = max(0, park_score - 6)

    components["park"] = round(park_score, 1)

    # ── Weather ───────────────────────────────────────────────────────────────
    weather_score = 50.0
    is_domed      = home_team in config.DOMED_PARKS

    if is_domed:
        weather_score = 55.0
        flags.append("domed_park")
    elif first_pitch_dt and home_team in config.PARK_COORDS:
        lat, lon = config.PARK_COORDS[home_team]
        local_dt = _to_local(first_pitch_dt, home_team)
        wx = fetcher.fetch_weather(lat, lon, game_date, local_dt,
                                   historical=historical)
        weather_score, wx_flags = _parse_weather(wx, local_dt, home_team)
        flags.extend(wx_flags)
    else:
        flags.append("weather_unavailable")

    components["weather"] = round(weather_score, 1)

    # ── Umpire ────────────────────────────────────────────────────────────────
    from utils.umpire_ratings import get_umpire_score
    umpire_name  = fetcher.fetch_umpire(game_pk, game_date)
    umpire_score, ump_found = get_umpire_score(umpire_name) if umpire_name else (50.0, False)

    if ump_found:
        flags.append(f"umpire_{umpire_name.split()[-1]}_zone_scored")
    elif umpire_name:
        flags.append(f"umpire_{umpire_name.split()[-1]}_not_in_table")
    else:
        flags.append("umpire_not_announced")

    components["umpire"]      = round(umpire_score, 1)
    components["umpire_name"] = umpire_name or "TBA"

    # ── Combine sub-scores ────────────────────────────────────────────────────
    park_w    = config.WEIGHT_PARK    / config.WEIGHT_ENVIRONMENT
    weather_w = config.WEIGHT_WEATHER / config.WEIGHT_ENVIRONMENT
    umpire_w  = config.WEIGHT_UMPIRE  / config.WEIGHT_ENVIRONMENT

    env_score = (
        park_score    * park_w +
        weather_score * weather_w +
        umpire_score  * umpire_w
    )

    # ── Line movement ──────────────────────────────────────────────────────────
    line_adj = 0.0
    if game_odds:
        line_adj = _line_adjustment(game_odds)
        if line_adj != 0:
            flags.append(f"line_movement_adj={line_adj:+.1f}")

    dq = "partial" if "weather_unavailable" in flags else "full"

    return EnvironmentResult(
        score=round(min(100, max(0, env_score)), 1),
        line_adjustment=line_adj,
        data_quality=dq,
        flags=flags,
        components=components,
    )


def _to_local(dt: datetime, team: str) -> datetime:
    offset = PARK_TZ_OFFSET.get(team, -4)
    return dt + timedelta(hours=offset)


def _parse_weather(wx: dict, local_dt: datetime, team: str) -> tuple[float, list]:
    import config
    flags = []
    if not wx or "hourly" not in wx:
        return 50.0, ["weather_parse_failed"]

    hourly = wx["hourly"]
    times  = hourly.get("time", [])
    target = local_dt.strftime("%Y-%m-%dT%H:00")
    idx    = next((i for i, t in enumerate(times) if t.startswith(target[:13])), None)

    if idx is None:
        target_date = local_dt.strftime("%Y-%m-%d")
        evening = f"{target_date}T18:00"
        idx = next((i for i, t in enumerate(times) if t == evening), None)

    if idx is None:
        return 50.0, ["weather_hour_not_found"]

    def _val(key, default):
        arr = hourly.get(key, [])
        return float(arr[idx]) if idx < len(arr) else default

    wind_speed = _val("windspeed_10m",      5.0)
    wind_dir   = _val("winddirection_10m",  180.0)
    temp_f     = _val("temperature_2m",     70.0)
    humidity   = _val("relativehumidity_2m", 50.0)

    orient   = config.PARK_ORIENTATIONS.get(team, 0.0)
    relative = (wind_dir - orient) % 360

    if 315 <= relative or relative <= 45:
        wind_factor = -wind_speed * 0.9
        wind_label  = "blowing_out"
    elif 135 <= relative <= 225:
        wind_factor = wind_speed * 0.9
        wind_label  = "blowing_in"
    else:
        wind_factor = wind_speed * 0.15
        wind_label  = "crosswind"

    if temp_f < 45:       temp_bonus = 12.0
    elif temp_f < 55:     temp_bonus =  7.0
    elif temp_f < 65:     temp_bonus =  3.0
    elif temp_f > 90:     temp_bonus = -5.0
    elif temp_f > 80:     temp_bonus = -2.0
    else:                 temp_bonus =  0.0

    humidity_factor = (humidity - 50) * 0.04
    score = min(100, max(0, 50.0 + wind_factor + temp_bonus + humidity_factor))
    flags.append(f"{wind_speed:.0f}mph_{wind_label}_{temp_f:.0f}F_{humidity:.0f}%rh")
    return score, flags


def _line_adjustment(odds: dict) -> float:
    return 0.0
