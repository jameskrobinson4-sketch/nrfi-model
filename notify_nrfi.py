#!/usr/bin/env python3
"""
Run NRFI model and push per-game ntfy notifications as lineups confirm.

Runs hourly via GitHub Actions. Each run:
  - Clears lineup, umpire, AND schedule cache so probable pitchers are always fresh
  - Re-scores all games
  - Sends one notification per newly qualifying game (Tier A/B, at least one
    lineup confirmed, score above threshold, game not yet started)
  - Tracks already-notified game_pks in output/{date}_notified.json
  - Silent run if nothing new to report
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nrfi-3d5e5fc61cbd")
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"
MODEL_DIR  = Path(__file__).parent

# Tier thresholds — must match config.py TIER_A/B_THRESHOLD values × 100.
# The game-time gate (GAME_CUTOFF_MINUTES) is the primary guard against false
# notifications; no additional score buffer is needed here.
TIER_A_THRESHOLD_PCT: float = 40.0
TIER_B_THRESHOLD_PCT: float = 34.0
NOTIFY_BUFFER_PCT:    float = 0.0

# Don't send a notification within this many minutes of first pitch —
# the bet window is effectively closed and the game may already be live.
GAME_CUTOFF_MINUTES: int = 30


# ── Cache helpers ─────────────────────────────────────────────────────────────

def clear_stale_cache():
    """
    Delete lineup, umpire, and schedule cache files before each run.

    Lineup and umpire: cleared so we always re-check whether lineups have
    posted since the last hourly run.

    Schedule: cleared so probable pitcher changes (late scratches) are always
    picked up. Without this, a pitcher cached at 10am stays all day even if
    the team makes a change at 3pm.
    """
    cache_dir = MODEL_DIR / "data" / "cache" / str(date.today())
    if not cache_dir.exists():
        return 0
    cleared = 0
    for pattern in ("lineup_*.json", "umpire_*.json", "schedule_*.json"):
        for f in cache_dir.glob(pattern):
            f.unlink()
            cleared += 1
    return cleared


# ── State tracking ────────────────────────────────────────────────────────────

def _state_path() -> Path:
    return MODEL_DIR / "output" / f"{date.today()}_notified.json"


def load_notified() -> set:
    p = _state_path()
    if p.exists():
        return set(json.loads(p.read_text()))
    return set()


def save_notified(notified: set):
    _state_path().write_text(json.dumps(sorted(notified)))


# ── Model runner ──────────────────────────────────────────────────────────────

def run_model() -> bool:
    result = subprocess.run(
        [sys.executable, "main.py", "--json"],
        cwd=MODEL_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def load_picks() -> dict:
    path = MODEL_DIR / "output" / f"{date.today()}_picks.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ── Qualification checks ──────────────────────────────────────────────────────

def _meets_notify_threshold(pick: dict) -> bool:
    """Score must be clearly above tier threshold, not just at the edge."""
    prob = pick["p_nrfi_pct"]
    tier = pick["tier"]
    if tier == "A":
        return prob >= TIER_A_THRESHOLD_PCT + NOTIFY_BUFFER_PCT
    if tier == "B":
        return prob >= TIER_B_THRESHOLD_PCT + NOTIFY_BUFFER_PCT
    return False


def _game_still_open(pick: dict, ts: str) -> bool:
    """
    Return True if there is still time to place a bet before first pitch.

    When first_pitch_utc is missing or unparseable we allow the notification
    rather than silently dropping a qualifying pick — lineup confirmation is
    already the primary gate.
    """
    fp_str = pick.get("first_pitch_utc", "")
    game   = pick.get("game", "?")

    if not fp_str:
        # Unknown start time — don't block a qualifying pick just because the
        # schedule didn't return a game time (happens on rescheduled/makeup games).
        print(f"[{ts}] WARN {game} — no first_pitch_utc, sending anyway")
        return True

    try:
        fp_dt   = datetime.fromisoformat(fp_str.replace("Z", "+00:00"))
        utcnow  = datetime.now(timezone.utc)
        cutoff  = fp_dt - timedelta(minutes=GAME_CUTOFF_MINUTES)
        if utcnow >= cutoff:
            if utcnow >= fp_dt:
                mins_past = int((utcnow - fp_dt).total_seconds() / 60)
                print(f"[{ts}] SKIP {game} — game already started ({mins_past}m ago)")
            else:
                mins_left = int((fp_dt - utcnow).total_seconds() / 60)
                print(f"[{ts}] SKIP {game} — only {mins_left}m to first pitch, cutoff is {GAME_CUTOFF_MINUTES}m")
            return False
        return True
    except (ValueError, TypeError) as e:
        # Unparseable time — treat the same as missing: allow through
        print(f"[{ts}] WARN {game} — could not parse first_pitch_utc '{fp_str}' ({e}), sending anyway")
        return True


# ── Notification formatting ───────────────────────────────────────────────────

def _hitter_line(hitters: list, team: str) -> str:
    parts = []
    for h in hitters[:3]:
        last = h["name"].split()[-1]
        parts.append(f"{last} .{int(round(h['obp'] * 1000)):03d}")
    return f"{team}: " + " · ".join(parts)


def _pitcher_line(half: dict, side_label: str) -> str:
    pc   = half["pitcher_components"]
    ip   = pc.get("ip", 0)
    hand = half["pitcher_hand"]
    return (
        f"{side_label}  {half['pitcher']} ({hand}HP)"
        f"  {half['pitcher_score']:.0f}/100 · {ip:.0f} IP"
        f"  →  {half['p_scoreless']:.0f}% scoreless"
    )


def format_pick(pick: dict) -> tuple[str, str, str]:
    """Return (title, body, priority) for a single confirmed qualifying pick."""
    tier  = pick["tier"]
    game  = pick["game"]
    time  = pick["time"]
    prob  = pick["p_nrfi_pct"]
    band  = pick["confidence_band"]
    raw   = pick["raw_score"]
    top   = pick["top_1st"]
    bot   = pick["bot_1st"]
    env   = pick["environment"]["components"]

    away, home = game.split("@")
    stake = "2u" if tier == "A" else "1u"
    icon  = "★" if tier == "A" else "▸"

    title = f"{icon} NRFI Tier {tier} ({stake}) — {game}  {time}"

    ump_name = env.get("umpire_name", "")
    ump_str  = f"{env.get('umpire', 50):.0f}"
    if ump_name:
        ump_str += f" ({ump_name})"

    wx_flag = next(
        (f for f in pick.get("flags", []) if "mph" in f or "°F" in f or "%rh" in f),
        "",
    )

    lines = [
        f"P(NRFI): {prob}%  ±{band}%  [raw {raw:.0f}/100]",
        "",
        _pitcher_line(top, "▲ TOP"),
        f"  {_hitter_line(top.get('hitters', []), away)}",
        "",
        _pitcher_line(bot, "▼ BOT"),
        f"  {_hitter_line(bot.get('hitters', []), home)}",
        "",
        f"Park {env.get('park', 50):.0f}  ·  Wx {env.get('weather', 50):.0f}  ·  Ump {ump_str}",
    ]
    if wx_flag:
        lines.append(f"🌡 {wx_flag}")
    top_lc = pick["top_1st"].get("lineup_confirmed", False)
    bot_lc = pick["bot_1st"].get("lineup_confirmed", False)
    if top_lc and bot_lc:
        lines.append("✅ Both lineups confirmed")
    elif top_lc:
        lines.append(f"⚠️ {away} lineup confirmed — {home} lineup pending")
    else:
        lines.append(f"⚠️ {home} lineup confirmed — {away} lineup pending")

    body     = "\n".join(lines)
    priority = "high" if tier == "A" else "default"
    return title, body, priority


# ── ntfy sender ───────────────────────────────────────────────────────────────

def send(title: str, body: str, priority: str, tags: str = "baseball"):
    try:
        resp = requests.post(
            "https://ntfy.sh/",
            json={
                "topic":    NTFY_TOPIC,
                "title":    title,
                "message":  body,
                "priority": {"high": 4, "default": 3, "low": 2}.get(priority, 3),
                "tags":     [tags],
            },
            timeout=10,
        )
        resp.raise_for_status()
        print(f"[{datetime.now().strftime('%H:%M')}] Sent: {title}")
    except Exception as e:
        print(f"Notification failed: {e}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ts = datetime.now().strftime("%H:%M")

    cleared = clear_stale_cache()
    print(f"[{ts}] Cleared {cleared} stale cache files (lineup + umpire + schedule)")

    print(f"[{ts}] Running model...")
    if not run_model():
        print(f"[{ts}] Model failed — skipping notifications", file=sys.stderr)
        sys.exit(1)

    data = load_picks()
    if not data:
        print(f"[{ts}] No picks data — skipping", file=sys.stderr)
        sys.exit(0)

    picks    = data.get("picks", [])
    notified = load_notified()

    # Step 1: at least one lineup confirmed (requiring BOTH misses picks where one
    # team posts early; the model already degrades gracefully on unconfirmed halves)
    lineup_confirmed = [
        p for p in picks
        if p["top_1st"].get("lineup_confirmed", False)
        or p["bot_1st"].get("lineup_confirmed", False)
    ]

    # Step 2: tier A or B AND score is clearly above threshold (not right at boundary)
    above_threshold = [p for p in lineup_confirmed if _meets_notify_threshold(p)]

    # Step 3: not already sent
    not_yet_notified = [p for p in above_threshold if str(p["game_pk"]) not in notified]

    # Step 4: game hasn't started yet (gate against post-game notifications)
    sendable = [p for p in not_yet_notified if _game_still_open(p, ts)]

    print(
        f"[{ts}] {len(picks)} games scored  ·  "
        f"{len(lineup_confirmed)} lineups confirmed  ·  "
        f"{len(above_threshold)} above threshold  ·  "
        f"{len(not_yet_notified)} not yet notified  ·  "
        f"{len(sendable)} to send now"
    )

    # Log anything confirmed + above threshold but already notified (informational)
    already_sent = [p for p in above_threshold if str(p["game_pk"]) in notified]
    for p in already_sent:
        print(f"[{ts}] already notified: {p['game']} {p['p_nrfi_pct']}%")

    # Log anything confirmed + tier-qualifying but below the buffer threshold
    borderline = [
        p for p in lineup_confirmed
        if p["tier"] in ("A", "B") and not _meets_notify_threshold(p)
    ]
    for p in borderline:
        tier_floor = TIER_A_THRESHOLD_PCT if p["tier"] == "A" else TIER_B_THRESHOLD_PCT
        print(
            f"[{ts}] borderline {p['game']} {p['p_nrfi_pct']}% "
            f"(Tier {p['tier']} floor {tier_floor}%, buffer +{NOTIFY_BUFFER_PCT}%)"
        )

    for pick in sendable:
        title, body, priority = format_pick(pick)
        send(title, body, priority)
        notified.add(str(pick["game_pk"]))

    save_notified(notified)
