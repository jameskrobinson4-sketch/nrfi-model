"""
Central configuration: API keys, model weights, thresholds, park tables.
All tunable constants live here — nowhere else.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API keys ──────────────────────────────────────────────────────────────────
ODDS_API_KEY: str = os.getenv("ODDS_API_KEY", "")

# ── Base URLs ─────────────────────────────────────────────────────────────────
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
UMPIRE_SCORECARDS_BASE = "https://www.umpirescorecards.com"

# ── Module weights (must sum to 1.0) ──────────────────────────────────────────
WEIGHT_PITCHER: float = 0.35
WEIGHT_MATCHUP: float = 0.30
WEIGHT_ENVIRONMENT: float = 0.35

# ── Environment sub-weights (must sum to WEIGHT_ENVIRONMENT) ──────────────────
WEIGHT_PARK: float = 0.15
WEIGHT_WEATHER: float = 0.12
WEIGHT_UMPIRE: float = 0.08

# ── Tier thresholds (P(NRFI) as fractions) ───────────────────────────────────
TIER_A_THRESHOLD: float = 0.40  # 2-unit play — combined both halves
TIER_B_THRESHOLD: float = 0.34  # 1-unit play — combined both halves

# ── Logistic calibration — maps raw score (0-100) → probability ───────────────
# Calibrated so: 50→~52%, 65→~65%, 75→~72%, 85+→~79%+
# Derived by solving simultaneously from (50→0.52) and (75→0.72) anchor points.
LOGISTIC_SCALE: float = 0.035   # steepness
LOGISTIC_MIDPOINT: float = 47.7  # raw score at which P ≈ 50%

# ── Pitcher scoring sub-weights (must sum to 1.0) ────────────────────────────
PITCHER_W_KRATE: float = 0.20
PITCHER_W_BBRATE: float = 0.15
PITCHER_W_HRRATE: float = 0.15
PITCHER_W_FI_ERA: float = 0.25
PITCHER_W_FPS: float = 0.15       # first-pitch strike %
PITCHER_W_REST: float = 0.10

# Recent-form penalty: if last-3 ERA exceeds season ERA by this margin, penalise
PITCHER_RECENT_FORM_THRESHOLD: float = 1.5
PITCHER_RECENT_FORM_PENALTY: float = 0.10

# Fatigue flag: fewer than this many rest days
PITCHER_FATIGUE_DAYS: int = 4

# ── Matchup scoring hitter weights (must sum to 1.0) ─────────────────────────
MATCHUP_W_BATTER1: float = 0.40
MATCHUP_W_BATTER2: float = 0.35
MATCHUP_W_BATTER3: float = 0.25

# Slow-starter bonus: if first-AB OPS < season OPS by this fraction, apply bonus
MATCHUP_SLOW_START_THRESHOLD: float = 0.15
MATCHUP_SLOW_START_BONUS: float = 5.0  # raw score points

# ── Line-movement bonus / penalty ─────────────────────────────────────────────
LINE_SHARP_MOVEMENT_THRESHOLD: float = 0.15  # 15% line shortening toward yes
LINE_SHARP_BONUS: float = 5.0
LINE_SHARP_PENALTY: float = -5.0

# ── Confidence-band base uncertainty and data-gap penalty ────────────────────
CONFIDENCE_BASE_PCT: float = 3.0      # ± base band
CONFIDENCE_NO_LINEUP_PENALTY: float = 2.0  # added when lineup not confirmed

# ── Park orientations: outfield direction in degrees (0=N, 90=E, etc.) ────────
# Used to convert wind direction → blowing in / across / out relative to the park
PARK_ORIENTATIONS: dict[str, float] = {
    "ARI": 330.0,   # Chase Field — CF faces NW
    "ATL": 10.0,    # Truist Park — CF faces N/NE
    "BAL": 70.0,    # Camden Yards — CF faces ENE
    "BOS": 90.0,    # Fenway Park — CF faces E
    "CHC": 45.0,    # Wrigley Field — CF faces NE
    "CWS": 340.0,   # Guaranteed Rate — CF faces NNW
    "CIN": 20.0,    # Great American — CF faces NNE
    "CLE": 15.0,    # Progressive Field — CF faces N
    "COL": 305.0,   # Coors Field — CF faces WNW
    "DET": 35.0,    # Comerica Park — CF faces NNE
    "HOU": 350.0,   # Minute Maid — CF faces N
    "KC":  25.0,    # Kauffman Stadium — CF faces NNE
    "LAA": 60.0,    # Angel Stadium — CF faces ENE
    "LAD": 90.0,    # Dodger Stadium — CF faces E
    "MIA": 10.0,    # LoanDepot Park — CF faces N
    "MIL": 55.0,    # American Family Field — CF faces NE
    "MIN": 5.0,     # Target Field — CF faces N
    "NYM": 20.0,    # Citi Field — CF faces NNE
    "NYY": 60.0,    # Yankee Stadium — CF faces ENE
    "OAK": 290.0,   # Oakland Coliseum — CF faces WNW
    "PHI": 335.0,   # Citizens Bank — CF faces NNW
    "PIT": 90.0,    # PNC Park — CF faces E
    "SD":  310.0,   # Petco Park — CF faces WNW
    "SF":  355.0,   # Oracle Park — CF faces N
    "SEA": 315.0,   # T-Mobile Park — CF faces NW
    "STL": 40.0,    # Busch Stadium — CF faces NE
    "TB":  5.0,     # Tropicana Field — CF faces N (domed)
    "TEX": 30.0,    # Globe Life Field — CF faces NNE
    "TOR": 355.0,   # Rogers Centre — CF faces N (domed)
    "WSH": 75.0,    # Nationals Park — CF faces ENE
}

# ── Stadium coordinates (lat, lon) for weather lookup ────────────────────────
PARK_COORDS: dict[str, tuple[float, float]] = {
    "ARI": (33.4453, -112.0667),
    "ATL": (33.8908, -84.4681),
    "BAL": (39.2838, -76.6217),
    "BOS": (42.3467, -71.0972),
    "CHC": (41.9484, -87.6553),
    "CWS": (41.8300, -87.6338),
    "CIN": (39.0979, -84.5082),
    "CLE": (41.4962, -81.6853),
    "COL": (39.7559, -104.9942),
    "DET": (42.3390, -83.0485),
    "HOU": (29.7573, -95.3555),
    "KC":  (39.0517, -94.4803),
    "LAA": (33.8003, -117.8827),
    "LAD": (34.0739, -118.2400),
    "MIA": (25.7781, -80.2197),
    "MIL": (43.0280, -87.9712),
    "MIN": (44.9817, -93.2781),
    "NYM": (40.7571, -73.8458),
    "NYY": (40.8296, -73.9262),
    "OAK": (37.7516, -122.2005),
    "PHI": (39.9061, -75.1665),
    "PIT": (40.4469, -80.0057),
    "SD":  (32.7076, -117.1570),
    "SF":  (37.7786, -122.3893),
    "SEA": (47.5914, -122.3325),
    "STL": (38.6226, -90.1928),
    "TB":  (27.7683, -82.6534),
    "TEX": (32.7473, -97.0822),
    "TOR": (43.6414, -79.3894),
    "WSH": (38.8730, -77.0074),
}

# ── Domed / retractable-roof stadiums (weather has no bearing when closed) ────
DOMED_PARKS: set[str] = {"TB", "TOR", "MIA", "HOU", "ARI", "MIL", "SEA"}
