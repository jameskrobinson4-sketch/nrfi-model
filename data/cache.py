"""Simple JSON cache keyed by date. Avoids redundant API calls on re-runs."""

import json
from pathlib import Path
from datetime import date

CACHE_ROOT = Path(__file__).parent / "cache"


def _path(key: str, game_date: date) -> Path:
    return CACHE_ROOT / str(game_date) / f"{key}.json"


def get(key: str, game_date: date):
    p = _path(key, game_date)
    if p.exists():
        return json.loads(p.read_text())
    return None


def put(key: str, game_date: date, data) -> None:
    p = _path(key, game_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
