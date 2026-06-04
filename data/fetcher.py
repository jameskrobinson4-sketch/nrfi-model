"""All external HTTP calls. Swap data sources here only."""

import requests
from datetime import date, datetime, timedelta
from typing import Optional
from utils.logger import get_logger
from data import cache as _cache

log = get_logger(__name__)
MLB_BASE    = "https://statsapi.mlb.com/api/v1"
METEO_BASE  = "https://api.open-meteo.com/v1/forecast"
METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT     = 12

WEATHER_PARAMS = "windspeed_10m,winddirection_10m,temperature_2m,relativehumidity_2m"


def _get(url: str, params: dict = None) -> dict:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_schedule(game_date: date) -> list[dict]:
    key = f"schedule_{game_date}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached
    try:
        data = _get(f"{MLB_BASE}/schedule", {
            "sportId": 1,
            "date": game_date.strftime("%Y-%m-%d"),
            "hydrate": "team,probablePitcher",
        })
        games = []
        for d in data.get("dates", []):
            games.extend(d.get("games", []))
        log.info("Fetched %d games for %s", len(games), game_date)
        _cache.put(key, game_date, games)
        return games
    except Exception as e:
        log.error("Schedule fetch failed: %s", e)
        return []


def fetch_pitcher_stats(pitcher_id: int, season: int, game_date: date,
                        end_date: Optional[date] = None) -> dict:
    """
    Fetch pitcher season stats + game log.
    If end_date is provided, restricts to stats up to that date (backtest mode).
    """
    key = f"pitcher_{pitcher_id}_season_{season}"
    if end_date:
        key += f"_asof_{end_date}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached
    try:
        params = {
            "stats": "season,gameLog",
            "group": "pitching",
            "season": season,
            "sportId": 1,
        }
        if end_date:
            params["startDate"] = f"{season}-03-01"
            params["endDate"]   = str(end_date)
        data = _get(f"{MLB_BASE}/people/{pitcher_id}/stats", params)
        _cache.put(key, game_date, data)
        return data
    except Exception as e:
        log.warning("Pitcher stats failed id=%d: %s", pitcher_id, e)
        return {}


def fetch_pitcher_fi_era(pitcher_id: int, season: int, game_date: date) -> Optional[float]:
    """
    Fetch first-inning ERA split for a pitcher.
    Returns None if unavailable.
    """
    key = f"pitcher_fi_era_{pitcher_id}_{season}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached.get("fi_era")
    try:
        data = _get(f"{MLB_BASE}/people/{pitcher_id}/stats", {
            "stats": "statSplits",
            "group": "pitching",
            "season": season,
            "sportId": 1,
            "sitCodes": "i1",
        })
        fi_era = None
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                era_str = split.get("stat", {}).get("era")
                if era_str and era_str not in ("-.--", "-", ""):
                    try:
                        fi_era = float(era_str)
                        break
                    except (ValueError, TypeError):
                        pass
        _cache.put(key, game_date, {"fi_era": fi_era})
        return fi_era
    except Exception as e:
        log.debug("First-inning ERA fetch failed id=%d: %s", pitcher_id, e)
        return None


def fetch_pitcher_hand(pitcher_id: int, game_date: date) -> str:
    """Fetch pitcher handedness (L/R)."""
    key = f"pitcher_hand_{pitcher_id}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached.get("hand", "R")
    try:
        data = _get(f"{MLB_BASE}/people/{pitcher_id}", {"hydrate": "pitchHand"})
        people = data.get("people", [])
        if people:
            hand = people[0].get("pitchHand", {}).get("code", "R")
            _cache.put(key, game_date, {"hand": hand})
            return hand
    except Exception as e:
        log.warning("Pitcher hand fetch failed id=%d: %s", pitcher_id, e)
    return "R"


def fetch_lineup(game_pk: int, game_date: date) -> dict:
    key = f"lineup_{game_pk}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached
    try:
        data = _get(f"{MLB_BASE}/game/{game_pk}/boxscore")
        _cache.put(key, game_date, data)
        return data
    except Exception as e:
        log.warning("Lineup fetch failed pk=%d: %s", game_pk, e)
        return {}


def fetch_batter_stats(batter_id: int, season: int, game_date: date,
                       end_date: Optional[date] = None) -> dict:
    """
    Fetch batter season stats.
    If end_date provided, restricts to stats up to that date (backtest mode).
    """
    key = f"batter_{batter_id}_season_{season}"
    if end_date:
        key += f"_asof_{end_date}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached
    try:
        params = {
            "stats": "season",
            "group": "hitting",
            "season": season,
            "sportId": 1,
        }
        if end_date:
            params["startDate"] = f"{season}-03-01"
            params["endDate"]   = str(end_date)
        data = _get(f"{MLB_BASE}/people/{batter_id}/stats", params)
        _cache.put(key, game_date, data)
        return data
    except Exception as e:
        log.warning("Batter stats failed id=%d: %s", batter_id, e)
        return {}


def fetch_batter_platoon_splits(batter_id: int, season: int,
                                 pitcher_hand: str, game_date: date,
                                 end_date: Optional[date] = None) -> dict:
    """
    Fetch batter vs LHP or RHP splits.
    sit_code: 'vr' = vs RHP, 'vl' = vs LHP
    """
    sit_code = "vr" if pitcher_hand == "R" else "vl"
    key = f"batter_platoon_{batter_id}_{season}_{sit_code}"
    if end_date:
        key += f"_asof_{end_date}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached
    try:
        params = {
            "stats": "statSplits",
            "group": "hitting",
            "season": season,
            "sportId": 1,
            "sitCodes": sit_code,
        }
        if end_date:
            params["startDate"] = f"{season}-03-01"
            params["endDate"]   = str(end_date)
        data = _get(f"{MLB_BASE}/people/{batter_id}/stats", params)
        _cache.put(key, game_date, data)
        return data
    except Exception as e:
        log.debug("Platoon splits failed id=%d %s: %s", batter_id, sit_code, e)
        return {}


def fetch_umpire(game_pk: int, game_date: date) -> str:
    """
    Fetch the home plate umpire name from the boxscore officials list.
    Returns empty string if unavailable.
    """
    key = f"umpire_{game_pk}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached.get("name", "")
    try:
        data = _get(f"{MLB_BASE}/game/{game_pk}/boxscore")
        officials = data.get("officials", [])
        for official in officials:
            if official.get("officialType", "").lower() == "home plate":
                name = official.get("official", {}).get("fullName", "")
                _cache.put(key, game_date, {"name": name})
                return name
        _cache.put(key, game_date, {"name": ""})
        return ""
    except Exception as e:
        log.debug("Umpire fetch failed pk=%d: %s", game_pk, e)
        return ""


def fetch_weather(lat: float, lon: float, game_date: date,
                  first_pitch_dt: Optional[datetime] = None,
                  historical: bool = False) -> dict:
    """
    Fetch weather data. Uses archive API for past dates, forecast for future.
    historical=True forces archive API regardless of date.
    """
    key = f"weather_{round(lat,3)}_{round(lon,3)}_{game_date}"
    cached = _cache.get(key, game_date)
    if cached is not None:
        return cached

    import config
    today = date.today()
    use_archive = historical or game_date < today

    base_params = {
        "latitude":          lat,
        "longitude":         lon,
        "hourly":            WEATHER_PARAMS,
        "windspeed_unit":    "mph",
        "temperature_unit":  "fahrenheit",
        "timezone":          "America/New_York",
        "start_date":        str(game_date),
        "end_date":          str(game_date),
    }

    url = METEO_ARCHIVE if use_archive else config.OPEN_METEO_BASE

    try:
        data = _get(url, base_params)
        _cache.put(key, game_date, data)
        return data
    except Exception as e:
        log.warning("Weather fetch failed (%s): %s", "archive" if use_archive else "forecast", e)
        return {}


def fetch_nrfi_odds(game_date: date) -> list[dict]:
    import config
    if not config.ODDS_API_KEY:
        log.info("No ODDS_API_KEY — skipping odds")
        return []
    try:
        data = _get(config.ODDS_API_BASE, {
            "apiKey": config.ODDS_API_KEY,
            "regions": "us", "markets": "h2h", "dateFormat": "iso",
        })
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("Odds fetch failed: %s", e)
        return []
